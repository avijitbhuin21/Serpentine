"""Ownership analyses over SIR: initialized-places dataflow + lexical loan checks.

Initialized-places is a forward may/must dataflow with a worklist (fixed point),
so moves inside loop bodies are caught at the loop head (SPEC.md J8). Loans are
lexical for-loop regions recorded on each instruction during lowering.
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


def check_function(sir: FuncSIR, rep: Reporter, file: str) -> None:
    """Run both analyses on one function and report diagnostics."""
    all_vars = sorted({i.var for b in sir.blocks for i in b.instrs})
    params = {p.name for p in sir.sig.params}
    entry_state = {v: (INIT if v in params else UNINIT) for v in all_vars}

    in_states: dict[int, dict[str, int] | None] = {b.id: None for b in sir.blocks}
    in_states[sir.entry] = dict(entry_state)
    work = [sir.entry]
    while work:
        bid = work.pop()
        state = dict(in_states[bid])  # type: ignore[arg-type]
        block = sir.blocks[bid]
        for instr in block.instrs:
            state[instr.var] = _transfer(instr.kind, state.get(instr.var, UNINIT))
        for succ in block.succs:
            merged = state if in_states[succ] is None else {
                v: _merge(in_states[succ].get(v, UNINIT), state.get(v, UNINIT))  # type: ignore[union-attr]
                for v in all_vars
            }
            if merged != in_states[succ]:
                in_states[succ] = dict(merged)
                work.append(succ)

    for block in sir.blocks:
        if in_states[block.id] is None:
            continue
        state = dict(in_states[block.id])  # type: ignore[arg-type]
        for instr in block.instrs:
            _check_instr(instr, state, rep, file)
            state[instr.var] = _transfer(instr.kind, state.get(instr.var, UNINIT))


def _transfer(kind: str, cur: int) -> int:
    if kind == "def":
        return INIT
    if kind == "move":
        return MOVED
    if kind == "drop":
        return MOVED
    return cur


def _span(node: ast.AST, file: str) -> Span:
    return Span(file, getattr(node, "lineno", 1), getattr(node, "col_offset", 0),
                getattr(node, "end_col_offset", None))


def _check_instr(instr, state: dict[str, int], rep: Reporter, file: str) -> None:
    cur = state.get(instr.var, UNINIT)
    span = _span(instr.node, file)
    if instr.kind in ("use", "mut_use", "move"):
        if cur == MOVED:
            rep.error("SE001", "use-after-move",
                      f"use of moved value '{instr.var}'", span,
                      label="value was moved before this use")
        elif cur == MAYBE:
            rep.error("SE001", "use-after-move",
                      f"use of possibly-moved value '{instr.var}' — it is moved on some "
                      f"paths reaching this point", span,
                      label="maybe-moved here")
    if instr.kind in ("mut_use", "move", "def"):
        for (var, _kind) in instr.loans:
            if var == instr.var:
                if instr.kind == "move":
                    rep.error("SE005", "move-while-borrowed",
                              f"cannot move '{instr.var}' while it is borrowed by the "
                              f"enclosing for loop", span,
                              label="borrowed for the whole loop body")
                else:
                    rep.error("SE004", "conflicting-borrow",
                              f"cannot mutate '{instr.var}' while it is borrowed by the "
                              f"enclosing for loop", span,
                              label="the loop holds a Ref borrow of it")


def check_program(sirs: dict, rep: Reporter, files: dict[str, str]) -> None:
    """Run ownership analyses on every function in the program."""
    for (mod, _fname), sir in sirs.items():
        check_function(sir, rep, files[mod])
