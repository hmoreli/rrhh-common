import httpx
import pytest
from conftest import CLAVE, encabezado
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from rrhh_common import (
    Referencia,
    ValidadorReferencias,
    VerificadorToken,
    registrar_manejadores_errores,
)
from rrhh_common.crud import router_crud

FUNCIONARIO = Referencia("funcionario_id", "funcionarios", "/funcionarios/{id}", "funcionario")
EXISTENTES = {1, 2}


class Servicios:
    """Keycloak y ms-funcionarios simulados; cuenta las llamadas."""

    def __init__(self, caido: bool = False) -> None:
        self.caido = caido
        self.tokens = 0
        self.consultas = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            self.tokens += 1
            assert b"client_credentials" in request.content
            return httpx.Response(200, json={"access_token": "tk", "expires_in": 300})
        self.consultas += 1
        assert request.headers["Authorization"] == "Bearer tk"
        assert request.url.host == "ms-funcionarios"
        if self.caido:
            return httpx.Response(502)
        id_ = int(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(200 if id_ in EXISTENTES else 404, json={})


def validador(servicios: Servicios) -> ValidadorReferencias:
    return ValidadorReferencias(
        token_url="http://keycloak:8080/realms/rrhh/protocol/openid-connect/token",
        client_id="ms-prueba",
        client_secret="secreto",
        http=httpx.Client(transport=httpx.MockTransport(servicios)),
    )


def test_existe_y_recuerda():
    servicios = Servicios()
    v = validador(servicios)
    assert v.existe(FUNCIONARIO, 1)
    assert v.existe(FUNCIONARIO, 1)
    assert not v.existe(FUNCIONARIO, 9)
    assert servicios.consultas == 2  # el 1 se recuerda
    assert servicios.tokens == 1  # el token se reutiliza


def test_verificar_id_inexistente_da_422():
    v = validador(Servicios())
    with pytest.raises(RequestValidationError) as exc:
        v.verificar([FUNCIONARIO], {"funcionario_id": 9})
    assert exc.value.errors()[0]["msg"] == "No existe el funcionario 9"


def test_verificar_ignora_campos_vacios():
    servicios = Servicios()
    validador(servicios).verificar([FUNCIONARIO], {"funcionario_id": None})
    assert servicios.consultas == 0


def test_servicio_caido_da_503():
    v = validador(Servicios(caido=True))
    with pytest.raises(HTTPException) as exc:
        v.verificar([FUNCIONARIO], {"funcionario_id": 1})
    assert exc.value.status_code == 503


# --------------------------------------------------------- dentro del CRUD


class Base(DeclarativeBase):
    pass


class Hijo(Base):
    __tablename__ = "hijo"
    id: Mapped[int] = mapped_column(primary_key=True)
    funcionario_id: Mapped[int]


class HijoCrear(BaseModel):
    funcionario_id: int


class HijoParche(BaseModel):
    funcionario_id: int | None = None


class HijoSalida(HijoCrear):
    model_config = ConfigDict(from_attributes=True)
    id: int


def app_con(validador_: ValidadorReferencias | None, config_auth) -> TestClient:
    motor = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(motor)
    fabrica = sessionmaker(motor)

    def sesion():
        with fabrica() as s:
            yield s

    app = FastAPI()
    app.state.verificador = VerificadorToken(
        config_auth, resolver_clave=lambda _: CLAVE.public_key()
    )
    app.state.referencias = validador_
    registrar_manejadores_errores(app)
    app.include_router(
        router_crud(
            modelo=Hijo,
            crear=HijoCrear,
            parche=HijoParche,
            salida=HijoSalida,
            prefijo="/hijos",
            etiqueta="Hijos",
            sesion=sesion,
            referencias=[FUNCIONARIO],
        )
    )
    return TestClient(app)


OPERADOR = encabezado("rrhh-operador")


def test_crud_valida_al_crear_y_al_modificar(config_auth):
    cliente = app_con(validador(Servicios()), config_auth)
    assert cliente.post("/hijos", json={"funcionario_id": 1}, headers=OPERADOR).status_code == 201
    r = cliente.post("/hijos", json={"funcionario_id": 9}, headers=OPERADOR)
    assert r.status_code == 422
    assert r.json()["detalles"] == [
        {"campo": "body.funcionario_id", "mensaje": "No existe el funcionario 9"}
    ]
    r = cliente.patch("/hijos/1", json={"funcionario_id": 9}, headers=OPERADOR)
    assert r.status_code == 422
    assert cliente.patch("/hijos/1", json={"funcionario_id": 2}, headers=OPERADOR).is_success


def test_sin_validador_no_se_valida(config_auth):
    cliente = app_con(None, config_auth)
    assert cliente.post("/hijos", json={"funcionario_id": 9}, headers=OPERADOR).status_code == 201


def test_servicio_interno_puede_leer(config_auth):
    cliente = app_con(None, config_auth)
    r = cliente.get("/hijos", headers=encabezado("servicio-interno"))
    assert r.status_code == 200
    r = cliente.post("/hijos", json={"funcionario_id": 1}, headers=encabezado("servicio-interno"))
    assert r.status_code == 403
