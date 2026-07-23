"""Ownership analyses over SIR: initialized-places dataflow + lexical loan checks.

Initialized-places is a forward may/must dataflow with a worklist (fixed point),
so moves inside loop bodies are caught at the loop head (docs/spec.md J8). Places are
field-sensitive to one level ("x" and "x.f"): moving x.f leaves x.g usable but
the whole x unusable until x.f is re-assigned. Loans are lexical for-loop
regions recorded on each instruction during lowering.
"""

import ast
from .diagnostics import Reporter, Span
from .sir import FuncSIR

UNINIT = 0
INIT = 1
MOVED = 2
MAYBE = 3   # conflicting states at a join: maybe-moved / maybe-uninit


def _merge(a: int, b: int) -> int:
    if a == b:
        return a
    return MAYBE


def _root(var: str) -> str:
    return var.split(".", 1)[0]


def _apply(kind: str, var: str, state: dict, all_vars: list[str]) -> None:
    """Advance the dataflow state over one instruction."""
    if kind == "def":
        state[var] = INIT
        if "." not in var:
            for v in all_vars:
                if v.startswith(var + "."):
                    state[v] = INIT
    elif kind == "field_def":
        state[var] = INIT
    elif kind in ("move", "drop"):
        state[var] = MOVED


def _eff(state: dict, var: str) -> int:
    """Effective state of a place: an untouched field inherits its root's state."""
    s = state.get(var, UNINIT)
    if "." in var and s == UNINIT:
        return state.get(_root(var), UNINIT)
    return s


def check_function(sir: FuncSIR, rep: Reporter, file: str) -> None:
    """Run both analyses on one function and report diagnostics."""
    all_vars = sorted({i.var for b in sir.blocks for i in b.instrs})
    params = {p.name for p in sir.sig.params}
    entry_state = {}
    for v in all_vars:
        if _root(v) in params:
            entry_state[v] = INIT
        else:
            entry_state[v] = UNINIT

    in_states: dict[int, dict[str, int] | None] = {b.id: None for b in sir.blocks}
    in_states[sir.entry] = dict(entry_state)
    work = [sir.entry]
    while work:
        bid = work.pop()
        state = dict(in_states[bid])  # type: ignore[arg-type]
        block = sir.blocks[bid]
        for instr in block.instrs:
            _apply(instr.kind, instr.var, state, all_vars)
        for succ in block.succs:
            merged = state if in_states[succ] is None else {
                v: _merge(in_states[succ].get(v, UNINIT), state.get(v, UNINIT))  # type: ignore[union-attr]
                for v in all_vars
            }
            if merged != in_states[succ]:
                in_states[succ] = dict(merged)
                work.append(succ)

    move_sites: dict[str, Span] = {}
    for block in sir.blocks:
        for instr in block.instrs:
            if instr.kind == "move" and instr.var not in move_sites:
                move_sites[instr.var] = _span(instr.node, file)

    for block in sir.blocks:
        if in_states[block.id] is None:
            continue
        state = dict(in_states[block.id])  # type: ignore[arg-type]
        for instr in block.instrs:
            _check_instr(instr, state, rep, file, all_vars, move_sites)
            _apply(instr.kind, instr.var, state, all_vars)


def _span(node: ast.AST, file: str) -> Span:
    return Span(file, getattr(node, "lineno", 1), getattr(node, "col_offset", 0),
                getattr(node, "end_col_offset", None))


def _moved_secondary(var: str, move_sites: dict) -> list:
    site = move_sites.get(var)
    return [(site, f"'{var}' moved here")] if site is not None else []


def _check_instr(instr, state: dict, rep: Reporter, file: str,
                 all_vars: list[str], move_sites: dict) -> None:
    var = instr.var
    span = _span(instr.node, file)
    if instr.kind in ("use", "mut_use", "move"):
        cur = _eff(state, var)
        if cur == MOVED:
            rep.error("SE001", "use-after-move",
                      f"use of moved value '{var}'", span,
                      label="value was moved before this use",
                      secondary=_moved_secondary(var, move_sites),
                      help=f"re-initialize '{var}' before this point, or borrow instead "
                           f"of moving")
        elif cur == MAYBE:
            rep.error("SE001", "use-after-move",
                      f"use of possibly-moved value '{var}' — it is moved on some "
                      f"paths reaching this point", span,
                      label="maybe-moved here",
                      secondary=_moved_secondary(var, move_sites),
                      help=f"assign '{var}' on every path (or none) before this use")
        elif "." not in var:
            # Whole-value use: every field must still be present (partial moves).
            for v in all_vars:
                if v.startswith(var + ".") and state.get(v, UNINIT) in (MOVED, MAYBE):
                    fieldname = v.split(".", 1)[1]
                    rep.error("SE001", "use-after-move",
                              f"use of partially moved value '{var}' — field "
                              f"'{fieldname}' was moved out", span,
                              label=f"'{v}' is gone here",
                              secondary=_moved_secondary(v, move_sites),
                              help=f"re-assign '{v}' before using '{var}' as a whole")
                    break
        if "." in var:
            root_state = state.get(_root(var), UNINIT)
            if root_state in (MOVED, MAYBE):
                rep.error("SE001", "use-after-move",
                          f"use of field '{var}' of moved value '{_root(var)}'", span,
                          label="the containing value was moved",
                          secondary=_moved_secondary(_root(var), move_sites))
    if instr.kind == "field_def":
        root_state = state.get(_root(var), UNINIT)
        if root_state in (MOVED, MAYBE):
            rep.error("SE001", "use-after-move",
                      f"cannot assign to field '{var}' of moved value '{_root(var)}'",
                      span, label="the containing value was moved",
                      secondary=_moved_secondary(_root(var), move_sites),
                      help=f"re-initialize '{_root(var)}' as a whole first")
    if instr.kind in ("mut_use", "move", "def", "field_def"):
        for (loan_var, _kind) in instr.loans:
            if loan_var == _root(var):
                if instr.kind == "move":
                    rep.error("SE005", "move-while-borrowed",
                              f"cannot move '{var}' while it is borrowed by the "
                              f"enclosing for loop", span,
                              label="borrowed for the whole loop body")
                else:
                    rep.error("SE004", "conflicting-borrow",
                              f"cannot mutate '{var}' while it is borrowed by the "
                              f"enclosing for loop", span,
                              label="the loop holds a Ref borrow of it")


def check_program(sirs: dict, rep: Reporter, files: dict[str, str]) -> None:
    """Run ownership analyses on every function in the program."""
    for (mod, _fname), sir in sirs.items():
        check_function(sir, rep, files[mod])
