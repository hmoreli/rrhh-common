"""Librería compartida de los microservicios de RRHH."""

from rrhh_common.auth import Usuario, VerificadorToken, requiere_roles, usuario_actual
from rrhh_common.config import ConfigAuth
from rrhh_common.errores import ErrorRespuesta, registrar_manejadores_errores
from rrhh_common.paginacion import Pagina, Paginacion

__all__ = [
    "ConfigAuth",
    "ErrorRespuesta",
    "Pagina",
    "Paginacion",
    "Usuario",
    "VerificadorToken",
    "registrar_manejadores_errores",
    "requiere_roles",
    "usuario_actual",
]
