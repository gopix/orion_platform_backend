from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from src.core.response import APIResponse


def register_exception_handlers(app):

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        response = APIResponse(
            status_code=exc.status_code,
            message=exc.detail,
            data=None,
            errors=[exc.detail],
        )
        return JSONResponse(status_code=exc.status_code, content=response.model_dump())

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = [
            {"field": err["loc"][-1], "message": err["msg"]}
            for err in exc.errors()
        ]

        response = APIResponse(
            status_code=422,
            message="Validation error",
            data=None,
            errors=errors,
        )
        return JSONResponse(status_code=422, content=response.model_dump())

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        response = APIResponse(
            status_code=500,
            message="Internal Server Error",
            data=None,
            errors=[str(exc)],
        )
        return JSONResponse(status_code=500, content=response.model_dump())