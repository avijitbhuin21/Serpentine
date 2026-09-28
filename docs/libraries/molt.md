# Molt (`serp-molt`) — roadmap

> Per-library roadmap. One-line status lives in [../libraries.md](../libraries.md); this
> file is the working checklist. One goal: **✅ drop-in `pydantic` v2, not ≈**.
> Numbered blockers at the bottom — every `[L]` item names the blocker that gates it.
>
> Markers: `[x]` done · `[ ]` open · **[P]** library-only work · **[R]** needs runtime
> (`prelude.rs`/`rt.rs`) work · **[L]** language-blocked, see blockers.
>
> **LB numbers are local to this file.** [venom.md](venom.md) owns its own `LB*` list;
> where a blocker is shared it is cited as `venom.md LB7`.
>
> **"Drop-in" means** API-identical under a `serp_molt` import root
> (`from serp_molt import BaseModel, Field, ValidationError`), the same convention every
> other drop-in in the tracker follows — porting a pydantic app is an import rewrite, not
> a code rewrite.

## Where we are (2026-07-27) — SHIPPED (T1 + T2 + T3 schema + validators/config/mutation + serializers)

`libs/serp-molt/` ships **0.7.0** as a drop-in: `from serp_molt import BaseModel, Field,
ValidationError, field_validator, model_validator, ConfigDict, AfterValidator,
BeforeValidator, field_serializer, model_serializer, computed_field, Json, SkipValidation,
SecretStr, Base64Bytes, PydanticCustomError, PositiveInt, HttpUrl, EmailStr`. **Every live language blocker is
cleared** — LB1/LB2/LB3/LB4/LB8/LB13/LB14
(D16 — build-time field-table intrinsics `fields_of`/`fields_json`/`fields_build`/`fields_set`,
`@classmethod` with a build-time `cls` binding, `Annotated[T, ...]` + a call in field-default
position recorded as `field_meta`; D18 — class-body registration decorators, the hook
intrinsics `hooks_json`/`run_hook`/`run_hook_self`, and `model_config`; D19 — `**mapping`
unpacking, `__setattr__`/frozen classes, and function references in build-time metadata) plus
LB7 sets (D20), LB6 enums (D21), LB10 `__init__` bodies (D22), LB9 generic bases (D23 + D25),
LB5 general unions (D24), **D27 serializer/computed-field/info hooks** and **D28 module-level
type aliases**. Only LB11 (reflection) and LB12 (`Decimal`) remain, both permanent
divergences. All twelve library tests are byte-identical across CPython, Backend A and
Backend B.

**Landed:** the whole T1 surface including `User(**data)`, T2's `Field()` constraints +
aliases + nested/container models + `@field_validator`/`@model_validator` (`before`/`after`,
inherited through flattening) + `Annotated[T, AfterValidator(f)/BeforeValidator(f)]`, T3's
`model_json_schema()` with `$defs`/`$ref`, the `model_config` subset (`extra`,
`populate_by_name`, `str_*`, `frozen`, `validate_assignment`, `alias_generator`), T4's
enum / `set[T]` / general-union field types plus generic models, and — new in 0.5.0 —
`@field_serializer`/`@model_serializer`/`@computed_field` on the dump path, two-argument
(`ValidationInfo`) validators, the constrained-alias families (`PositiveInt` … `HttpUrl`,
`EmailStr`), `Json()`/`SkipValidation()` markers, `PydanticCustomError`, root models
(a single `root` field) and `model_fields_set()`. **New in 0.6.0:** `datetime`/`date`/
`timedelta`/`UUID` field types, self-referential models, the `Strict*` families,
`Field(exclude=)`/`json_schema_extra=`, `model_json_schema(by_alias=)`, `info["context"]`
and per-member union errors.
**Not landed:** `wrap`/`plain` validators (`venom.md` LB3) and discriminated unions (needs a
tagged union in the language). `conint()`/`constr()` and smart-union ordering are **closed as
divergences**, not TODOs — see §B.
**New in 0.7.0:** `SecretStr` (masked in `str()`, every dump and `model_dump_json`;
`get_secret_value()`; `format: password` + `writeOnly` in the schema) and `Base64Bytes`
(`Annotated[bytes, Base64()]` — base64 text in, `bytes` on the model, base64 text out,
`base64_decode` errors).

**Targets.** **T1** = models with plain annotated fields: construct, `model_validate`,
`model_dump`, `model_dump_json`, `ValidationError`. **T2** = `Field()` constraints,
validators, nested models. **T3** = JSON Schema + Venom body models/`response_model`.
**T4** = the long tail (unions, generics, config surface, `TypeAdapter`).

## Why the remaining boxes are open (re-audited 2026-07-27, after D31–D38)

The checklist matches the code. The open items split three ways:

**A. Language-blocked (13 items marked `[L]`).** Gated on LB11 reflection, LB12 `Decimal`, or
`venom.md LB2`/`LB3`. **LB11's five items and LB12's are permanent divergences, not TODOs**
(`create_model`, `TypeAdapter` over runtime types, `arbitrary_types_allowed`,
`extra="allow"` attribute access, `__get_pydantic_core_schema__`, `Decimal`). Every *live*
language blocker (LB1–LB10, LB13, LB14) is cleared.

**B. Feasible today — the remaining backlog, roughly in cost order:**

1. ~~`SecretStr`, `Base64Bytes`~~ — **DONE 2026-08-29 (0.7.0).** `SecretStr` is a molt class
   recognized *structurally* by `_fmt_of` (`class == "SecretStr"`, one field named `_v`), exactly
   like `UUID`/`date`: it validates from plain text, `get_secret_value()` returns the secret,
   `str()` and every dump emit `**********`, and the schema is
   `{"type":"string","format":"password","writeOnly":true}`. **No compiler change was needed** —
   the known-class mechanism is pure library convention. `Base64Bytes` is
   `Annotated[bytes, Base64()]`: a `_b64_markers` pass decodes the base64 text into `bytes`
   before validation (reporting `base64_decode` on bad input) and `_out_field` re-encodes on the
   way out. Adds a `serp-base64` dependency.
   Tests: `tests/test_secretstr.py`, `tests/test_base64bytes.py`.
2. ~~`conint()`/`constr()`~~ — **IMPLEMENTED 2026-08-29.** A call in type-alias position now
   desugars in the frontend (`_expand_alias_factory`) to the `Annotated[base, Field(...)]`
   form the rest of the pipeline already understands, so `Age = conint(gt=0)`,
   `Name = constr(min_length=2)`, `Tags = conlist(str, min_length=1)` all work — plus
   `confloat`/`conbytes`. The shim provides matching runtime functions so the same source
   dual-runs. Test: `tests/test_confactories.py`.
3. ~~Smart-union coercion order~~ — **CLOSED as a non-issue.** D24 requires union members to
   differ in runtime kind, so there is exactly one candidate member per input kind: molt's
   "first member whose runtime kind matches" *is* pydantic's smart-mode strict pass. The only
   remaining difference is `int`→`float` widening when no `int` member exists, which matches
   pydantic. Per-member errors already shipped (D37).
4. ~~Discriminated unions~~ — **IMPLEMENTED 2026-08-29.** A union of two or more models is
   accepted when it carries a **discriminator**: a field shared by every member whose
   *constant default* differs in each (`pet_type: str = "cat"` / `= "dog"`). Serpentine has
   no `Literal`, so the default is the tag. `TypeChecker.union_discriminator` derives it,
   `fieldsyn` emits tag dispatch in the build direction, and molt (`_disc_pick`) and the shim
   (`_disc_member`) select the member on the validation path. Without a derivable
   discriminator the old `SE201` still fires, now with a message that says how to add one.
   Test: `tests/test_discriminated.py`.
5. `mode="wrap"`/`"plain"` validators — need the inner validator as a callable value
   (`venom.md LB3`). Still language-blocked — the only remaining Molt item.

**Every item that could be done without a language change is now done.** What is left is
LB11/LB12 (closed by decision), `venom.md` LB2/LB3, and tagged unions.

**C. Sequenced behind another library (3 items).** The Venom integration phase (M9) waits on
`venom.md LB2`; `BaseSettings` is a separate upstream distribution and out of scope for Molt.

## Why this is not purely engineering

Pydantic **is** reflection. `BaseModel`'s metaclass reads `__annotations__` at class
creation and compiles a validator/serializer; `model_validate` and `model_dump` are
inherited methods that enumerate the *subclass's* fields at runtime. Serpentine lists
runtime reflection, metaclasses and dynamic attributes as permanently out of scope
([../features.md](../features.md)), and inheritance is check-time textual flattening — a
`model_dump()` body copied from `BaseModel` into `User` has no `__annotations__`, no
`getattr`/`setattr`, and no knowledge of `User`'s fields. **No amount of library effort can
write the two functions that are pydantic.**

The compiler, however, already holds the exact field table: `ClassInfo.fields` /
`field_order` / `field_defaults` (`compiler/src/serpentine_lang/typecheck.py:66`). LB1 is
about exposing that table to generated code. Precedent is strong and already shipped:
`@dataclass` `__init__`/`__eq__` synthesis, the `__repr__` backend override, and `serp
test`'s build-time `TestCase` discovery are all "compiler knows the fields, compiler
generates the code".

**Decided design (2026-07-26): generic intrinsics, not a pydantic-specific derive.** The
compiler stays pydantic-agnostic and exposes field-table access that *any* library can use;
Molt is then library engineering on top. This composes unusually well with flattening: a
single line in `BaseModel`

```python
def model_dump(self: Ref[BaseModel]) -> dict[str, PyVal]:
    return fields_of(self)
```

is deep-copied into every subclass with `self` retargeted `BaseModel` → `User`, so
`fields_of(self)` expands against `User`'s field table at that call site. One library line,
monomorphized per model, zero per-model codegen.

---

# Phase M0 — the language gate — CLEARED (D16)

- [x] **[L]** `fields_of(obj) -> dict[str, PyVal]` — read the field table of a class-typed
      value into a PyVal dict, recursing into class-typed fields. **LB1 done.**
- [x] **[L]** The construction direction — `fields_build(cls, pv)` builds an instance from a
      `dict[str, PyVal]` with per-field type checks; **error accumulation lives in the
      library** (`model_validate_errors`), the intrinsic itself raises on the first
      structural mismatch.
- [x] **[L]** Build-time field metadata for generated code — `fields_json(cls)` returns the
      whole table (name, type tree, `has_default`, folded default, `Field()` meta) as a JSON
      string, parsed with `serp_json.loads`.
- [x] **[L]** Decided: the intrinsics are **general user-callable builtins** over any
      `@dataclass`-shaped class (D16), not library-private.
- [x] **[P]** Accept corpus for the intrinsics: `tests/accept/076_fields_intrinsics.py`,
      `077_classmethod_models/` (nested, defaulted, `Optional`, `list[Model]`,
      `dict[str, Model]`, cross-module inherited classmethods).

# Phase M1 — core model surface (T1) — SHIPPED

- [x] **[P]** `class User(BaseModel)` — field-less base + flattening already work
      (accept test `075_cross_module_inherit` covers cross-module bases).
- [x] **[P]** `User(id=1, name="a")` keyword construction — kwargs shipped; `@dataclass`
      already generates `__init__`/`__repr__`/`__eq__`, so value equality and repr come free.
- [x] **[L]** `User(**data)` dict unpacking — LB8 cleared: a dict **literal** `**` expands to
      keyword arguments at check time, and `Model(**mapping)` lowers to the `fields_build`
      helper (strict field types, no coercion — use `model_validate` for lax input).
- [x] **[L]** `User.model_validate(obj)` — classmethod entry point (LB1 + LB3).
- [x] **[L]** `User.model_validate_json(s)` — `serp_json.loads` into PyVal, then LB1.
- [x] **[L]** `m.model_dump()` → `dict[str, PyVal]`, with `by_alias` / `exclude_none`.
- [x] **[L]** `m.model_dump_json()` — dump + a compact-separator serializer.
- [x] **[L]** `m.model_copy(update=...)`, `User.model_construct(...)` (skip validation).
- [x] **[L]** `User.model_fields` — the field table as data (a **classmethod call**,
      `User.model_fields()`, not a class attribute: a documented divergence).
- [x] **[P]** `m.model_fields_set` — shipped as a **classmethod over the input**,
      `User.model_fields_set(obj)` returning the field names the input supplied explicitly
      (a divergence: pydantic's is per-instance state, which a model dataclass cannot carry).
- [x] **[P]** `__str__` parity — pydantic's `str(m)` is `id=1 name='a'`, not the repr.

# Phase M2 — types & lax coercion (T1) — SHIPPED (except the blocked types)

Pydantic's default (lax) mode coerces; strict mode does not. Both need a per-field decision
table, which is pure library work **once LB1 lands**.

- [x] **[P]** `int` / `float` / `bool` / `str` / `bytes` fields + the lax table:
      `str`→`int`/`float`, `int`→`float`, `"true"/"yes"/"1"`→`bool`, `0`/`1`→`bool`.
- [x] **[P]** Reject-with-error cases: `float`→`int` with a fractional part, out-of-range,
      `None` for a non-`Optional` field.
- [x] **[P]** `Optional[T]` / `T | None` fields — narrowing already exists.
- [x] **[P]** `list[T]`, `dict[str, T]`, `tuple[...]` fields (element-wise validation with
      indexed error `loc`s).
- [x] **[P]** `datetime` / `date` / `timedelta` from ISO strings (D31) — parsed via
      `datetime.fromisoformat`/`date.fromisoformat`, dumped back to ISO text (`timedelta`
      validates from a number of seconds and dumps as one); **no tz-aware values** (divergence).
- [x] **[P]** `UUID` fields (D31) — `UUID(str)` parsing from serp-uuid (dashed, plain-hex,
      braced and `urn:uuid:` spellings); dumped as the canonical dashed form.
- [x] **[L]** `Enum` / `IntEnum` fields — LB6 cleared (D21): an `{"k":"enum"}` field-table node
      carrying the member names/values; input is the member **value** (an `Enum` *instance* is
      not a `PyVal`, so `use_enum_values` is moot — dumps always emit `.value`).
- [x] **[L]** `set[T]` / `frozenset[T]` fields — LB7 cleared (D20): validated from a JSON list,
      deduped in input order, dumped back as a list, `uniqueItems: true` in the schema.
- [ ] **[L]** `Decimal` fields, `max_digits`, `decimal_places`, ints beyond 64 bits.
      Needs **LB12** — likely never.

# Phase M3 — `Field()` and `Annotated` constraints (T2) — SHIPPED (core)

- [x] **[L]** `x: int = Field(default=0, gt=0)` — LB4 cleared; the call's folded arguments
      become `ClassInfo.field_meta` (positional first arg = the default).
- [x] **[L]** `x: Annotated[int, Field(gt=0)]` — `Annotated` is parsed and its extras kept.
- [x] **[L]** `default_factory=list` / `dict` — per-instance empty containers.
      (Arbitrary factories are still out: defaults must fold at build time.)
- [x] **[P]** Numeric constraints `gt`/`ge`/`lt`/`le`/`multiple_of`.
- [x] **[P]** String constraints `min_length`/`max_length`/`pattern` (via `serp-re`).
- [x] **[P]** Collection constraints `min_length`/`max_length` on lists/dicts.
- [x] **[P]** Schema-only metadata: `title`, `description`, `json_schema_extra` (merged into
      the property schema) and `exclude` (honoured by `model_dump`, D34/D35). `examples` and
      `repr` are accepted as metadata but not honoured yet.
- [x] **[L]** `alias` / `validation_alias` / `serialization_alias` — read on validation,
      written back with `model_dump(by_alias=True)`. (`populate_by_name` needs LB2 config.)
- [x] **[P]** Constrained type aliases: `PositiveInt`, `NonNegativeInt`, `NegativeInt`,
      `NonPositiveInt` and the four `*Float` counterparts — shipped as `Annotated` aliases
      (D28). `StrictInt`/`StrictFloat`/`StrictBool`/`StrictStr`/`StrictBytes` shipped as
      `Annotated[T, Field(strict=True)]` (D33). `conint()`/`constr()` are still open (a call
      cannot fold to an alias).
- [x] **[P]** `AnyUrl` / `AnyHttpUrl` / `HttpUrl` — shipped as `Annotated[str, Field(pattern=...)]`
      aliases (a **divergence**: they validate by regex and stay `str`, they are not URL
      objects). `SecretStr` / `Base64Bytes` are class-typed fields and remain open.
- [x] **[P]** `EmailStr` — **decided**: shipped as a divergent built-in regex alias
      (`^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$`), not `email-validator` semantics.

# Phase M4 — validators & serializers (T2) — SHIPPED (before/after)

- [x] **[L]** `@field_validator("x", mode="before"|"after")` — LB2 cleared (D18): the
      frontend records the decoration against the class, `hooks_json(cls)` exposes the table
      and `run_hook(cls, name, v)` dispatches to the lifted classmethod.
- [x] **[L]** `@model_validator(mode="before"|"after")` — `before` rewrites the raw input
      mapping, `after` runs on the built instance via `run_hook_self(instance, name)`.
- [ ] **[L]** `mode="plain"` / `mode="wrap"` validators (the handler is a closure over the
      inner validator). Needs `venom.md LB3`.
- [x] **[P]** `@computed_field` + `@property` in `model_dump` — shipped (D27): a `computed`
      hook kind dispatched with `run_hook_get`, appended to the dump in declaration order.
      `model_json_schema("serialization")` also emits them as `readOnly` properties (D29).
- [x] **[P]** `@field_serializer` / `@model_serializer` — shipped (D27). A field serializer
      rewrites its field on the dump path (`run_hook_val`); a model serializer replaces the
      whole dumped value, so `model_dump()` returns `PyVal` rather than `dict[str, PyVal]`
      (a divergence forced by serializers that return a list).
- [x] **[L]** `Annotated[int, AfterValidator(f)]` / `BeforeValidator` — LB14 cleared: a bare
      function name in metadata folds to a symbol reference (`{"__fn__": name}`) that the
      synthesized `run_hook` dispatcher calls. `WrapValidator` is still open (it needs the
      inner validator as a callable argument).
- [x] **[P]** `ValidationInfo` (`info.data`, `info.field_name`) passed to validators — shipped
      (D27): a two-argument validator is dispatched through `run_hook_info` with `info` as a
      **`PyVal` mapping** (`info["data"]` / `info["field_name"]`), not an object.
- [x] **[P]** `info.context` — shipped (D36) as a `PyVal` divergence: `model_validate(obj,
      context=...)` threads the value through to `info["context"]` in every validator.
- [x] **[P]** `ValueError` raised inside a validator becomes a `value_error`
      `ValidationError` entry, accumulated with the field errors.
- [x] **[P]** `__post_init__` runs after every construction and can raise, so whole-model
      validation on the constructor path works today (superseded by `@model_validator`).

# Phase M5 — `ValidationError` parity (T1) — SHIPPED

Pydantic's error object is a big part of why people use it; a divergent error shape breaks
real ports.

- [x] **[P]** `ValidationError` (a `ValueError` subclass) raised from every validation entry
      point, with pydantic's multi-line message as the payload.
- [x] **[P]** Errors as `{type, loc, msg, input}` dicts — reachable via
      `Model.model_validate_errors(obj)` (a **divergence**: `e.errors()` needs typed payload
      on the exception object, which the language has no shape for — LB11-adjacent).
- [x] **[P]** `Model.model_validate_json_errors(text)` — the same list from a JSON string,
      reporting a malformed document as a single `json_invalid` error instead of raising.
      This is what a web framework needs to build FastAPI's `{"detail": [...]}` 422
      envelope without an exception round-trip (see `serp-venom`'s `test_molt_body.py`).
- [x] **[P]** `loc` as a `list[PyVal]` path (`["items", 0, "name"]`) — documented divergence
      from pydantic's tuple.
- [x] **[P]** Error **accumulation** — every field failure is collected, not just the first.
- [x] **[P]** `str(e)` multi-line format parity, including the `N validation errors for X`
      header and the `[type=…, input_value=…, input_type=…]` tail.
- [x] **[P]** `type` string parity (`int_parsing`, `greater_than`, `string_too_short`,
      `missing`, `multiple_of`, `string_pattern_mismatch`, …).
- [x] **[P]** The `https://errors.pydantic.dev/...` URL line is **dropped** (decided).
- [x] **[P]** `PydanticCustomError` — shipped as a `ValueError` subclass raised from a
      validator; its message is split on the first `": "` into the error entry's `type` and
      `msg` (a divergence: exceptions carry a single string, not a typed payload).

# Phase M6 — nested, recursive & container models (T2) — SHIPPED

- [x] **[L]** Nested models (`class Order: user: User`) — validated and dumped recursively
      (LB1 recurses into class-typed fields).
- [x] **[P]** `list[Model]` / `dict[str, Model]` fields with indexed error paths.
- [x] **[P]** Self-referential models via `from __future__ import annotations` (D32) — the
      field table emits a `{"cycle": true}` stub for a back-reference; molt rebuilds a
      spec table from the root and resolves stubs on the fly, and the JSON Schema emits a
      `$ref`. Depth is bounded by the input, not the type.
- [ ] **[P]** Cyclic models — need `Shared`/`Weak`; cycles leak (D3). Document.

# Phase M7 — `model_config` (T4) — SHIPPED (core subset)

- [x] **[L]** `model_config = ConfigDict(...)` — LB2 cleared (D18): a class-body assignment
      whose value is a foldable `ConfigDict(...)`/`dict(...)` call is recorded in
      `ClassInfo.config` and surfaces in `fields_json`'s `"config"` key; inherited.
- [x] **[P]** `extra="ignore"` (default) and `extra="forbid"`.
- [ ] **[L]** `extra="allow"` + `__pydantic_extra__` attribute access. Needs **LB11** —
      dynamic attributes are permanently out of scope. A `PyVal` bag is the divergence.
- [x] **[P]** `str_strip_whitespace`, `str_to_lower`, `str_to_upper`, `str_min_length`,
      `str_max_length`, plus `populate_by_name`.
- [x] **[L]** `validate_assignment` and `frozen=True` — LB13 cleared: `BaseModel.__setattr__`
      intercepts every field write and re-validates (or raises `frozen_instance`).
      `@dataclass(frozen=True)` is also accepted by the compiler for plain classes.
      Hashable models are still out (no `__hash__`).
- [x] **[L]** `alias_generator` — LB14 cleared; applied to the top-level fields of a model in
      both directions (input keys and `by_alias` dumps). Explicit `alias`/`serialization_alias`
      still win, and nested models use their own config.
- [ ] **[L]** `from_attributes=True` (ORM mode). Needs LB1 in the *reading* direction over
      an arbitrary source object — only meaningful for another dataclass.
- [ ] **[L]** `arbitrary_types_allowed`, `json_encoders`. Needs **LB11**; expect divergence.

# Phase M8 — advanced typing (T4)

- [x] **[L]** General unions `int | str` — LB5 cleared (D24): a `{"k":"union","members":[...]}`
      field-table node, validated by runtime kind (first member whose kind matches, `int`
      widening to a `float` member when no `int` member exists).
- [ ] **[L]** Discriminated unions (`Field(discriminator=...)`, `Tag`/`Discriminator`).
      Needs LB5 + LB4. A union of two *model* members is rejected at compile time with
      `SE201` (D30): both arrive as JSON objects, so runtime-kind dispatch cannot pick one.
- [ ] **[P]** Smart-union coercion order — LB5 is cleared; molt validates by runtime kind
      rather than pydantic's smart/left-to-right two-pass order. Per-member errors **are**
      reported now (D37: each member is re-run in isolation and its errors collected under
      `loc + [member tag]`). **Divergence narrowed; ordering still differs.**
- [x] **[L]** Generic models `class Page(BaseModel, Generic[T])` — LB9 cleared (D23 + D25):
      `model_validate` / `model_dump` / `model_json_schema` work on an instantiation
      (`Page[int].model_validate(d)`); a bare `Page.model_validate(...)` is SE214.
- [x] **[P]** Root models — shipped as a **shape convention**: a model whose only field is
      named `root` accepts a bare value (wrapped to `{"root": v}`) and dumps unwrapped.
      `class Ids(RootModel[list[int]])` itself is not available — inheriting *from* a generic
      class is still SE201 — so the spelling is `class Ids(BaseModel): root: list[int]`.
- [x] **[P]** `Json[T]` — shipped as `Annotated[T, Json()]`: the field's raw string is
      JSON-parsed before type validation, with a `json_invalid` error otherwise.
- [x] **[P]** `SkipValidation` — shipped as `Annotated[T, SkipValidation()]`: type checks,
      `str_*` config and `Field()` constraints are skipped for that field. **Divergence:** the
      value must still match the field's declared shape at construction (`fields_build` is
      typed), so it cannot smuggle an arbitrary value in. `InstanceOf` is meaningless without
      subtyping and stays out.

# Phase M9 — JSON Schema + Venom integration (T3) — schema SHIPPED

This is the phase that pays for Molt beyond Molt.

- [x] **[L]** `User.model_json_schema()` — built from the field table, with `type`/`title`/
      `default`/`required` and the `Field()` constraint keywords (`exclusiveMinimum`,
      `minLength`, `multipleOf`, `pattern`, …).
- [x] **[P]** `$defs`/`$ref` for nested and self-referential models; `anyOf` for `T | None`;
      `format: date`/`date-time`/`uuid` for temporal and UUID fields;
      `mode="validation"|"serialization"` (D29 — serialization mode adds `@computed_field`
      properties); `by_alias=` (D35, defaults to `True` as upstream).
- [ ] **[L]** Venom request-body models (`def create(item: Item)`). Needs `venom.md LB2`.
- [ ] **[L]** Venom `response_model=` / returning a model from a handler. Same gates.
- [ ] **[L]** Venom OpenAPI `/docs` — Venom B8; needs `venom.md LB2` + this phase.
- [ ] **[P]** Venom `Query()`/`Path()`/`Body()` declaration surface once the above lands.
- [ ] **[L]** `__get_pydantic_core_schema__` / `WithJsonSchema` custom hooks. Needs LB11 —
      out of scope.

# Phase M10 — beyond models (T4)

- [ ] **[L]** `TypeAdapter(list[int])` — types as runtime values. Needs **LB11**; the closest
      reachable thing is a build-time generic `validate_as[T]`. Design needed.
- [ ] **[L]** `@validate_call` on functions. Needs `venom.md LB2` (signature introspection);
      D13 decorators cannot change behaviour, only register.
- [ ] **[L]** `pydantic.dataclasses.dataclass`. Needs LB1 + LB2.
- [ ] **[L]** `create_model()` — runtime class creation. **Never**; LB11.
- [x] **[P]** v1 compat aliases shipped: `.dict()`, `.json()`, `parse_obj()`, `parse_raw()`,
      `schema()`.
- [ ] **[P]** `BaseSettings` — a separate `pydantic-settings` distribution upstream; if
      wanted, ship `serp-molt-settings` over `serp-os` env vars. Out of scope for Molt.

---

# Permanent divergences

These are not TODOs; they are what the README must say up front.

| pydantic | Serpentine | Why |
|---|---|---|
| `e.errors()` on the exception | `Model.model_validate_errors(obj)` | exceptions carry only a message string |
| `loc` tuple | `list[PyVal]` | no heterogeneous tuples in `PyVal` |
| `User.model_fields` attribute | `User.model_fields()` classmethod | no class-level data attributes |
| `m.model_fields_set` attribute | `User.model_fields_set(obj)` classmethod | no per-instance non-field state |
| `RootModel[T]` base class | a model with a single `root` field | cannot inherit from a generic class |
| `ValidationInfo` object | a `PyVal` mapping (`info["data"]`) | no runtime object for a build-time shape |
| `AnyUrl`/`HttpUrl`/`EmailStr` objects | regex-constrained `str` aliases | no URL/email object types |
| `SkipValidation` accepts anything | value must still match the declared field shape | `fields_build` is typed |
| `model_dump()` → `dict` | `PyVal` (a `@model_serializer` may return a list) | one return type per function |
| `str(e)` error-URL line | omitted | version-coupled noise |
| arbitrary-precision `int` | int64, overflow traps | language, documented project-wide |
| `Decimal`, `complex` | absent | LB12 |
| `conint()` returns a type object | desugared at build time to `Annotated[int, Field(...)]` | types are build-time descriptions |
| `Literal["cat"]` discriminator | the discriminator field's **constant default** | no `Literal` type |
| `SecretStr` in `model_dump()` | the masked text `**********` | `model_dump` returns `PyVal`, not live objects |
| `create_model`, `arbitrary_types_allowed`, `__get_pydantic_core_schema__` | absent | LB11 — reflection is out of scope by design |
| `extra="allow"` attribute access | `PyVal` bag at best | LB11 dynamic attributes |
| tz-aware `datetime` | naive only | `serp-datetime` has no tz |
| `InstanceOf`, subtype polymorphism | absent | inheritance is flattening (D15) |
| private attrs `_x` / `PrivateAttr` | absent | no name-mangled non-field class state |
| `model_rebuild()` for forward refs | no-op | resolved at build time |
| `model_config` `frozen` vs `@dataclass(frozen=True)` | both exist, checked at different times | library config is runtime; the decorator is check-time |

# Dependencies

Library and runtime prerequisites that are **not** language blockers:

| Needed by | Depends on | Status |
|---|---|---|
| M1 JSON entry/exit | `serp-json` (PyVal `loads`/`dumps`) | shipped; wants compact separators + a small-dict fast path (see venom.md A4) |
| M2 date/time fields | `serp-datetime` ISO-8601 **parsing** | shipped: `date.fromisoformat` / `datetime.fromisoformat` (naive only) |
| M2 UUID fields | `serp-uuid` `UUID(str)` parsing | shipped: dashed / plain-hex / braced / `urn:uuid:` |
| M3 `pattern=` | `serp-re` | shipped 0.2.0 |
| M3 `AnyUrl`/`HttpUrl` | `serp-url` | shipped |
| M3 `Base64Bytes` | `serp-base64` | shipped |
| M9 Venom integration | `venom.md` LB2 + B2 | not started |
| M10 `BaseSettings` (if ever) | `serp-os` env vars | shipped |

# Language blockers

Each says what must be true in the **language**, not in Molt. LB numbering is local to this
file. Nothing here is Molt-specific — every one unblocks other libraries too.

- **LB1 — build-time field-table intrinsics.** ✅ **CLEARED (D16, 2026-07-26.)** Three
  builtins, lowered to ordinary Serpentine functions synthesized from `ClassInfo`
  (`compiler/src/serpentine_lang/fieldsyn.py`) so both backends compile them like user code:
  `fields_of(obj) -> dict[str, PyVal]` (dump, recursing into class-typed fields),
  `fields_json(cls_or_obj) -> str` (the field table — names, type trees, defaults, `Field()`
  metadata — as JSON), and `fields_build(cls_or_obj, pv) -> Cls` (construct with per-field
  kind checks). Error *accumulation* lives in the library, not the intrinsic. The dump
  direction composes with flattening exactly as designed: `self` retargeting monomorphizes
  `fields_of(self)` per subclass. **D17 resolved by LB3**: `cls` is a build-time binding, and
  statics/classmethods are now inherited. *Also unblocks:* ORM row→object mapping in
  `serp-sqlite`, Venom `response_model`, any serializer library, `serp-scales`
  DataFrame↔record conversion.

- **LB2 — class-body registration decorators + non-annotated class-body statements.**
  ✅ **CLEARED (D18, 2026-07-26.)** Methods carrying `@field_validator(...)` /
  `@model_validator(...)` keep their body but lose the decorator: the frontend records
  `{kind, mode, fields, method}` against the class (`mod.class_hooks`), the checker merges it
  into `ClassInfo.hooks` (inherited through flattening, minus redefined methods), and three
  intrinsics expose it to library code — `hooks_json(cls)` (the hook table as JSON),
  `run_hook(cls, name, v)` (dispatch to a lifted validator classmethod) and
  `run_hook_self(instance, name)` (dispatch to an after-model method). Class-body
  assignments whose value folds (`model_config = ConfigDict(...)`) land in `ClassInfo.config`
  and ride along in `fields_json`'s `"config"` key. Bad shapes are rejected at build time
  (`tests/reject/r064`–`r066`). *Still open:* `wrap`/`plain` validator modes and serializer
  hooks (same mechanism, dump-path work). *Also unblocks:* `serp-test` fixtures, ORM-style
  declarative libraries.

- **LB3 — `classmethod`.** ✅ **CLEARED (D16.)** `@classmethod` is supported: methods are
  lifted to module-level functions with a build-time `cls` binding (the class the call
  resolves to), so `cls(...)` constructs and `cls.other()` dispatches; `Self` is the return
  annotation. Both classmethods and staticmethods are now **inherited through flattening**.
  Types are still not values — `type[T]` does not exist.

- **LB4 — non-constant field defaults + `Annotated`.** ✅ **CLEARED (D16.)** `Annotated[T, ...]`
  is parsed and its extras kept as build-time metadata; a **call in field-default position**
  (`x: int = Field(0, gt=0)`) is recognized and its folded keyword/positional arguments are
  recorded in `ClassInfo.field_meta` instead of being rejected. `default_factory=list`/`dict`
  gives per-instance empty containers. Still constant-folded: arbitrary factories and
  non-foldable argument expressions remain rejected. *Also unblocks:*
  `dataclasses.field(default_factory=...)` parity everywhere.

- **LB5 — general unions.** ✅ **CLEARED.** `TUnion(members)` is a closed, runtime-tagged sum
  (D24): canonically ordered members that must differ in runtime kind (SE218 otherwise),
  `isinstance()` as the sole narrowing form (SE210 for any other use), a Rust `enum` with
  generated `is_i`/`as_i`/`mut_i`/`into_i` accessors on Backend A and a flat `{i8 tag, ...members}`
  struct on Backend B, implicit member→union widening at every annotated boundary, and a
  `{"k":"union","members":[...]}` field-table node with matching dump/build lowering in both
  the compiler and the shim. Union-to-union widening, same-kind members and `isinstance()` as
  a general predicate stay rejected. *Tests:* `tests/accept/086_unions.py`,
  `tests/accept/087_union_fields.py`, `tests/reject/r084`–`r087`.

- **LB6 — `Enum`.** ✅ **CLEARED.** C-like enums only: `class C(Enum | IntEnum | StrEnum)` with
  constant `int`/`str` members, collected into `EnumInfo` and lowered to a fieldless Rust enum
  (Backend A) / an `i64` ordinal (Backend B), with `.value`, `.name`, `C(value)` lookup and Copy
  semantics. Methods, `auto()`, aliases and class iteration stay rejected (D21). Data-carrying
  enums remain LB5's problem. *Tests:* `tests/accept/083_enums.py`, `tests/reject/r075`–`r078`.

- **LB7 — `set` / `frozenset`.** ✅ **CLEARED.** `TSet(elem)` with Copy elements, represented
  like `list[T]` and iterating in **insertion order** (D20): literals, comprehensions, `in`,
  `add`/`discard`/`remove`/`pop`/`clear`/`update`, set algebra and comparisons, both backends.
  `frozenset[T]` is an accepted alias, not a distinct immutable type.
  *Tests:* `tests/accept/082_sets.py`, `tests/reject/r073`–`r074`.

- **LB8 — `**kwargs` unpacking at call sites.** ✅ **CLEARED.** A `**` argument whose value is
  a **dict literal** is expanded into keyword arguments during type checking; `Model(**mapping)`
  on a model class lowers to the `fields_build` helper (strict field types). `**mapping` into
  a plain function, and mixing `**mapping` with positional arguments, stay rejected (SE201) —
  there is no runtime keyword-argument mechanism. *Tests:* `tests/accept/079_kwargs_unpack.py`,
  `tests/reject/r067`–`r068`.

- **LB9 — generic classes with a base.** ✅ **CLEARED (D23).** `class Page(Base, Generic[T])`
  is accepted: the frontend keeps the `Generic[...]` base alongside the single plain
  `@dataclass` base, flattening copies the (non-generic) base members in as usual, and every
  method monomorphizes per instantiation. The field-table intrinsics now accept an
  *instantiated* class — `fields_of(p)`, `fields_json(Page[int])`, `fields_build(Page[int], d)`
  — keying their synthesized helpers on the instantiation and substituting the class's type
  arguments into the field table. Classmethods of a generic class are templates whose `cls`
  and `Self` mean `Page[T]`, monomorphized from an explicit receiver at the call site —
  `Page[int].model_validate(d)` (D25); a bare `Page.model_validate(...)` is SE214, and the
  validator-hook intrinsics accept an instantiation too. Inheriting **from** a generic class
  (`class IntBox(Box[int])`) is still SE201.
  *Tests:* `tests/accept/085_generic_inherit.py`, `tests/accept/088_generic_classmethod.py`,
  `tests/reject/r083`, `tests/reject/r088`.

- **LB10 — `__init__` bodies** (= `venom.md LB7`). ✅ **CLEARED.** A class may define
  `__init__(self: Mut[C], ...) -> None`; the checker desugars it into a module-level factory
  `_serp_init_C(...) -> C` (fields hoisted to locals, ordinary ctor at the end) and retargets
  every `C(...)` call site, so both backends are unchanged. Definite assignment is enforced
  syntactically: every field is assigned exactly once at the top level of the body, reads of
  an unassigned field and missing fields are the new **SE217 uninitialized-field**. Rejected
  on generic/frozen classes and alongside `__post_init__` / `__setattr__` / validator hooks
  (D22). *Tests:* `tests/accept/084_user_init.py`, `tests/reject/r079`–`r082`.

- **LB11 — runtime reflection / dynamic class creation.** ⛔ **CLOSED — rejected (D26).**
  Permanently out of scope ([../features.md](../features.md)): a class is a build-time
  description with no runtime type object, and the field/hook tables are synthesized per class
  at compile time. *Gates:* `create_model`, `extra="allow"` attribute
  access, `arbitrary_types_allowed`, `__get_pydantic_core_schema__`, `TypeAdapter` over
  arbitrary runtime types, `json_encoders`. *These are documented divergences, not
  TODOs* — do not plan work against them.

- **LB12 — `Decimal` / arbitrary-precision numerics.** ⛔ **CLOSED — rejected (D26).** `int` is
  int64 with an overflow trap and `float` is binary64; a decimal *core* type would change the
  numeric tower, both backends' arithmetic lowering and the `PyVal` encoding for one library's
  field type. *Gates:* `Decimal` fields, `max_digits`/`decimal_places`, big ints. If exact
  decimals are ever wanted they arrive as a library struct (coefficient + exponent over
  `i64`), not as a language change.

- **LB13 — attribute-write hooks (`__setattr__`) + frozen classes.** ✅ **CLEARED.**
  `__setattr__(self: Mut[C], name: str, value: PyVal) -> None` is an allowed dunder; every
  field write `obj.f = v` in checked code is rewritten to `obj.__setattr__("f", v)` when the
  class defines it, and construction (including `__post_init__`) bypasses the hook, matching
  CPython's dataclass behaviour. The new `fields_set(obj, name, value)` intrinsic performs the
  actual typed write. `@dataclass(frozen=True)` is accepted and propagates through
  flattening; assigning a frozen field is SE201 at check time. *Still open:* property setters
  and `__hash__`. *Tests:* `tests/accept/081_frozen_setattr.py`, `tests/reject/r071`–`r072`.

- **LB14 — foldable function references in build-time metadata.** ✅ **CLEARED.** A bare name
  in `Field()`/`ConfigDict()`/`Annotated` metadata position folds to an `FnRef`, travels
  through `fields_json`/`hooks_json` as `{"__fn__": name}`, and the class's synthesized
  `run_hook` dispatcher can call it. Referenced functions must be module-level and shaped
  `(v: PyVal) -> PyVal`; unknown names and wrong shapes are SE214/SE201. *Still open:*
  `WrapValidator` (needs the inner validator passed as a value) and arbitrary
  `default_factory`. *Tests:* `tests/accept/080_meta_fnrefs.py`, `tests/reject/r069`–`r070`.

## Dependency chains, shortest first

```
M0 intrinsics .................. LB1  ✅ cleared (D16)
M1 core model surface .......... LB1 + LB3  ✅ shipped
M2 scalar/container coercion ... ✅ shipped (incl. datetime/date/timedelta/UUID, D31)
M5 ValidationError parity ...... ✅ shipped (errors() shape diverges)
M6 nested models ............... ✅ shipped (incl. self-referential models, D32)
M3 Field()/Annotated ........... LB4  ✅ shipped
M9 model_json_schema ........... ✅ shipped
M1 User(**data) ................ LB8  ✅ shipped
M4 validators .................. ✅ shipped (before/after + Annotated markers; wrap/plain + serializers open)
M7 model_config ................ ✅ shipped (extra/str_*/populate_by_name/frozen/validate_assignment/alias_generator)
M9 Venom body models ........... venom.md LB2
M2 enum fields ................. LB6  ✅ shipped (D21)
M2 set fields .................. LB7  ✅ shipped (D20)
M8 unions ...................... LB5  ✅ shipped (D24)
M8 generic models .............. LB9  ✅ shipped (D23 + D25)
M2 Decimal ..................... LB12  ⛔ rejected (D26 — divergence)
M10 TypeAdapter / create_model . LB11  ⛔ rejected (D26 — divergence)
```

**The language-blocker list LB1–LB14 is closed (D26).** LB1–LB10, LB13 and LB14 are
implemented; LB11 and LB12 are rejected outright, not deferred. Everything still open below
is *library* work.

**Next, in order:** `SecretStr`/`Base64Bytes` over the D31 known-class mechanism, then
`conint()`/`constr()`, then discriminated unions, then Venom body models via `venom.md LB2`.
