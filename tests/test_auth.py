import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from rrhh_common import (
    ConfigAuth,
    Pagina,
    Paginacion,
    Usuario,
    VerificadorToken,
    registrar_manejadores_errores,
    requiere_roles,
    usuario_actual,
)

ISSUER = "http://keycloak:8080/realms/rrhh"
AUDIENCIA = "rrhh-api"
CLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTRA_CLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(roles=(), clave=CLAVE, **cambios) -> str:
    ahora = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCIA,
        "sub": "u-1",
        "preferred_username": "hector",
        "iat": ahora,
        "exp": ahora + 300,
        "realm_access": {"roles": list(roles)},
        **cambios,
    }
    return jwt.encode(claims, clave, algorithm="RS256")


@pytest.fixture
def cliente() -> TestClient:
    config = ConfigAuth(issuer=ISSUER, audience=AUDIENCIA, jwks_url="no-se-usa")
    app = FastAPI()
    app.state.verificador = VerificadorToken(config, resolver_clave=lambda _: CLAVE.public_key())
    registrar_manejadores_errores(app)

    @app.get("/yo")
    def yo(usuario: Usuario = Depends(usuario_actual)):
        return {"username": usuario.username, "roles": sorted(usuario.roles)}

    @app.post("/liquidaciones/cerrar")
    def cerrar(_: Usuario = Depends(requiere_roles("nomina-liquidador"))):
        return {"ok": True}

    @app.get("/items", response_model=Pagina[int])
    def items(p: Paginacion = Depends()):
        datos = list(range(10))
        return Pagina(
            items=datos[p.offset : p.offset + p.limit], total=10, limit=p.limit, offset=p.offset
        )

    return TestClient(app)


def auth(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


def test_token_valido_devuelve_usuario(cliente):
    r = cliente.get("/yo", headers=auth(token(["rrhh-operador"])))
    assert r.status_code == 200
    assert r.json() == {"username": "hector", "roles": ["rrhh-operador"]}


def test_roles_de_cliente_se_suman(cliente):
    t = token(["consulta"], resource_access={AUDIENCIA: {"roles": ["nomina-liquidador"]}})
    r = cliente.get("/yo", headers=auth(t))
    assert r.json()["roles"] == ["consulta", "nomina-liquidador"]


def test_sin_token_401(cliente):
    r = cliente.get("/yo")
    assert r.status_code == 401
    assert r.json()["codigo"] == "no_autenticado"
    assert r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "t",
    [
        token(exp=int(time.time()) - 120),
        token(aud="otro-servicio"),
        token(iss="http://evil/realms/rrhh"),
        token(clave=OTRA_CLAVE),
        "no-es-un-jwt",
    ],
    ids=["vencido", "audiencia", "emisor", "firma", "basura"],
)
def test_tokens_invalidos_401(cliente, t):
    assert cliente.get("/yo", headers=auth(t)).status_code == 401


def test_rol_faltante_403(cliente):
    r = cliente.post("/liquidaciones/cerrar", headers=auth(token(["rrhh-operador"])))
    assert r.status_code == 403
    assert r.json()["codigo"] == "sin_permiso"


def test_rol_correcto_y_admin_pasan(cliente):
    for roles in (["nomina-liquidador"], ["rrhh-admin"]):
        r = cliente.post("/liquidaciones/cerrar", headers=auth(token(roles)))
        assert r.status_code == 200


def test_paginacion(cliente):
    r = cliente.get("/items?limit=3&offset=4")
    assert r.json() == {"items": [4, 5, 6], "total": 10, "limit": 3, "offset": 4}


def test_paginacion_invalida_usa_error_comun(cliente):
    r = cliente.get("/items?limit=0")
    assert r.status_code == 422
    assert r.json()["codigo"] == "datos_invalidos"
    assert r.json()["detalles"][0]["campo"] == "query.limit"
