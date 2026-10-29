"""Validación de JWT de Keycloak y control de roles para FastAPI.

Uso en un servicio:

    verificador = VerificadorToken(ConfigAuth.desde_entorno())
    app = FastAPI()
    app.state.verificador = verificador

    @app.get("/funcionarios")
    def listar(usuario: Usuario = Depends(requiere_roles("rrhh-operador"))): ...
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from rrhh_common.config import ConfigAuth

ROL_ADMIN = "rrhh-admin"


@dataclass(frozen=True)
class Usuario:
    """Identidad extraída del token."""

    id: str
    username: str
    email: str | None = None
    roles: frozenset[str] = field(default_factory=frozenset)
    claims: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def tiene_rol(self, *roles: str) -> bool:
        return ROL_ADMIN in self.roles or any(r in self.roles for r in roles)


class VerificadorToken:
    """Valida firma, emisor, audiencia y vencimiento de un JWT.

    `resolver_clave` permite inyectar la clave pública en tests; en producción
    se usa el JWKS de Keycloak (con caché).
    """

    def __init__(
        self,
        config: ConfigAuth,
        resolver_clave: Callable[[str], Any] | None = None,
    ) -> None:
        self.config = config
        if resolver_clave is None:
            cliente_jwks = jwt.PyJWKClient(config.jwks_url, cache_keys=True, lifespan=300)

            def resolver_clave(token: str) -> Any:
                return cliente_jwks.get_signing_key_from_jwt(token).key

        self._resolver_clave = resolver_clave

    def verificar(self, token: str) -> Usuario:
        try:
            claims = jwt.decode(
                token,
                self._resolver_clave(token),
                algorithms=list(self.config.algoritmos),
                audience=self.config.audience,
                issuer=self.config.issuer,
                leeway=self.config.margen_segundos,
                options={"require": ["exp", "iat", "iss", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise _no_autorizado("El token expiró") from exc
        except (jwt.PyJWTError, jwt.PyJWKClientError) as exc:
            raise _no_autorizado("Token inválido") from exc
        return _usuario_desde_claims(claims, self.config.audience)


def _usuario_desde_claims(claims: dict[str, Any], cliente: str) -> Usuario:
    roles = set(claims.get("realm_access", {}).get("roles", []))
    roles.update(claims.get("resource_access", {}).get(cliente, {}).get("roles", []))
    return Usuario(
        id=claims["sub"],
        username=claims.get("preferred_username", claims["sub"]),
        email=claims.get("email"),
        roles=frozenset(roles),
        claims=claims,
    )


def _no_autorizado(detalle: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detalle,
        headers={"WWW-Authenticate": "Bearer"},
    )


_bearer = HTTPBearer(auto_error=False)


def usuario_actual(
    request: Request,
    credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Usuario:
    """Dependencia FastAPI: devuelve el usuario del token o responde 401."""
    if credenciales is None:
        raise _no_autorizado("Falta el token de acceso")
    verificador: VerificadorToken = request.app.state.verificador
    return verificador.verificar(credenciales.credentials)


def requiere_roles(*roles: str) -> Callable[..., Usuario]:
    """Dependencia FastAPI: exige al menos uno de los roles (rrhh-admin siempre pasa)."""

    def _dependencia(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
        if roles and not usuario.tiene_rol(*roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tenés permiso para esta operación",
            )
        return usuario

    return _dependencia
