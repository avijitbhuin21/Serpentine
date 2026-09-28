"""serp-molt Base64Bytes fields: base64 text in, bytes on the model, base64 text out."""
from __future__ import annotations

from serp_molt import Base64Bytes, BaseModel
from serpentine import PyVal


class Blob(BaseModel):
    name: str
    payload: Base64Bytes


def main() -> None:
    b: Blob = Blob.model_validate({"name": "greeting", "payload": "aGVsbG8gd29ybGQ="})
    print(b.name)
    print(b.payload)
    print(len(b.payload))
    print(b.model_dump())
    print(b.model_dump_json())

    errs: list[PyVal] = Blob.model_validate_errors({"name": "x", "payload": "not base64!!"})
    for e in errs:
        print(e["type"], e["loc"], e["msg"])

    round2: Blob = Blob.model_validate_json('{"name": "n", "payload": "AAECAw=="}')
    print(round2.payload)
    print(round2.model_dump_json())

    schema: PyVal = Blob.model_json_schema()
    print(schema["properties"]["payload"])


if __name__ == "__main__":
    main()
