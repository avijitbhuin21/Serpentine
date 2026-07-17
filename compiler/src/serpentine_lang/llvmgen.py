"""Backend B: typed AST -> LLVM IR via llvmlite (RESEARCH.md section 4, item 5b).

Covers the numeric Tier-0 core: int/float/bool locals and parameters, full
CPython arithmetic semantics (overflow traps, floor division, zero-division
errors), if/while/for-range control flow, function calls (including
monomorphized generic instantiations), and print of ints/bools/string
literals. Everything else raises LLVMUnsupported — `serp build` (Backend A,
Rust) remains the full-language path. Like Backend A, this backend emits from
the typed AST; SIR drives the ownership analyses.

Divergence note: trap messages are written to stdout by the C printf, not
stderr; exit code parity (1) is preserved.
"""

import ast

from llvmlite import ir

from .frontend import Module
from .ptypes import TBool, TFloat, TInt, TNone, TStr, Type
from .typecheck import FuncSig, TypeChecker

I64 = ir.IntType(64)
I32 = ir.IntType(32)
I8 = ir.IntType(8)
I1 = ir.IntType(1)
F64 = ir.DoubleType()
VOID = ir.VoidType()
I8P = I8.as_pointer()

OVERFLOW_MSG = "OverflowError: Serpentine int operation overflowed 64 bits"


class LLVMUnsupported(Exception):
    """The program uses features outside the Backend-B numeric core."""


def _lty(t: Type):
    if isinstance(t, TInt):
        return I64
    if isinstance(t, TFloat):
        return F64
    if isinstance(t, TBool):
        return I1
    if isinstance(t, TNone):
        return VOID
    raise LLVMUnsupported(f"type {t} is not in the LLVM numeric core")


class LLVMGen:
    """Whole-program LLVM IR generator for the numeric core."""

    def __init__(self, tc: TypeChecker):
        self.tc = tc
        self.module = ir.Module(name="serpentine")
        self.strings: dict[str, ir.GlobalVariable] = {}
        self.printf = ir.Function(
            self.module, ir.FunctionType(I32, [I8P], var_arg=True), name="printf")
        self.exit_fn = ir.Function(
            self.module, ir.FunctionType(VOID, [I32]), name="exit")
        self.funcs: dict[tuple[str, str], ir.Function] = {}
        self._make_trap()

    # ---------- infrastructure ----------

    def _cstr(self, text: str) -> ir.GlobalVariable:
        """An interned NUL-terminated global string constant."""
        if text in self.strings:
            return self.strings[text]
        data = bytearray(text.encode("utf-8")) + bytearray(b"\x00")
        ty = ir.ArrayType(I8, len(data))
        gv = ir.GlobalVariable(self.module, ty, name=f".str{len(self.strings)}")
        gv.linkage = "internal"
        gv.global_constant = True
        gv.initializer = ir.Constant(ty, data)
        self.strings[text] = gv
        return gv

    def _cstr_ptr(self, builder: ir.IRBuilder, text: str):
        gv = self._cstr(text)
        return builder.bitcast(gv, I8P)

    def _make_trap(self) -> None:
        """define internal void @serp_trap(i8* msg): print message, exit(1)."""
        fnty = ir.FunctionType(VOID, [I8P])
        fn = ir.Function(self.module, fnty, name="serp_trap")
        fn.linkage = "internal"
        block = fn.append_basic_block("entry")
        b = ir.IRBuilder(block)
        fmt = self._cstr("%s\n")
        b.call(self.printf, [b.bitcast(fmt, I8P), fn.args[0]])
        b.call(self.exit_fn, [ir.Constant(I32, 1)])
        b.unreachable()
        self.trap = fn

    def _trap(self, builder: ir.IRBuilder, cond, msg: str) -> None:
        """Branch to a trap that prints msg and exits when cond is true."""
        fn = builder.function
        bad = fn.append_basic_block("trap")
        ok = fn.append_basic_block("ok")
        builder.cbranch(cond, bad, ok)
        builder.position_at_end(bad)
        builder.call(self.trap, [self._cstr_ptr(builder, msg)])
        builder.unreachable()
        builder.position_at_end(ok)

    # ---------- program ----------

    def generate(self) -> ir.Module:
        """Emit every checked function plus main; raises LLVMUnsupported."""
        sigs = [s for (m, n), s in self.tc.sigs.items()
                if not s.is_template and (s.module, s.name) in self.tc.facts]
        for sig in sigs:
            self._declare_function(sig)
        for sig in sigs:
            self._emit_function(sig)
        entry = self.tc.program.entry
        if entry.entry_call is None:
            raise LLVMUnsupported("no entry point")
        mainty = ir.FunctionType(I32, [])
        main = ir.Function(self.module, mainty, name="main")
        b = ir.IRBuilder(main.append_basic_block("entry"))
        b.call(self.funcs[(entry.name, entry.entry_call)], [])
        b.ret(ir.Constant(I32, 0))
        return self.module

    def _declare_function(self, sig: FuncSig) -> None:
        for p in sig.params:
            if p.conv != "copy":
                raise LLVMUnsupported(
                    f"parameter '{p.name}' of '{sig.name}' is not a Copy scalar")
        argtys = [_lty(p.typ) for p in sig.params]
        fnty = ir.FunctionType(_lty(sig.ret), argtys)
        name = f"f_{sig.module}_{sig.name}".replace(".", "_").replace("[", "_") \
            .replace("]", "_").replace(",", "_").replace(" ", "")
        fn = ir.Function(self.module, fnty, name=name)
        self.funcs[(sig.module, sig.name)] = fn

    def _emit_function(self, sig: FuncSig) -> None:
        fn = self.funcs[(sig.module, sig.name)]
        self.sig = sig
        self.mod: Module = self.tc.program.modules[sig.module]
        self.facts = self.tc.facts[(sig.module, sig.name)]
        self.builder = ir.IRBuilder(fn.append_basic_block("entry"))
        self.slots: dict[str, ir.Value] = {}
        self.loop_stack: list[tuple[ir.Block, ir.Block]] = []   # (continue, break)
        for name, t in self.facts.locals.items():
            self.slots[name] = self.builder.alloca(_lty(t), name=f"v_{name}")
        for p, arg in zip(sig.params, fn.args):
            arg.name = f"a_{p.name}"
            self.builder.store(arg, self.slots[p.name])
        body = sig.node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            body = body[1:]
        self._block(body)
        if not self.builder.block.is_terminated:
            if isinstance(sig.ret, TNone):
                self.builder.ret_void()
            else:
                self.builder.unreachable()

    # ---------- statements ----------

    def _block(self, stmts: list[ast.stmt]) -> None:
        for s in stmts:
            if self.builder.block.is_terminated:
                return
            self._stmt(s)

    def _stmt(self, s: ast.stmt) -> None:
        if isinstance(s, ast.Pass):
            return
        if isinstance(s, ast.Return):
            if s.value is None:
                self.builder.ret_void()
            else:
                v = self._coerced(s.value, self.sig.ret)
                self.builder.ret(v)
            return
        if isinstance(s, (ast.Assign, ast.AnnAssign)):
            target = s.targets[0] if isinstance(s, ast.Assign) else s.target
            if not isinstance(target, ast.Name) or s.value is None:
                raise LLVMUnsupported("only scalar name assignment is supported")
            t = self.facts.locals[target.id]
            self.builder.store(self._coerced(s.value, t), self.slots[target.id])
            return
        if isinstance(s, ast.AugAssign):
            if not isinstance(s.target, ast.Name):
                raise LLVMUnsupported("augmented assignment target")
            t = self.facts.locals[s.target.id]
            cur = self.builder.load(self.slots[s.target.id])
            rhs = self._expr(s.value)
            v = self._binop(s.op, cur, self._t(s.target), rhs, self._t(s.value))
            self.builder.store(self._coerce_val(v, self._result_t(s.op, self._t(s.target),
                                                                  self._t(s.value)), t),
                               self.slots[s.target.id])
            return
        if isinstance(s, ast.Expr):
            e = s.value
            if isinstance(e, ast.Call) and isinstance(e.func, ast.Name) and e.func.id == "print":
                self._print(e)
                return
            self._expr(e)
            return
        if isinstance(s, ast.If):
            self._if(s)
            return
        if isinstance(s, ast.While):
            self._while(s)
            return
        if isinstance(s, ast.For):
            self._for(s)
            return
        if isinstance(s, ast.Break):
            self.builder.branch(self.loop_stack[-1][1])
            return
        if isinstance(s, ast.Continue):
            self.builder.branch(self.loop_stack[-1][0])
            return
        raise LLVMUnsupported(f"statement {type(s).__name__}")

    def _if(self, s: ast.If) -> None:
        cond = self._expr(s.test)
        fn = self.builder.function
        then_b = fn.append_basic_block("then")
        else_b = fn.append_basic_block("else") if s.orelse else None
        join = fn.append_basic_block("join")
        self.builder.cbranch(cond, then_b, else_b or join)
        self.builder.position_at_end(then_b)
        self._block(s.body)
        if not self.builder.block.is_terminated:
            self.builder.branch(join)
        if else_b is not None:
            self.builder.position_at_end(else_b)
            self._block(s.orelse)
            if not self.builder.block.is_terminated:
                self.builder.branch(join)
        self.builder.position_at_end(join)

    def _while(self, s: ast.While) -> None:
        fn = self.builder.function
        head = fn.append_basic_block("while.head")
        body = fn.append_basic_block("while.body")
        exit_b = fn.append_basic_block("while.exit")
        self.builder.branch(head)
        self.builder.position_at_end(head)
        cond = self._expr(s.test)
        self.builder.cbranch(cond, body, exit_b)
        self.builder.position_at_end(body)
        self.loop_stack.append((head, exit_b))
        self._block(s.body)
        self.loop_stack.pop()
        if not self.builder.block.is_terminated:
            self.builder.branch(head)
        self.builder.position_at_end(exit_b)

    def _for(self, s: ast.For) -> None:
        it = s.iter
        if not (isinstance(it, ast.Call) and isinstance(it.func, ast.Name)
                and it.func.id == "range" and isinstance(s.target, ast.Name)):
            raise LLVMUnsupported("only for-over-range loops are supported")
        args = [self._expr(a) for a in it.args]
        zero = ir.Constant(I64, 0)
        one = ir.Constant(I64, 1)
        if len(args) == 1:
            start, stop, step = zero, args[0], one
        elif len(args) == 2:
            start, stop, step = args[0], args[1], one
        else:
            start, stop, step = args
            self._trap(self.builder, self.builder.icmp_signed("==", step, zero),
                       "ValueError: range() arg 3 must not be zero")
        slot = self.slots[s.target.id]
        self.builder.store(start, slot)
        fn = self.builder.function
        head = fn.append_basic_block("for.head")
        body = fn.append_basic_block("for.body")
        incr = fn.append_basic_block("for.incr")
        exit_b = fn.append_basic_block("for.exit")
        self.builder.branch(head)
        self.builder.position_at_end(head)
        i = self.builder.load(slot)
        pos = self.builder.icmp_signed(">", step, zero)
        lt = self.builder.icmp_signed("<", i, stop)
        gt = self.builder.icmp_signed(">", i, stop)
        cond = self.builder.select(pos, lt, gt)
        self.builder.cbranch(cond, body, exit_b)
        self.builder.position_at_end(body)
        self.loop_stack.append((incr, exit_b))
        self._block(s.body)
        self.loop_stack.pop()
        if not self.builder.block.is_terminated:
            self.builder.branch(incr)
        self.builder.position_at_end(incr)
        nxt = self.builder.add(self.builder.load(slot), step)
        self.builder.store(nxt, slot)
        self.builder.branch(head)
        self.builder.position_at_end(exit_b)

    def _print(self, e: ast.Call) -> None:
        fmt_parts: list[str] = []
        args: list[ir.Value] = []
        for a in e.args:
            t = self.tc.expr_types.get(id(a))
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                fmt_parts.append("%s")
                args.append(self._cstr_ptr(self.builder, a.value))
            elif isinstance(t, TInt):
                fmt_parts.append("%lld")
                args.append(self._expr(a))
            elif isinstance(t, TBool):
                fmt_parts.append("%s")
                v = self._expr(a)
                args.append(self.builder.select(
                    v, self._cstr_ptr(self.builder, "True"),
                    self._cstr_ptr(self.builder, "False")))
            else:
                raise LLVMUnsupported(f"print of {t} (numeric core prints int/bool/str "
                                      f"literals)")
        fmt = self._cstr_ptr(self.builder, " ".join(fmt_parts) + "\n")
        self.builder.call(self.printf, [fmt] + args)

    # ---------- expressions ----------

    def _t(self, node: ast.expr) -> Type:
        t = self.tc.expr_types.get(id(node))
        if t is None:
            raise LLVMUnsupported("untyped expression")
        return t

    def _result_t(self, op: ast.operator, lt: Type, rt: Type) -> Type:
        if isinstance(op, ast.Div):
            return TFloat()
        if isinstance(lt, TFloat) or isinstance(rt, TFloat):
            return TFloat()
        return TInt()

    def _coerce_val(self, v: ir.Value, src: Type, dst: Type) -> ir.Value:
        if isinstance(src, TInt) and isinstance(dst, TFloat):
            return self.builder.sitofp(v, F64)
        return v

    def _coerced(self, node: ast.expr, dst: Type) -> ir.Value:
        return self._coerce_val(self._expr(node), self._t(node), dst)

    def _expr(self, e: ast.expr) -> ir.Value:
        if isinstance(e, ast.Constant):
            v = e.value
            if isinstance(v, bool):
                return ir.Constant(I1, int(v))
            if isinstance(v, int):
                return ir.Constant(I64, v)
            if isinstance(v, float):
                return ir.Constant(F64, v)
            raise LLVMUnsupported(f"literal {v!r}")
        if isinstance(e, ast.Name):
            if e.id not in self.slots:
                const = self.tc.constants.get((self.mod.name, e.id))
                if const is not None:
                    cnode = self.mod.constants[e.id].value
                    assert isinstance(cnode, ast.Constant)
                    self.tc.expr_types[id(cnode)] = const
                    return self._expr(cnode)
                raise LLVMUnsupported(f"name {e.id}")
            return self.builder.load(self.slots[e.id])
        if isinstance(e, ast.BinOp):
            l = self._expr(e.left)
            r = self._expr(e.right)
            return self._binop(e.op, l, self._t(e.left), r, self._t(e.right))
        if isinstance(e, ast.UnaryOp):
            return self._unary(e)
        if isinstance(e, ast.BoolOp):
            return self._boolop(e)
        if isinstance(e, ast.Compare):
            return self._compare(e)
        if isinstance(e, ast.IfExp):
            return self._ifexp(e)
        if isinstance(e, ast.Call):
            return self._call(e)
        raise LLVMUnsupported(f"expression {type(e).__name__}")

    def _intrinsic(self, name: str, ret, argtys) -> ir.Function:
        """Declare (once) an LLVM intrinsic with an explicit signature."""
        if name in self.module.globals:
            return self.module.globals[name]
        return ir.Function(self.module, ir.FunctionType(ret, argtys), name=name)

    def _checked_arith(self, intrinsic: str, l, r) -> ir.Value:
        fn = self._intrinsic(f"{intrinsic}.i64",
                             ir.LiteralStructType([I64, I1]), [I64, I64])
        res = self.builder.call(fn, [l, r])
        val = self.builder.extract_value(res, 0)
        ovf = self.builder.extract_value(res, 1)
        self._trap(self.builder, ovf, OVERFLOW_MSG)
        return val

    def _binop(self, op: ast.operator, l, lt: Type, r, rt: Type) -> ir.Value:
        both_int = isinstance(lt, TInt) and isinstance(rt, TInt)
        if both_int and not isinstance(op, ast.Div):
            zero = ir.Constant(I64, 0)
            if isinstance(op, ast.Add):
                return self._checked_arith("llvm.sadd.with.overflow", l, r)
            if isinstance(op, ast.Sub):
                return self._checked_arith("llvm.ssub.with.overflow", l, r)
            if isinstance(op, ast.Mult):
                return self._checked_arith("llvm.smul.with.overflow", l, r)
            if isinstance(op, (ast.FloorDiv, ast.Mod)):
                self._trap(self.builder, self.builder.icmp_signed("==", r, zero),
                           "ZeroDivisionError: integer division or modulo by zero")
                q = self.builder.sdiv(l, r)
                rem = self.builder.srem(l, r)
                # CPython flooring: adjust when signs differ and remainder nonzero
                nz = self.builder.icmp_signed("!=", rem, zero)
                ls = self.builder.icmp_signed("<", l, zero)
                rs = self.builder.icmp_signed("<", r, zero)
                diff = self.builder.xor(ls, rs)
                adj = self.builder.and_(nz, diff)
                if isinstance(op, ast.FloorDiv):
                    qm1 = self.builder.sub(q, ir.Constant(I64, 1))
                    return self.builder.select(adj, qm1, q)
                remb = self.builder.add(rem, r)
                return self.builder.select(adj, remb, rem)
            if isinstance(op, ast.Pow):
                return self._ipow(l, r)
            raise LLVMUnsupported(f"int operator {type(op).__name__}")
        lf = self.builder.sitofp(l, F64) if isinstance(lt, TInt) else l
        rf = self.builder.sitofp(r, F64) if isinstance(rt, TInt) else r
        fzero = ir.Constant(F64, 0.0)
        if isinstance(op, ast.Add):
            return self.builder.fadd(lf, rf)
        if isinstance(op, ast.Sub):
            return self.builder.fsub(lf, rf)
        if isinstance(op, ast.Mult):
            return self.builder.fmul(lf, rf)
        if isinstance(op, ast.Div):
            msg = "ZeroDivisionError: division by zero" if isinstance(lt, TInt) \
                and isinstance(rt, TInt) else "ZeroDivisionError: float division by zero"
            self._trap(self.builder, self.builder.fcmp_ordered("==", rf, fzero), msg)
            return self.builder.fdiv(lf, rf)
        if isinstance(op, ast.FloorDiv):
            self._trap(self.builder, self.builder.fcmp_ordered("==", rf, fzero),
                       "ZeroDivisionError: float floor division")
            d = self.builder.fdiv(lf, rf)
            floor = self._intrinsic("llvm.floor.f64", F64, [F64])
            return self.builder.call(floor, [d])
        raise LLVMUnsupported(f"float operator {type(op).__name__}")

    def _ipow(self, base, exp) -> ir.Value:
        """CPython int ** with overflow checks via a loop (square-and-multiply)."""
        b = self.builder
        zero = ir.Constant(I64, 0)
        self._trap(b, b.icmp_signed("<", exp, zero),
                   "OverflowError: Serpentine Tier-0 int ** requires a non-negative exponent")
        fn = b.function
        res_slot = b.alloca(I64)
        base_slot = b.alloca(I64)
        exp_slot = b.alloca(I64)
        b.store(ir.Constant(I64, 1), res_slot)
        b.store(base, base_slot)
        b.store(exp, exp_slot)
        head = fn.append_basic_block("pow.head")
        body = fn.append_basic_block("pow.body")
        exit_b = fn.append_basic_block("pow.exit")
        b.branch(head)
        b.position_at_end(head)
        e = b.load(exp_slot)
        b.cbranch(b.icmp_signed(">", e, zero), body, exit_b)
        b.position_at_end(body)
        e = b.load(exp_slot)
        odd = b.trunc(b.and_(e, ir.Constant(I64, 1)), I1)
        cur = b.load(res_slot)
        mul = self._checked_arith("llvm.smul.with.overflow", cur, b.load(base_slot))
        b.store(b.select(odd, mul, cur), res_slot)
        e2 = b.ashr(e, ir.Constant(I64, 1))
        b.store(e2, exp_slot)
        sq_needed = b.icmp_signed(">", e2, zero)
        cur_base = b.load(base_slot)
        sq = self._checked_arith("llvm.smul.with.overflow", cur_base, cur_base)
        b.store(b.select(sq_needed, sq, cur_base), base_slot)
        b.branch(head)
        b.position_at_end(exit_b)
        return b.load(res_slot)

    def _unary(self, e: ast.UnaryOp) -> ir.Value:
        v = self._expr(e.operand)
        t = self._t(e.operand)
        if isinstance(e.op, ast.Not):
            return self.builder.not_(v)
        if isinstance(e.op, ast.USub):
            if isinstance(t, TInt):
                return self._checked_arith("llvm.ssub.with.overflow",
                                           ir.Constant(I64, 0), v)
            return self.builder.fneg(v)
        if isinstance(e.op, ast.UAdd):
            return v
        raise LLVMUnsupported("unary operator")

    def _boolop(self, e: ast.BoolOp) -> ir.Value:
        """Short-circuit and/or via control flow and a phi."""
        fn = self.builder.function
        result = self.builder.alloca(I1)
        end = fn.append_basic_block("bool.end")
        is_and = isinstance(e.op, ast.And)
        for i, operand in enumerate(e.values):
            v = self._expr(operand)
            self.builder.store(v, result)
            if i == len(e.values) - 1:
                self.builder.branch(end)
            else:
                nxt = fn.append_basic_block("bool.next")
                if is_and:
                    self.builder.cbranch(v, nxt, end)
                else:
                    self.builder.cbranch(v, end, nxt)
                self.builder.position_at_end(nxt)
        self.builder.position_at_end(end)
        return self.builder.load(result)

    def _cmp_pair(self, op: ast.cmpop, l, lt: Type, r, rt: Type) -> ir.Value:
        table = {ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=",
                 ast.Gt: ">", ast.GtE: ">="}
        if type(op) not in table:
            raise LLVMUnsupported("comparison operator")
        sym = table[type(op)]
        if isinstance(lt, TFloat) or isinstance(rt, TFloat):
            lf = self.builder.sitofp(l, F64) if isinstance(lt, TInt) else l
            rf = self.builder.sitofp(r, F64) if isinstance(rt, TInt) else r
            return self.builder.fcmp_ordered(sym, lf, rf)
        return self.builder.icmp_signed(sym, l, r)

    def _compare(self, e: ast.Compare) -> ir.Value:
        operands = [e.left] + list(e.comparators)
        vals = [self._expr(o) for o in operands]
        types = [self._t(o) for o in operands]
        acc = None
        for i, op in enumerate(e.ops):
            c = self._cmp_pair(op, vals[i], types[i], vals[i + 1], types[i + 1])
            acc = c if acc is None else self.builder.and_(acc, c)
        assert acc is not None
        return acc

    def _ifexp(self, e: ast.IfExp) -> ir.Value:
        t = self._t(e)
        fn = self.builder.function
        slot = self.builder.alloca(_lty(t))
        then_b = fn.append_basic_block("ternary.then")
        else_b = fn.append_basic_block("ternary.else")
        end = fn.append_basic_block("ternary.end")
        self.builder.cbranch(self._expr(e.test), then_b, else_b)
        self.builder.position_at_end(then_b)
        self.builder.store(self._coerced(e.body, t), slot)
        self.builder.branch(end)
        self.builder.position_at_end(else_b)
        self.builder.store(self._coerced(e.orelse, t), slot)
        self.builder.branch(end)
        self.builder.position_at_end(end)
        return self.builder.load(slot)

    def _call(self, e: ast.Call) -> ir.Value:
        if not isinstance(e.func, ast.Name):
            raise LLVMUnsupported("method calls")
        name = e.func.id
        if id(e) in self.tc.move_calls:
            return self._expr(e.args[0])
        target = self.tc.call_targets.get(id(e))
        if target is None and self.tc._resolve_callee(self.mod, name) is not None:
            sig = self.tc._resolve_callee(self.mod, name)
            target = (sig.module, sig.name)
        if target is not None:
            sig = self.tc.sigs[target]
            args = [self._coerced(a, p.typ) for a, p in zip(e.args, sig.params)]
            return self.builder.call(self.funcs[target], args)
        return self._builtin(e, name)

    def _builtin(self, e: ast.Call, name: str) -> ir.Value:
        b = self.builder
        if name == "abs":
            t = self._t(e.args[0])
            v = self._expr(e.args[0])
            if isinstance(t, TInt):
                neg = self._checked_arith("llvm.ssub.with.overflow", ir.Constant(I64, 0), v)
                return b.select(b.icmp_signed("<", v, ir.Constant(I64, 0)), neg, v)
            fabs = self._intrinsic("llvm.fabs.f64", F64, [F64])
            return b.call(fabs, [v])
        if name in ("min", "max") and len(e.args) == 2:
            l = self._expr(e.args[0])
            r = self._expr(e.args[1])
            lt, rt = self._t(e.args[0]), self._t(e.args[1])
            c = self._cmp_pair(ast.Lt() if name == "min" else ast.Gt(), r, rt, l, lt)
            return b.select(c, r, l)
        if name == "float":
            t = self._t(e.args[0])
            v = self._expr(e.args[0])
            if isinstance(t, TInt):
                return b.sitofp(v, F64)
            if isinstance(t, TFloat):
                return v
            raise LLVMUnsupported("float() argument")
        if name == "int":
            t = self._t(e.args[0])
            v = self._expr(e.args[0])
            if isinstance(t, TInt):
                return v
            if isinstance(t, TBool):
                return b.zext(v, I64)
            if isinstance(t, TFloat):
                trunc = self._intrinsic("llvm.trunc.f64", F64, [F64])
                return b.fptosi(b.call(trunc, [v]), I64)
            raise LLVMUnsupported("int() argument")
        if name == "bool":
            t = self._t(e.args[0])
            v = self._expr(e.args[0])
            if isinstance(t, TInt):
                return b.icmp_signed("!=", v, ir.Constant(I64, 0))
            if isinstance(t, TBool):
                return v
            raise LLVMUnsupported("bool() argument")
        raise LLVMUnsupported(f"builtin '{name}'")


def generate_llvm(tc: TypeChecker) -> str:
    """Generate textual LLVM IR for a checked numeric-core program."""
    return str(LLVMGen(tc).generate())


def run_llvm(tc: TypeChecker, opt: int = 2) -> int:
    """JIT-compile and execute the program in-process; returns main's exit code."""
    import ctypes
    import sys as _sys

    import llvmlite.binding as llvm

    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    if _sys.platform == "win32":
        llvm.load_library_permanently("msvcrt.dll")
    ir_text = generate_llvm(tc)
    mod = llvm.parse_assembly(ir_text)
    mod.verify()
    target = llvm.Target.from_default_triple()
    tm = target.create_target_machine(opt=opt)
    engine = llvm.create_mcjit_compiler(mod, tm)
    engine.finalize_object()
    _sys.stdout.flush()
    addr = engine.get_function_address("main")
    rc = ctypes.CFUNCTYPE(ctypes.c_int)(addr)()
    if _sys.platform == "win32":
        ctypes.CDLL("msvcrt").fflush(None)
    else:
        ctypes.CDLL(None).fflush(None)
    return rc
