"""Validación de ids que pertenecen a otro servicio.

Entre schemas no hay FK física: cuando un servicio guarda un `funcionario_id` o un
`cargo_id`, pregunta al servicio dueño si el registro existe antes de guardarlo.

    FUNCIONARIO = Referencia("funcionario_id", "funcionarios", "/funcionarios/{id}", "funcionario")

    router_crud(..., referencias=[FUNCIONARIO])          # en los CRUD genéricos
    verificar_referencias(request, [FUNCIONARIO], datos)  # en rutas propias

La validación se activa cuando el servicio tiene su client de Keycloak configurado
(`SERVICIO_CLIENT_ID` y `SERVICIO_CLIENT_SECRET`). Sin esas variables, por ejemplo
en las pruebas, no se valida nada.
"""

import logging
import os
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Referencia:
    """Un campo que guarda el id de un registro de otro servicio.

    campo: nombre del campo en el cuerpo del request (`funcionario_id`).
    servicio: el servicio dueño (`funcionarios` → http://ms-funcionarios:8000).
    ruta: GET que responde 200 si existe y 404 si no (`/funcionarios/{id}`).
    nombre: para el mensaje de error ("No existe el funcionario 12").
    """

    campo: str
    servicio: str
    ruta: str
    nombre: str


class ValidadorReferencias:
    """Consulta a los otros servicios con el token del servicio (client credentials).

    Recuerda por un rato los ids que ya encontró, para no repetir la consulta en
    cargas masivas.
    """

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        url_servicio: Callable[[str], str] = lambda s: f"http://ms-{s}:8000",
        timeout: float = 3.0,
        recordar_segundos: float = 60.0,
        http: httpx.Client | None = None,
    ) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._url_servicio = url_servicio
        self._recordar = recordar_segundos
        self._http = http or httpx.Client(timeout=timeout)
        self._token: str | None = None
        self._token_vence = 0.0
        self._existentes: dict[str, float] = {}

    @classmethod
    def desde_entorno(cls) -> "ValidadorReferencias | None":
        client_id = os.environ.get("SERVICIO_CLIENT_ID")
        if not client_id:
            log.warning("Sin SERVICIO_CLIENT_ID: no se validan ids de otros servicios")
            return None
        issuer = os.environ["KEYCLOAK_ISSUER"].rstrip("/")
        token_url = os.environ.get("KEYCLOAK_TOKEN_URL", f"{issuer}/protocol/openid-connect/token")
        plantilla = os.environ.get("SERVICIOS_URL", "http://ms-{servicio}:8000")
        return cls(
            token_url=token_url,
            client_id=client_id,
            client_secret=os.environ["SERVICIO_CLIENT_SECRET"],
            url_servicio=lambda s: plantilla.format(servicio=s),
        )

    def _obtener_token(self) -> str:
        if self._token and time.monotonic() < self._token_vence - 30:
            return self._token
        resp = self._http.post(
            self._token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        resp.raise_for_status()
        datos = resp.json()
        self._token = datos["access_token"]
        self._token_vence = time.monotonic() + datos.get("expires_in", 60)
        return self._token

    def existe(self, ref: Referencia, id_: Any) -> bool:
        """True si existe, False si el servicio responde 404.

        Si el servicio no responde o contesta otra cosa, lanza httpx.HTTPError.
        """
        url = self._url_servicio(ref.servicio) + ref.ruta.format(id=id_)
        ahora = time.monotonic()
        if self._existentes.get(url, 0) > ahora:
            return True
        resp = self._http.get(url, headers={"Authorization": f"Bearer {self._obtener_token()}"})
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        self._existentes[url] = ahora + self._recordar
        return True

    def verificar(self, referencias: Iterable[Referencia], datos: Mapping[str, Any]) -> None:
        """422 si algún id no existe; 503 si el servicio dueño no responde."""
        errores = []
        for ref in referencias:
            id_ = datos.get(ref.campo)
            if id_ is None:
                continue
            try:
                encontrado = self.existe(ref, id_)
            except httpx.HTTPError as exc:
                log.warning("No se pudo verificar %s=%s: %s", ref.campo, id_, exc)
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"No se pudo verificar el {ref.nombre} {id_}: "
                    f"ms-{ref.servicio} no responde",
                ) from exc
            if not encontrado:
                errores.append(
                    {
                        "type": "referencia",
                        "loc": ("body", ref.campo),
                        "msg": f"No existe el {ref.nombre} {id_}",
                        "input": id_,
                    }
                )
        if errores:
            raise RequestValidationError(errores)


def verificar_referencias(
    request: Request, referencias: Iterable[Referencia], datos: Mapping[str, Any]
) -> None:
    """Valida con el validador de la app (`app.state.referencias`), si hay uno."""
    validador: ValidadorReferencias | None = getattr(request.app.state, "referencias", None)
    if validador is not None:
        validador.verificar(referencias, datos)
