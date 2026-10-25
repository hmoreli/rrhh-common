import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "http://keycloak:8080/realms/rrhh"
AUDIENCIA = "rrhh-api"
CLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def emitir_token(roles=(), clave=CLAVE, **cambios) -> str:
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


def encabezado(*roles: str) -> dict:
    return {"Authorization": f"Bearer {emitir_token(roles)}"}


@pytest.fixture
def config_auth():
    from rrhh_common import ConfigAuth

    return ConfigAuth(issuer=ISSUER, audience=AUDIENCIA, jwks_url="no-se-usa")
