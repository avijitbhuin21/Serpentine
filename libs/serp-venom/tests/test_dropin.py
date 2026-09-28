"""Venom as a FastAPI drop-in: module-level app, decorators, parameter injection."""
from __future__ import annotations

from serp_fastapi import (APIRouter, Depends, FastAPI, HTTPException, JSONResponse,
                          PlainTextResponse, Request, Response, TestClient)
from serp_molt import BaseModel
from serpentine import Owned, PyVal

app = FastAPI(title="Drop-in")


class Item(BaseModel):
    name: str
    price: float
    tags: list[str] = []


class ItemOut(BaseModel):
    name: str
    price: float
    total: float


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "Hello World"}


@app.get("/items/{item_id}")
def read_item(item_id: int, q: str | None = None, limit: int = 10) -> PyVal:
    out: dict[str, PyVal] = {"item_id": item_id, "limit": limit}
    if q is not None:
        out["q"] = q
    return out


@app.post("/items", status_code=201)
def create_item(item: Item) -> ItemOut:
    return ItemOut(name=item.name, price=item.price, total=item.price * 2.0)


@app.get("/items")
def list_items(skip: int = 0, flag: bool = False) -> list[ItemOut]:
    out: list[ItemOut] = [ItemOut(name="a", price=1.0, total=2.0),
                          ItemOut(name="b", price=2.5, total=5.0)]
    if flag:
        return out
    rest: list[ItemOut] = []
    i: int = skip
    while i < len(out):
        rest.append(out[i].model_copy())
        i += 1
    return rest


@app.get("/users/{user_id}")
def find_user(user_id: str) -> Response:
    if user_id == "0":
        raise HTTPException(status_code=404, detail="User not found")
    if user_id == "bare":
        raise HTTPException(status_code=404)
    return PlainTextResponse("user " + user_id)


@app.get("/raw")
def raw(req: Owned[Request]) -> Response:
    return JSONResponse({"method": req.method, "path": req.url})


@app.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int) -> None:
    return None


@app.get("/scale/{factor}")
def scale(factor: float, name: str) -> PyVal:
    return {"factor": factor, "name": name}


def common_params(q: str | None = None, skip: int = 0, limit: int = 100) -> dict[str, PyVal]:
    out: dict[str, PyVal] = {"skip": skip, "limit": limit}
    if q is not None:
        out["q"] = q
    return out


def current_user(token: str = "anon") -> str:
    if token == "bad":
        raise HTTPException(status_code=401, detail="Invalid token")
    return "user:" + token


@app.get("/search")
def search(commons: dict[str, PyVal] = Depends(common_params),
           who: str = Depends(current_user)) -> PyVal:
    out: dict[str, PyVal] = {"who": who, "commons": commons}
    return out


router = APIRouter(prefix="/admin")


@router.get("/stats")
def admin_stats(verbose: bool = False) -> dict[str, int]:
    return {"routes": 1 if verbose else 0}


@router.post("/items/{item_id}", status_code=202)
def admin_touch(item_id: int, item: Item) -> ItemOut:
    return ItemOut(name=item.name, price=item.price, total=item.price * float(item_id))


def legacy(req: Owned[Request]) -> Response:
    return PlainTextResponse("legacy " + req.url)


@app.get("/caught")
def caught() -> PyVal:
    try:
        raise HTTPException(status_code=418, detail="teapot")
    except HTTPException as e:
        return {"code": e.status_code, "detail": e.detail, "text": str(e)}


def _expect(ok: bool, what: str) -> None:
    """Fail the whole test run (non-zero exit) when a FastAPI-parity expectation breaks."""
    if not ok:
        raise AssertionError("expectation failed: " + what)


app.include_router(router, prefix="/v1")
app.add_api_route("/legacy", legacy, ["GET"])


def main() -> None:
    client = TestClient(app)

    r = client.get("/caught")
    print(r.status_code, r.text)
    _expect(r.status_code == 200, "caught status")
    _expect(r.text == '{"code":418,"detail":"teapot","text":"418: teapot"}', "caught body")
    r = client.get("/search?q=pen&limit=5&token=t1")
    print(r.status_code, r.text)
    _expect(r.text == '{"who":"user:t1","commons":{"skip":0,"limit":5,"q":"pen"}}', "Depends")
    r = client.get("/search")
    print(r.status_code, r.text)
    r = client.get("/search?token=bad")
    print(r.status_code, r.text)
    _expect(r.status_code == 401, "HTTPException inside a dependency")
    r = client.get("/search?limit=x")
    print(r.status_code, r.text)

    r = client.get("/v1/admin/stats?verbose=1")
    print(r.status_code, r.text)
    _expect(r.status_code == 200 and r.text == '{"routes":1}', "APIRouter prefix + include prefix")
    r = client.post("/v1/admin/items/3", json={"name": "bolt", "price": 1.5})
    print(r.status_code, r.text)
    _expect(r.status_code == 202, "router status_code")
    r = client.get("/legacy")
    print(r.status_code, r.text)

    r = client.get("/")
    print(r.status_code, r.text)
    _expect(r.status_code == 200 and r.text == '{"message":"Hello World"}', "root")

    r = client.get("/items/42?q=hello%20world")
    print(r.status_code, r.text)
    _expect(r.text == '{"item_id":42,"limit":10,"q":"hello world"}', "path+query injection")
    r = client.get("/items/7", params={"limit": "3"})
    print(r.status_code, r.text)
    r = client.get("/items/abc")
    print(r.status_code, r.text)
    _expect(r.status_code == 422 and r.json()["detail"][0]["type"] == "int_parsing"
            and r.json()["detail"][0]["loc"][0] == "path", "422 path int_parsing")
    r = client.get("/items/1?limit=many")
    print(r.status_code, r.text)

    r = client.post("/items", json={"name": "hammer", "price": 9.5})
    print(r.status_code, r.text)
    _expect(r.status_code == 201 and r.text == '{"name":"hammer","price":9.5,"total":19.0}',
            "model body + status_code=201")
    r = client.post("/items", json={"name": "nail"})
    print(r.status_code, r.text)
    r = client.post("/items", json={"name": "nail", "price": "cheap"})
    print(r.status_code)
    for e in r.json()["detail"]:
        print(e["type"], e["loc"], e["msg"])

    r = client.get("/items")
    print(r.status_code, r.text)
    r = client.get("/items?skip=1")
    print(r.status_code, r.text)
    r = client.get("/items?flag=true")
    print(r.status_code, len(r.json()))
    r = client.get("/items?flag=maybe")
    print(r.status_code, r.text)

    r = client.get("/users/0")
    print(r.status_code, r.text)
    _expect(r.status_code == 404 and r.text == '{"detail":"User not found"}', "HTTPException kwargs")
    r = client.get("/users/bare")
    print(r.status_code, r.text)
    _expect(r.text == '{"detail":"Not Found"}', "HTTPException default detail")
    r = client.get("/users/12")
    print(r.status_code, r.text, r.headers["content-type"])

    r = client.get("/raw?x=1")
    print(r.status_code, r.text)

    r = client.delete("/items/3")
    print(r.status_code, r.text)
    _expect(r.status_code == 204 and r.text == "", "204 empty body")

    r = client.get("/scale/2.5?name=x")
    print(r.status_code, r.text)
    r = client.get("/scale/2.5")
    print(r.status_code, r.text)
    r = client.get("/scale/big?name=x")
    print(r.status_code, r.text)

    r = client.put("/items", json={"name": "x"})
    print(r.status_code, r.text)
    r = client.get("/nope")
    print(r.status_code, r.text)
    print(app.title, len(app.routes), len(router.routes))


if __name__ == "__main__":
    main()
