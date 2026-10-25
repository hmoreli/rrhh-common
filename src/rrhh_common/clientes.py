"""Llamadas entre servicios autenticadas con client credentials de Keycloak."""

import time

import httpx


class TokenDeServicio:
    """Obtiene y cachea el token del servicio (grant client_credentials)."""

    def __init__(self, token_url: str, client_id: str, client_secret: str) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._vence: float = 0.0

    async def obtener(self, http: httpx.AsyncClient) -> str:
        if self._token and time.monotonic() < self._vence - 30:
            return self._token
        resp = await http.post(
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
        self._vence = time.monotonic() + datos.get("expires_in", 60)
        return self._token


class ClienteServicio:
    """Cliente HTTP hacia otro microservicio, con el token del servicio ya puesto.

    ej.: funcionarios = ClienteServicio("http://ms-funcionarios:8000", token)
         resp = await funcionarios.get("/funcionarios/12")
    """

    def __init__(self, base_url: str, token: TokenDeServicio, timeout: float = 5.0) -> None:
        self._token = token
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def get(self, ruta: str, **kwargs) -> httpx.Response:
        return await self._request("GET", ruta, **kwargs)

    async def post(self, ruta: str, **kwargs) -> httpx.Response:
        return await self._request("POST", ruta, **kwargs)

    async def _request(self, metodo: str, ruta: str, **kwargs) -> httpx.Response:
        token = await self._token.obtener(self._http)
        headers = {**kwargs.pop("headers", {}), "Authorization": f"Bearer {token}"}
        return await self._http.request(metodo, ruta, headers=headers, **kwargs)

    async def cerrar(self) -> None:
        await self._http.aclose()
