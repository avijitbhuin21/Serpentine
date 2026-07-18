"""SIR: Serpentine IR — CFG of basic blocks with explicit use/move/borrow/drop ops.

Lowered from the typed AST; consumed by the ownership analyses in borrowck.py.
Tier-0 places are variable roots (projections collapse to their root — field
sensitivity is Phase-2 work).
"""

import ast
from dataclasses import dataclass, field

from .typecheck import TypeChecker, FuncSig


@dataclass
class Instr:
    """One SIR operation on a place root."""

    kind: str          # use | mut_use | move | def | drop | borrow_begin | borrow_end
    var: str
    node: ast.AST
    loans: frozenset = frozenset()   # active (var, kind) loans at this instruction


@dataclass
class Block:
    """A basic block: straight-line instructions plus successor edges."""

    id: int
    instrs: list[Instr] = field(default_factory=list)
    succs: list[int] = field(default_factory=list)
    is_exit: bool = False


@dataclass
class FuncSIR:
    """The SIR of one function."""

    sig: FuncSig
    blocks: list[Block] = field(default_factory=list)
    entry: int = 0

    def dump(self) -> str:
        """Human-readable SIR listing for `serp check --dump-sir`."""
        out = [f"fn {self.sig.module}::{self.sig.name}"]
        for b in self.blocks:
            tail = " (exit)" if b.is_exit else f" -> {b.succs}"
            out.append(f"  bb{b.id}{tail}")
            for i in b.instrs:
                loans = f"  [loans: {sorted(i.loans)}]" if i.loans else ""
                out.append(f"    {i.kind} {i.var}{loans}")
        return "\n".join(out)


class Lowerer:
    """AST -> SIR lowering for one function."""

    def __init__(self, tc: TypeChecker, sig: FuncSig):
        self.tc = tc
        self.sig = sig
        self.sir = FuncSIR(sig=sig)
        self.cur: Block = self._new_block()
        self.loan_stack: list[tuple[str, str]] = []
        self.loop_stack: list[tuple[int, int]] = []   # (head_id, exit_id)
        self.handler_stack: list[int] = []            # entry block of enclosing try handlers
        self.noncopy_locals: list[str] = []

    def _new_block(self) -> Block:
        b = Block(id=len(self.sir.blocks))
        self.sir.blocks.append(b)
        return b

    def _emit(self, kind: str, var: str, node: ast.AST) -> None:
        self.cur.instrs.append(Instr(kind, var, node, frozenset(self.loan_stack)))

    def _goto(self, target: Block) -> None:
        if not self.cur.is_exit:
            self.cur.succs.append(target.id)

    def lower(self) -> FuncSIR:
        """Lower the function body to SIR, inserting drops at scope exits."""
        facts = self.tc.facts[(self.sig.module, self.sig.name)]
        self.noncopy_locals = [n for n, t in facts.locals.items() if not t.is_copy()]
        for p in self.sig.params:
            self._emit("def", p.name, self.sig.node)
        body = self.sig.node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            body = body[1:]
        self._lower_block(body)
        if not self.cur.is_exit:
            self._emit_drops(self.sig.node)
            self.cur.is_exit = True
        return self.sir

    def _emit_drops(self, node: ast.AST) -> None:
        for name in reversed(self.noncopy_locals):
            self._emit("drop", name, node)

    def _lower_block(self, stmts: list[ast.stmt]) -> None:
        for stmt in stmts:
            if self.cur.is_exit:
                return
            self._lower_stmt(stmt)

    def _lower_stmt(self, stmt: ast.stmt) -> None:
        if isinstance(stmt, ast.With):
            item = stmt.items[0]
            self._lower_expr(item.context_expr)
            assert isinstance(item.optional_vars, ast.Name)
            name = item.optional_vars.id
            self._emit("def", name, stmt)
            self._lower_block(stmt.body)
            if not self.cur.is_exit:
                self._emit("drop", name, stmt)
            return
        if isinstance(stmt, ast.Try):
            self._lower_try(stmt)
            return
        if isinstance(stmt, ast.Raise):
            if stmt.exc is not None:
                self._lower_expr(stmt.exc)
            if self.handler_stack:
                # Unwinding to a local handler: locals stay live for the handler path.
                self.cur.succs.append(self.handler_stack[-1])
            else:
                self._emit_drops(stmt)
            self.cur.is_exit = True
            return
        if isinstance(stmt, ast.Return):
            if stmt.value is not None:
                self._lower_expr(stmt.value)
                if isinstance(stmt.value, ast.Name) and not self._is_copy_var(stmt.value.id):
                    self._emit("move", stmt.value.id, stmt)
            self._emit_drops(stmt)
            self.cur.is_exit = True
            return
        if isinstance(stmt, ast.Break):
            if self.loop_stack:
                self.cur.succs.append(self.loop_stack[-1][1])
                self.cur = self._new_block()
            return
        if isinstance(stmt, ast.Continue):
            if self.loop_stack:
                self.cur.succs.append(self.loop_stack[-1][0])
                self.cur = self._new_block()
            return
        if isinstance(stmt, ast.Expr):
            self._lower_expr(stmt.value)
            e = stmt.value
            if isinstance(e, ast.Call) and isinstance(e.func, ast.Attribute) \
                    and isinstance(e.func.value, ast.Name) and e.func.value.id == "sys" \
                    and e.func.attr == "exit":
                self._emit_drops(stmt)
                self.cur.is_exit = True
            return
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            target = stmt.targets[0] if isinstance(stmt, ast.Assign) else stmt.target
            if stmt.value is not None:
                self._lower_expr(stmt.value)
            if isinstance(target, ast.Name):
                self._emit("def", target.id, stmt)
            elif isinstance(target, ast.Subscript):
                self._lower_expr(target.slice)
                root = self._root_of(target.value)
                if root:
                    self._emit("mut_use", root, stmt)
            elif isinstance(target, ast.Attribute):
                if isinstance(target.value, ast.Name) and self._is_plain_class_var(target.value.id):
                    self._emit("field_def", f"{target.value.id}.{target.attr}", stmt)
                else:
                    root = self._root_of(target.value)
                    if root:
                        self._emit("mut_use", root, stmt)
            return
        if isinstance(stmt, ast.AugAssign):
            self._lower_expr(stmt.value)
            if isinstance(stmt.target, ast.Name):
                self._emit("use", stmt.target.id, stmt)
                self._emit("def", stmt.target.id, stmt)
            elif isinstance(stmt.target, ast.Subscript):
                self._lower_expr(stmt.target.slice)
                root = self._root_of(stmt.target.value)
                if root:
                    self._emit("mut_use", root, stmt)
            elif isinstance(stmt.target, ast.Attribute):
                root = self._root_of(stmt.target.value)
                if root:
                    self._emit("mut_use", root, stmt)
            return
        if isinstance(stmt, ast.If):
            self._lower_expr(stmt.test)
            head = self.cur
            then_b = self._new_block()
            head.succs.append(then_b.id)
            self.cur = then_b
            self._lower_block(stmt.body)
            then_end = self.cur
            if stmt.orelse:
                else_b = self._new_block()
                head.succs.append(else_b.id)
                self.cur = else_b
                self._lower_block(stmt.orelse)
                else_end = self.cur
                join = self._new_block()
                for end in (then_end, else_end):
                    if not end.is_exit:
                        end.succs.append(join.id)
                self.cur = join
            else:
                join = self._new_block()
                head.succs.append(join.id)
                if not then_end.is_exit:
                    then_end.succs.append(join.id)
                self.cur = join
            return
        if isinstance(stmt, ast.While):
            head = self._new_block()
            self._goto(head)
            self.cur = head
            self._lower_expr(stmt.test)
            body_b = self._new_block()
            exit_b = self._new_block()
            always_true = isinstance(stmt.test, ast.Constant) and stmt.test.value is True
            head.succs.append(body_b.id)
            if not always_true:
                head.succs.append(exit_b.id)
            self.loop_stack.append((head.id, exit_b.id))
            self.cur = body_b
            self._lower_block(stmt.body)
            if not self.cur.is_exit:
                self.cur.succs.append(head.id)
            self.loop_stack.pop()
            self.cur = exit_b
            return
        if isinstance(stmt, ast.For):
            self._lower_expr(stmt.iter)
            borrowed = self._for_borrow_roots(stmt.iter)
            for b in borrowed:
                self._emit("borrow_begin", b, stmt)
                self.loan_stack.append((b, "ref"))
            head = self._new_block()
            self._goto(head)
            self.cur = head
            targets = [stmt.target] if isinstance(stmt.target, ast.Name) else list(stmt.target.elts)
            for t in targets:
                if isinstance(t, ast.Name):
                    self._emit("def", t.id, stmt)
            body_b = self._new_block()
            exit_b = self._new_block()
            head.succs.extend([body_b.id, exit_b.id])
            self.loop_stack.append((head.id, exit_b.id))
            self.cur = body_b
            self._lower_block(stmt.body)
            if not self.cur.is_exit:
                self.cur.succs.append(head.id)
            self.loop_stack.pop()
            for _b in borrowed:
                self.loan_stack.pop()
            self.cur = exit_b
            for b in borrowed:
                self._emit("borrow_end", b, stmt)
            return

    def _lower_try(self, stmt: ast.Try) -> None:
        """Try body: every statement boundary edges to the handler entry (E1 join)."""
        handler_entry = self._new_block()
        self.cur.succs.append(handler_entry.id)
        self.handler_stack.append(handler_entry.id)
        for s in stmt.body:
            if self.cur.is_exit:
                break
            self._lower_stmt(s)
            if not self.cur.is_exit and handler_entry.id not in self.cur.succs:
                self.cur.succs.append(handler_entry.id)
        self.handler_stack.pop()
        body_end = self.cur
        join = self._new_block()
        if not body_end.is_exit:
            body_end.succs.append(join.id)
        for h in stmt.handlers:
            hb = self._new_block()
            handler_entry.succs.append(hb.id)
            self.cur = hb
            if h.name:
                self._emit("def", h.name, h)
            self._lower_block(h.body)
            if not self.cur.is_exit:
                self.cur.succs.append(join.id)
        self.cur = join
        if stmt.finalbody:
            self._lower_block(stmt.finalbody)

    def _is_plain_class_var(self, name: str) -> bool:
        """Whether name is a local/param dataclass instance (not Shared)."""
        from .ptypes import TClass
        facts = self.tc.facts[(self.sig.module, self.sig.name)]
        return isinstance(facts.locals.get(name), TClass)

    def _is_copy_var(self, name: str) -> bool:
        facts = self.tc.facts[(self.sig.module, self.sig.name)]
        t = facts.locals.get(name)
        return t is None or t.is_copy()

    def _root_of(self, e: ast.expr) -> str | None:
        while isinstance(e, (ast.Subscript, ast.Attribute)):
            if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) \
                    and e.value.id == "sys":
                return None
            e = e.value
        if isinstance(e, ast.Name):
            return e.id
        return None

    def _for_borrow_roots(self, iter_expr: ast.expr) -> list[str]:
        """The root variables a for loop Ref-borrows for its body (range: none)."""
        e = iter_expr
        exprs = [e]
        if isinstance(e, ast.Call):
            if isinstance(e.func, ast.Name) and e.func.id == "range":
                return []
            if isinstance(e.func, ast.Name) and e.func.id == "zip":
                exprs = list(e.args)
            elif isinstance(e.func, ast.Name) and e.func.id in ("enumerate", "reversed",
                                                                "sorted") and e.args:
                exprs = [e.args[0]]
            elif isinstance(e.func, ast.Attribute):
                exprs = [e.func.value]
            else:
                return []
        out = []
        for ex in exprs:
            if isinstance(ex, ast.Call):
                continue
            root = self._root_of(ex)
            if root is not None and not self._is_copy_var(root):
                out.append(root)
        return out

    MUT_LIST_METHODS = {"append", "insert", "pop", "extend", "clear", "reverse", "sort"}

    def _lower_expr(self, e: ast.expr) -> None:
        """Emit use/move/mut_use ops for every place read in an expression."""
        facts = self.tc.facts[(self.sig.module, self.sig.name)]
        if isinstance(e, (ast.ListComp, ast.DictComp)):
            gen = e.generators[0]
            self._lower_expr(gen.iter)
            roots = self._for_borrow_roots(gen.iter)
            for r in roots:
                self.loan_stack.append((r, "ref"))
            targets = [gen.target] if isinstance(gen.target, ast.Name) else list(gen.target.elts)
            for t in targets:
                if isinstance(t, ast.Name):
                    self._emit("def", t.id, e)
            for cond in gen.ifs:
                self._lower_expr(cond)
            if isinstance(e, ast.DictComp):
                self._lower_expr(e.key)
                self._lower_expr(e.value)
            else:
                self._lower_expr(e.elt)
            for _r in roots:
                self.loan_stack.pop()
            return
        if isinstance(e, ast.Name):
            if isinstance(e.ctx, ast.Load):
                self._emit("use", e.id, e)
            return
        if isinstance(e, ast.Attribute):
            if isinstance(e.value, ast.Name):
                if e.value.id == "sys":
                    return
                if self._is_plain_class_var(e.value.id):
                    self._emit("use", f"{e.value.id}.{e.attr}", e)
                elif e.value.id in facts.locals:
                    self._emit("use", e.value.id, e)
                return
            self._lower_expr(e.value)
            return
        if isinstance(e, ast.Call):
            if isinstance(e.func, ast.Name) and id(e) in self.tc.move_calls:
                arg = e.args[0]
                if isinstance(arg, ast.Name) and not self._is_copy_var(arg.id):
                    self._emit("move", arg.id, e)
                elif isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name) \
                        and self._is_plain_class_var(arg.value.id):
                    t = self.tc.expr_types.get(id(e))
                    if t is not None and not t.is_copy():
                        self._emit("move", f"{arg.value.id}.{arg.attr}", e)
                    else:
                        self._emit("use", f"{arg.value.id}.{arg.attr}", e)
                else:
                    self._lower_expr(arg)
                return
            if isinstance(e.func, ast.Attribute):
                recv = e.func.value
                from .ptypes import TClass, TDict, TFile, TList, TShared
                if isinstance(recv, ast.Name) and recv.id == "sys":
                    for a in e.args:
                        self._lower_expr(a)
                    return
                rt = self.tc.expr_types.get(id(recv))
                root = self._root_of(recv)
                for a in e.args:
                    self._lower_expr(a)
                is_mut = False
                if isinstance(rt, TShared):
                    is_mut = False
                elif isinstance(rt, TList) and e.func.attr in self.MUT_LIST_METHODS:
                    is_mut = True
                elif isinstance(rt, TDict) and e.func.attr == "pop":
                    is_mut = True
                elif isinstance(rt, TFile):
                    is_mut = True
                elif isinstance(rt, TClass):
                    tgt = self.tc.call_targets.get(id(e))
                    if tgt is not None:
                        msig = self.tc.sigs[tgt]
                        if msig.params and msig.params[0].conv == "mut":
                            is_mut = True
                if root is not None and root in facts.locals:
                    if not self._is_copy_var(root):
                        self._emit("mut_use" if is_mut else "use", root, e)
                    else:
                        self._emit("use", root, e)
                if not isinstance(recv, (ast.Name, ast.Subscript, ast.Attribute)):
                    self._lower_expr(recv)
                elif isinstance(recv, ast.Subscript):
                    self._lower_expr(recv.slice)
                return
            if isinstance(e.func, ast.Name):
                sig = self.tc._resolve_callee(self._mod(), e.func.id)
                tgt = self.tc.call_targets.get(id(e))
                if tgt is not None:
                    sig = self.tc.sigs[tgt]
                for i, a in enumerate(e.args):
                    self._lower_expr(a)
                    if sig is not None and i < len(sig.params) and sig.params[i].conv == "mut":
                        root = self._root_of(a)
                        if root:
                            self._emit("mut_use", root, e)
                for kw in e.keywords:
                    v = kw.value
                    if isinstance(v, ast.Lambda):
                        roots = self._for_borrow_roots(e.args[0]) if e.args else []
                        for r in roots:
                            self.loan_stack.append((r, "ref"))
                        self._emit("def", v.args.args[0].arg, v)
                        self._lower_expr(v.body)
                        for _r in roots:
                            self.loan_stack.pop()
                    else:
                        self._lower_expr(v)
                return
        for child in ast.iter_child_nodes(e):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                self._emit("use", child.id, child)
            elif isinstance(child, ast.expr):
                self._lower_expr(child)
            elif isinstance(child, (ast.FormattedValue,)):
                self._lower_expr(child.value)

    def _mod(self):
        return self.tc.program.modules[self.sig.module]


def lower_program(tc: TypeChecker) -> dict[tuple[str, str], FuncSIR]:
    """Lower every checked (non-template) function to SIR."""
    out = {}
    for key, sig in tc.sigs.items():
        if sig.is_template or key not in tc.facts:
            continue
        out[key] = Lowerer(tc, sig).lower()
    return out
