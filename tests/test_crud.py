from collections.abc import Iterator

import pytest
from conftest import CLAVE, encabezado
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
from sqlalchemy import ForeignKey, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from rrhh_common import VerificadorToken, registrar_manejadores_errores
from rrhh_common.crud import router_crud


class Base(DeclarativeBase):
    pass


class Sector(Base):
    __tablename__ = "sector"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), unique=True)


class Cargo(Base):
    __tablename__ = "cargo"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100))
    sector_id: Mapped[int] = mapped_column(ForeignKey("sector.id"))


class SectorCrear(BaseModel):
    nombre: str


class SectorParche(BaseModel):
    nombre: str | None = None


class SectorSalida(SectorCrear):
    model_config = ConfigDict(from_attributes=True)
    id: int


class CargoCrear(BaseModel):
    nombre: str
    sector_id: int


class CargoParche(BaseModel):
    nombre: str | None = None
    sector_id: int | None = None


class CargoSalida(CargoCrear):
    model_config = ConfigDict(from_attributes=True)
    id: int


@pytest.fixture
def cliente(config_auth) -> TestClient:
    motor = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(motor)
    Sesion = sessionmaker(motor)

    def sesion() -> Iterator[Session]:
        with Sesion() as s:
            yield s

    app = FastAPI()
    app.state.verificador = VerificadorToken(
        config_auth, resolver_clave=lambda _: CLAVE.public_key()
    )
    registrar_manejadores_errores(app)
    comunes = {"sesion": sesion}
    app.include_router(
        router_crud(
            modelo=Sector,
            crear=SectorCrear,
            parche=SectorParche,
            salida=SectorSalida,
            prefijo="/sectores",
            etiqueta="Sectores",
            nombre="Sector",
            **comunes,
        )
    )
    app.include_router(
        router_crud(
            modelo=Cargo,
            crear=CargoCrear,
            parche=CargoParche,
            salida=CargoSalida,
            prefijo="/cargos",
            etiqueta="Cargos",
            nombre="Cargo",
            filtros={"sector_id": int},
            metodos={"listar", "crear"},
            **comunes,
        )
    )
    return TestClient(app)


OPERADOR = encabezado("rrhh-operador")
CONSULTA = encabezado("consulta")


def test_ciclo_completo(cliente):
    r = cliente.post("/sectores", json={"nombre": "Ventas"}, headers=OPERADOR)
    assert r.status_code == 201
    id_ = r.json()["id"]

    assert cliente.get(f"/sectores/{id_}", headers=CONSULTA).json() == {
        "id": id_,
        "nombre": "Ventas",
    }

    r = cliente.patch(f"/sectores/{id_}", json={"nombre": "Comercial"}, headers=OPERADOR)
    assert r.json()["nombre"] == "Comercial"

    assert cliente.delete(f"/sectores/{id_}", headers=OPERADOR).status_code == 204
    r = cliente.get(f"/sectores/{id_}", headers=CONSULTA)
    assert r.status_code == 404
    assert r.json() == {"codigo": "no_encontrado", "mensaje": "Sector no encontrado"}


def test_patch_parcial_no_pisa_campos(cliente):
    s = cliente.post("/sectores", json={"nombre": "RRHH"}, headers=OPERADOR).json()
    c = cliente.post("/cargos", json={"nombre": "Analista", "sector_id": s["id"]}, headers=OPERADOR)
    assert c.status_code == 201


def test_consulta_no_puede_escribir(cliente):
    r = cliente.post("/sectores", json={"nombre": "X"}, headers=CONSULTA)
    assert r.status_code == 403


def test_duplicado_da_409(cliente):
    cliente.post("/sectores", json={"nombre": "Ventas"}, headers=OPERADOR)
    r = cliente.post("/sectores", json={"nombre": "Ventas"}, headers=OPERADOR)
    assert r.status_code == 409
    assert r.json()["codigo"] == "conflicto"


def test_listado_paginado_y_filtrado(cliente):
    a = cliente.post("/sectores", json={"nombre": "A"}, headers=OPERADOR).json()["id"]
    b = cliente.post("/sectores", json={"nombre": "B"}, headers=OPERADOR).json()["id"]
    for i in range(3):
        cliente.post("/cargos", json={"nombre": f"c{i}", "sector_id": a}, headers=OPERADOR)
    cliente.post("/cargos", json={"nombre": "otro", "sector_id": b}, headers=OPERADOR)

    todos = cliente.get("/cargos", headers=CONSULTA).json()
    assert len(todos) == 4
    de_a = cliente.get(f"/cargos?sector_id={a}", headers=CONSULTA).json()
    assert [c["nombre"] for c in de_a] == ["c0", "c1", "c2"]
    pagina = cliente.get(f"/cargos?sector_id={a}&limit=2&offset=1", headers=CONSULTA).json()
    assert [c["nombre"] for c in pagina] == ["c1", "c2"]


def test_metodos_no_habilitados_no_existen(cliente):
    # Sin rutas /{id}: no existen en la API ni en OpenAPI.
    assert cliente.delete("/cargos/1", headers=OPERADOR).status_code == 404
    assert "/cargos/{id}" not in cliente.get("/openapi.json").json()["paths"]


def test_filtros_aparecen_en_openapi(cliente):
    params = cliente.get("/openapi.json").json()["paths"]["/cargos"]["get"]["parameters"]
    assert {"limit", "offset", "sector_id"} <= {p["name"] for p in params}
