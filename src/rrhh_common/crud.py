"""Router CRUD genérico para recursos simples sobre SQLAlchemy.

Cubre el patrón de los contratos (GET lista, POST, GET/PATCH/DELETE por id),
con paginación limit/offset, filtros por igualdad, búsqueda de texto (?q=)
y control de roles.

    router = router_crud(
        modelo=Hijo, crear=HijoCrear, parche=HijoParche, salida=HijoSalida,
        prefijo="/hijos", etiqueta="Gestión de Hijos", sesion=obtener_sesion,
        filtros={"funcionario_id": int}, busqueda=("nombre",),
    )
"""

import inspect
from collections.abc import Callable, Iterable, Iterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rrhh_common.auth import Usuario, requiere_roles
from rrhh_common.paginacion import Paginacion

ROLES_LECTURA = ("rrhh-operador", "nomina-liquidador", "consulta")
ROLES_ESCRITURA = ("rrhh-operador",)

TODAS = frozenset({"listar", "crear", "obtener", "actualizar", "eliminar"})


def _dependencia_filtros(
    filtros: dict[str, type], busqueda: tuple[str, ...]
) -> Callable[..., dict[str, Any]]:
    """Arma una dependencia con un query param opcional por filtro (visible en OpenAPI).

    Si hay columnas de búsqueda agrega además ?q=, que llega en la clave "q".
    """

    def _filtros(**valores: Any) -> dict[str, Any]:
        return {k: v for k, v in valores.items() if v is not None}

    parametros = [
        inspect.Parameter(
            nombre,
            inspect.Parameter.KEYWORD_ONLY,
            default=Query(None, description=f"Filtrar por {nombre}"),
            annotation=tipo | None,
        )
        for nombre, tipo in filtros.items()
    ]
    if busqueda:
        parametros.append(
            inspect.Parameter(
                "q",
                inspect.Parameter.KEYWORD_ONLY,
                default=Query(
                    None,
                    min_length=1,
                    description="Buscar texto (sin distinguir mayúsculas) en: "
                    + ", ".join(busqueda),
                ),
                annotation=str | None,
            )
        )
    _filtros.__signature__ = inspect.Signature(parametros)  # type: ignore[attr-defined]
    return _filtros


def _conflicto(exc: IntegrityError) -> HTTPException:
    detalle = str(exc.orig).splitlines()[0] if exc.orig else "Restricción de integridad"
    return HTTPException(status.HTTP_409_CONFLICT, detail=f"Conflicto de datos: {detalle}")


def router_crud(
    *,
    modelo: type,
    crear: type[BaseModel],
    parche: type[BaseModel],
    salida: type[BaseModel],
    prefijo: str,
    etiqueta: str,
    sesion: Callable[[], Iterator[Session]],
    filtros: dict[str, type] | None = None,
    busqueda: Iterable[str] = (),
    metodos: Iterable[str] = TODAS,
    roles_lectura: tuple[str, ...] = ROLES_LECTURA,
    roles_escritura: tuple[str, ...] = ROLES_ESCRITURA,
    nombre: str = "Registro",
) -> APIRouter:
    router = APIRouter(prefix=prefijo, tags=[etiqueta])
    metodos = frozenset(metodos)
    leer = requiere_roles(*roles_lectura)
    escribir = requiere_roles(*roles_escritura)
    busqueda = tuple(busqueda)
    filtrar = _dependencia_filtros(filtros or {}, busqueda)

    def _buscar(db: Session, id_: int) -> Any:
        obj = db.get(modelo, id_)
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{nombre} no encontrado")
        return obj

    def _guardar(db: Session, obj: Any) -> Any:
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise _conflicto(exc) from exc
        db.refresh(obj)
        return obj

    def _guardar_borrado(db: Session) -> None:
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise _conflicto(exc) from exc

    if "listar" in metodos:

        @router.get("", response_model=list[salida], summary=f"Listar {prefijo.strip('/')}")
        def listar(
            p: Paginacion = Depends(),
            valores: dict[str, Any] = Depends(filtrar),
            db: Session = Depends(sesion),
            _: Usuario = Depends(leer),
        ):
            texto = valores.pop("q", None)
            consulta = select(modelo).filter_by(**valores).order_by(modelo.id)
            if texto:
                patron = f"%{texto}%"
                consulta = consulta.where(
                    or_(*(getattr(modelo, col).ilike(patron) for col in busqueda))
                )
            return db.scalars(consulta.offset(p.offset).limit(p.limit)).all()

    if "crear" in metodos:

        @router.post("", response_model=salida, status_code=201, summary=f"Crear {nombre.lower()}")
        def crear_(
            datos: crear,  # type: ignore[valid-type]
            db: Session = Depends(sesion),
            _: Usuario = Depends(escribir),
        ):
            obj = modelo(**datos.model_dump())
            db.add(obj)
            return _guardar(db, obj)

    if "obtener" in metodos:

        @router.get("/{id}", response_model=salida, summary=f"Obtener {nombre.lower()} por ID")
        def obtener(id: int, db: Session = Depends(sesion), _: Usuario = Depends(leer)):
            return _buscar(db, id)

    if "actualizar" in metodos:

        @router.patch("/{id}", response_model=salida, summary=f"Actualizar {nombre.lower()}")
        def actualizar(
            id: int,
            datos: parche,  # type: ignore[valid-type]
            db: Session = Depends(sesion),
            _: Usuario = Depends(escribir),
        ):
            obj = _buscar(db, id)
            for campo, valor in datos.model_dump(exclude_unset=True).items():
                setattr(obj, campo, valor)
            return _guardar(db, obj)

    if "eliminar" in metodos:

        @router.delete("/{id}", status_code=204, summary=f"Eliminar {nombre.lower()}")
        def eliminar(id: int, db: Session = Depends(sesion), _: Usuario = Depends(escribir)):
            db.delete(_buscar(db, id))
            _guardar_borrado(db)
            return Response(status_code=204)

    return router
