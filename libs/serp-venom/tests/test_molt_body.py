"""serp-venom + serp-molt: pydantic-style body validation, model responses and OpenAPI."""
from __future__ import annotations

from typing import Annotated

from serp_fastapi import (ClientResponse, FastAPI, JSONResponse, Request, Response,
                          TestClient)
from serp_molt import BaseModel, Field, ValidationError
from serpentine import Owned, PyVal, move


class Item(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    price: Annotated[float, Field(gt=0.0)]
    tags: list[str] = Field(default_factory=list)
    note: str | None = None


class ItemOut(BaseModel):
    name: str
    price: float
    total: float


def _errors_body(errs: Owned[list[PyVal]]) -> PyVal:
    """FastAPI's 422 envelope: {"detail": [ ...pydantic errors... ]}."""
    out: dict[str, PyVal] = {"detail": move(errs)}
    return out


def create_item(req: Owned[Request]) -> Response:
    body: str = req.body
    errs: list[PyVal] = Item.model_validate_json_errors(body)
    if len(errs) > 0:
        return JSONResponse(_errors_body(move(errs)), 422)
    item = Item.model_validate_json(body)
    out = ItemOut(name=item.name, price=item.price, total=item.price * 2.0)
    return JSONResponse(out.model_dump(), 201)


def echo_item(req: Owned[Request]) -> Response:
    """A handler that lets ValidationError escape, to show the raise path works."""
    try:
        item = Item.model_validate_json(req.body)
        return JSONResponse(item.model_dump(False, True))
    except ValidationError as e:
        return JSONResponse({"detail": str(e)}, 422)


def openapi(req: Owned[Request]) -> Response:
    schema: dict[str, PyVal] = {
        "openapi": "3.1.0",
        "info": {"title": "venom+molt", "version": "0.1.0"},
        "paths": {
            "/items": {"post": {"requestBody": Item.model_json_schema(),
                                "responses": {"201": ItemOut.model_json_schema()}}},
        },
    }
    return JSONResponse(schema)


def build_app() -> FastAPI:
    """The app under test."""
    app = FastAPI()
    app.add_api_route("/items", create_item, ["POST"])
    app.add_api_route("/echo", echo_item, ["POST"])
    app.add_api_route("/openapi.json", openapi, ["GET"])
    return app


def main() -> None:
    client: TestClient = TestClient(build_app())

    ok: ClientResponse = client.post("/items", json={"name": "hammer", "price": 9.5,
                                                     "tags": ["tool"]})
    print(ok.status_code, ok.text)

    coerced: ClientResponse = client.post("/items", json={"name": "nail", "price": "3"})
    print(coerced.status_code, coerced.text)

    bad: ClientResponse = client.post("/items", json={"name": "", "price": -1.0})
    print(bad.status_code)
    detail: PyVal = bad.json()["detail"]
    for er in detail:
        print(er["type"], er["loc"], er["msg"])

    raised: ClientResponse = client.post("/echo", json={"name": "x", "price": 0.0})
    print(raised.status_code, raised.text)

    torn: ClientResponse = client.request("POST", "/items", "{not json")
    print(torn.status_code)
    for er in torn.json()["detail"]:
        print(er["type"], er["loc"])

    kept: ClientResponse = client.post("/echo", json={"name": "x", "price": 1.5,
                                                      "note": "hi"})
    print(kept.status_code, kept.text)

    spec: ClientResponse = client.get("/openapi.json")
    print(spec.status_code)
    body: PyVal = spec.json()
    props: PyVal = body["paths"]["/items"]["post"]["requestBody"]["properties"]
    print(body["openapi"], props["price"]["exclusiveMinimum"], props["name"]["maxLength"])
    print(body["paths"]["/items"]["post"]["requestBody"]["required"])


if __name__ == "__main__":
    main()
