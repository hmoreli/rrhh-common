# rrhh-common

Librería compartida por los microservicios de RRHH (FastAPI). Resuelve lo que todos necesitan igual:

- **Autenticación**: valida el JWT de Keycloak (firma vía JWKS, emisor, audiencia, vencimiento).
- **Roles**: `requiere_roles("nomina-liquidador")` responde 403 si falta el rol; `rrhh-admin` siempre pasa.
- **Paginación**: `?limit=&offset=` y la respuesta `Pagina[T]` (`items`, `total`, `limit`, `offset`).
- **Errores**: un formato único `{codigo, mensaje, detalles}` para 4xx y validaciones.
- **Llamadas entre servicios**: `ClienteServicio` con token de *client credentials*.

## Instalar en un microservicio

```bash
pip install "rrhh-common @ git+https://github.com/hmoreli/rrhh-common@v0.1.0"
```

## Uso

```python
from fastapi import Depends, FastAPI
from rrhh_common import (
    ConfigAuth,
    Pagina,
    Paginacion,
    Usuario,
    VerificadorToken,
    registrar_manejadores_errores,
    requiere_roles,
)

app = FastAPI()
app.state.verificador = VerificadorToken(ConfigAuth.desde_entorno())
registrar_manejadores_errores(app)


@app.get("/funcionarios", response_model=Pagina[FuncionarioOut])
def listar(
    p: Paginacion = Depends(),
    usuario: Usuario = Depends(requiere_roles("rrhh-operador", "consulta")),
): ...
```

Variables de entorno:

| Variable | Ejemplo | Obligatoria |
| --- | --- | --- |
| `KEYCLOAK_ISSUER` | `http://localhost:8080/realms/rrhh` | Sí |
| `KEYCLOAK_JWKS_URL` | `http://keycloak:8080/realms/rrhh/protocol/openid-connect/certs` | No (se deriva del issuer) |
| `KEYCLOAK_AUDIENCE` | `rrhh-api` | No (por defecto `rrhh-api`) |

Dentro de Docker, `KEYCLOAK_JWKS_URL` apunta a `keycloak:8080` mientras el issuer sigue siendo `localhost:8080`, que es el que figura en el token.

## Desarrollo

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```
