"""Paginación limit/offset común a todos los listados."""

from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")

LIMITE_MAXIMO = 200


class Paginacion:
    """Dependencia FastAPI: `?limit=50&offset=0`."""

    def __init__(
        self,
        limit: int = Query(50, ge=1, le=LIMITE_MAXIMO, description="Cantidad de registros"),
        offset: int = Query(0, ge=0, description="Registros a saltear"),
    ) -> None:
        self.limit = limit
        self.offset = offset


class Pagina(BaseModel, Generic[T]):
    """Respuesta de un listado paginado."""

    items: list[T]
    total: int
    limit: int
    offset: int
