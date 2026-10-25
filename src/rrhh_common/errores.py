"""Formato de error único para todas las APIs."""

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

_CODIGOS = {
    400: "solicitud_invalida",
    401: "no_autenticado",
    403: "sin_permiso",
    404: "no_encontrado",
    409: "conflicto",
    422: "datos_invalidos",
}


class ErrorRespuesta(BaseModel):
    codigo: str
    mensaje: str
    detalles: list[dict[str, Any]] | None = None


def _respuesta(status: int, mensaje: str, detalles=None, headers=None) -> JSONResponse:
    cuerpo = ErrorRespuesta(
        codigo=_CODIGOS.get(status, "error"), mensaje=mensaje, detalles=detalles
    )
    return JSONResponse(cuerpo.model_dump(exclude_none=True), status_code=status, headers=headers)


def registrar_manejadores_errores(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException) -> JSONResponse:
        return _respuesta(exc.status_code, str(exc.detail), headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validacion(_: Request, exc: RequestValidationError) -> JSONResponse:
        detalles = [
            {"campo": ".".join(str(p) for p in e["loc"]), "mensaje": e["msg"]} for e in exc.errors()
        ]
        return _respuesta(422, "Datos de entrada inválidos", detalles)
