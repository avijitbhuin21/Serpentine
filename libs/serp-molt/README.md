# serp-molt

A `pydantic` v2 drop-in for the Serpentine subset: declare a model as an
annotated class deriving `BaseModel`, and get keyword construction,
`model_validate` with pydantic's lax coercion table, `model_dump` /
`model_dump_json`, `Field()` constraints, nested models, `@field_validator` /
`@model_validator`, `@field_serializer` / `@model_serializer` /
`@computed_field`, `model_config`, pydantic-shaped `ValidationError` text and
JSON Schema.

Models are not reflection: the compiler's build-time field table is exposed
through the `fields_of` / `fields_json` / `fields_build` intrinsics (and the
hook table through `hooks_json` / `run_hook` / `run_hook_self` /
`run_hook_val` / `run_hook_get` / `run_hook_info`), and
because inheritance is check-time flattening, the single `fields_of(self)` in
`BaseModel.model_dump` is monomorphized against each subclass's own fields.

## API

```python
from serp_molt import (BaseModel, ConfigDict, Field, ValidationError,
                       field_validator, model_validator)

class User(BaseModel):
    id: int
    name: str = Field(default="anon", min_length=2, max_length=10)
    age: Annotated[int, Field(ge=0, le=150)] = 0
    tags: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("name")
    @classmethod
    def lower_name(cls, v: PyVal) -> PyVal:
        return str(v).lower()

    @model_validator(mode="after")
    def check(self: Ref[User]) -> None:
        if self.age > 150:
            raise ValueError("too old")

u = User.model_validate({"id": "7", "name": "Ada"})   # str -> int coercion
u.model_dump_json()
```

- **Class surface:** `model_validate(obj)`, `model_validate_json(text)`,
  `model_construct(values)` (no validation), `model_json_schema()`,
  `model_fields()`, `model_validate_errors(obj)`, plus v1 `parse_obj`,
  `parse_raw`, `schema`.
- **Instance surface:** `model_dump(by_alias=False, exclude_none=False)`,
  `model_dump_json(...)`, `model_copy(update)`, `__str__` (`id=1 name='a'`),
  `__repr__`/`__eq__` from `@dataclass`, plus v1 `dict()` / `json()`.
- **`Field()`:** `default` (positional or keyword), `default_factory`, `gt`,
  `ge`, `lt`, `le`, `multiple_of`, `min_length`, `max_length`, `pattern`,
  `alias`, `validation_alias`, `serialization_alias`, `title`, `description`.
  Usable either in default position or inside `Annotated[T, Field(...)]`.
- **Field types:** `int`, `float`, `bool`, `str`, `bytes`, `T | None`,
  `list[T]`, `dict[str, T]`, `set[T]`, `tuple[...]`, `Enum`/`IntEnum`/`StrEnum`,
  general unions (`int | str`), nested models, models nested in lists/dicts, and
  generic models (`class Page(BaseModel, Generic[T])`, validated as `Page[int]`).
  `PyVal` fields accept anything.
- **Coercion (lax mode):** `"7"`→`int`, `"1.5"`/`int`→`float`, `36.0`→`int`
  when integral, `"true"/"yes"/"on"/"1"`→`bool`, numbers→`str` is *not* done
  (pydantic v2 behaviour).
- **Validators:** `@field_validator(*names, mode="before"|"after")` (a
  `@classmethod` taking one `PyVal`) and `@model_validator(mode="before")` (raw
  input mapping in, mapping out) / `mode="after"` (a `Ref[Self]` method).
  `before` field validators see the raw input, `after` ones see the coerced
  value and their result is re-checked against the field type. Raising
  `ValueError` inside one becomes a `value_error` entry in the accumulated
  `ValidationError`. Validators are inherited, and a subclass redefining the
  method replaces the base hook. `Annotated[T, BeforeValidator(f)]` and
  `Annotated[T, AfterValidator(f)]` also work, where `f` is a module-level
  `(v: PyVal) -> PyVal` function. A two-argument validator
  `(cls, v: PyVal, info: PyVal)` receives a `ValidationInfo`-shaped mapping
  (`info["data"]`, `info["field_name"]`).
- **Serializers:** `@field_serializer(*names)` (a method taking the field's
  value), `@model_serializer` (a method taking the whole dumped mapping and
  returning any `PyVal`) and `@computed_field` + `@property` (added to
  `model_dump` output) all run on the dump path.
- **Constrained aliases:** `PositiveInt`, `NonNegativeInt`, `NegativeInt`,
  `NonPositiveInt`, the four `*Float` counterparts, plus `AnyUrl`,
  `AnyHttpUrl`, `HttpUrl` and `EmailStr` (pattern-based, no
  `email-validator`).
- **Markers:** `Annotated[T, Json()]` parses the field's raw string as JSON
  before validating `T`; `Annotated[T, SkipValidation()]` skips type checks,
  `str_*` config and `Field()` constraints. `PydanticCustomError("type: msg")`
  raised in a validator becomes an entry with that `type`/`msg`.
- **Root models:** a model whose only field is named `root` validates from (and
  dumps back to) the bare value, standing in for `RootModel[T]`.
- **`model_fields_set`:** a **classmethod** —
  `User.model_fields_set(mapping)` returns the field names the input supplies
  explicitly.
- **`model_config = ConfigDict(...)`:** `extra="ignore"|"forbid"`,
  `populate_by_name`, `str_strip_whitespace`, `str_to_lower`, `str_to_upper`,
  `str_min_length`, `str_max_length`, `frozen`, `validate_assignment`,
  `alias_generator`. Inherited unless overridden.
- **Mutation:** field assignment goes through `BaseModel.__setattr__`, so
  `frozen=True` raises a `frozen_instance` `ValidationError` and
  `validate_assignment=True` re-validates the written value against the
  field's type, `str_*` config and `Field()` constraints.
- **Construction:** `User(id=1, name="ada")`, `User(**mapping)` and
  `User(**{"id": 1})` all work. `**` construction uses strict field types (no
  coercion) — use `model_validate` for lax input.
- **Errors:** every failure is collected, not just the first. `str(e)` matches
  pydantic's multi-line `N validation errors for Model` / `loc` / `msg
  [type=..., input_value=..., input_type=...]` layout, and error `type`
  strings (`missing`, `int_parsing`, `greater_than`, `string_too_short`,
  `string_pattern_mismatch`, …) are pydantic's.

## Caps (loud errors or documented divergences)

- `ValidationError` carries only its message; the structured error list comes
  from `Model.model_validate_errors(obj)` instead of `e.errors()`, because a
  Serpentine exception cannot carry a typed payload. (`model_validate_errors`
  reports field errors only — it does not run validators.)
- `loc` is a `list`, not a tuple. `str(e)` omits pydantic's trailing
  `errors.pydantic.dev` URL line.
- Validators take one `PyVal`, or two for `ValidationInfo`
  (`info["data"]`/`info["field_name"]`/`info["context"]` as a mapping, not an
  object). `mode="wrap"` and `mode="plain"` and
  `WrapValidator` are not implemented.
- An `after`-model validator's error reports the input mapping as
  `input_value`, where pydantic reports the model instance.
- `extra="allow"`/`__pydantic_extra__` are absent. `model_fields_set` is a
  classmethod over the *input* mapping, not per-instance state.
  `alias_generator` applies to a model's own fields only (nested models use
  their own config), and hashable frozen models (`__hash__`) are not supported.
- `Enum` fields take (and dump) the member **value**, never an `Enum` instance;
  `use_enum_values` is therefore moot. `set[T]` fields validate from a JSON list
  and dump back to a list, deduped in input order.
- A union field (`int | str`) is validated by the input's runtime kind, not by
  pydantic's smart-union order, and a failure reports one `union_type` error
  instead of one per member. A union of two *models* (`Cat | Dog`) is a compile
  error (`SE201`) because both arrive as JSON objects; discriminated unions
  (`Field(discriminator=...)`) are not implemented.
- Generic models (`class Page(BaseModel, Generic[T])`) are validated through an
  explicit instantiation — `Page[int].model_validate(d)`; a bare
  `Page.model_validate(d)` is a compile error.
- No `Decimal`, `TypeAdapter`, `create_model`, `@validate_call`, or
  `BaseSettings`. `RootModel[T]` is spelled as a single-`root`-field model.
- `date`/`datetime`/`timedelta`/`UUID` fields are supported (ISO text in and
  out, `timedelta` as seconds) but are **naive only** — serp-datetime has no
  timezones. `AnyUrl`/`HttpUrl`/`EmailStr` are pattern-validated `str` aliases,
  not parsed URL objects; `SecretStr`/`Base64Bytes` are absent.
- `@computed_field` values appear in `model_dump`, and in
  `model_json_schema("serialization")` as `readOnly` properties (pydantic's
  `mode="serialization"`); the default validation-mode schema omits them.
- JSON Schema covers `type`/`title`/`description`/`default`/`anyOf`/`$defs`
  + the constraint keywords, `format` for temporal/UUID fields and
  `json_schema_extra`; `mode=` is positional-or-keyword with
  `"validation"`/`"serialization"`, and `by_alias=` defaults to `True`.

## Install

```
serp add serp-molt
pip install serp-molt
```
