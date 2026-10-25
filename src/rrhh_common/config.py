"""Configuración leída de variables de entorno."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ConfigAuth:
    """Datos para validar tokens emitidos por Keycloak.

    issuer: URL del realm, p. ej. http://keycloak:8080/realms/rrhh
    audience: client_id del servicio que recibe el token (claim `aud`).
    jwks_url: por defecto, el endpoint de certificados del realm.
    """

    issuer: str
    audience: str
    jwks_url: str
    algoritmos: tuple[str, ...] = ("RS256",)
    margen_segundos: int = 30

    @classmethod
    def desde_entorno(cls) -> "ConfigAuth":
        issuer = os.environ["KEYCLOAK_ISSUER"].rstrip("/")
        return cls(
            issuer=issuer,
            audience=os.environ.get("KEYCLOAK_AUDIENCE", "rrhh-api"),
            jwks_url=os.environ.get("KEYCLOAK_JWKS_URL", f"{issuer}/protocol/openid-connect/certs"),
        )
