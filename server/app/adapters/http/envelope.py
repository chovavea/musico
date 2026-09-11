from typing import Any

from fastapi.responses import JSONResponse


def ok(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": 0, "data": data, "msg": ""})


def fail(code: int, msg: str, status_code: int = 400, data: Any = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "data": data, "msg": msg})
