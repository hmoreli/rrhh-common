# rrhh-common

Librería compartida por los microservicios de RRHH (FastAPI). Resuelve lo que todos necesitan igual:

- **Autenticación**: valida el JWT de Keycloak (firma vía JWKS, emisor, audiencia, vencimiento).
- **Roles**: `requiere_roles("nomina-liquidador")` responde 403 si falta el rol; `rrhh-admin` siempre pasa.
- **Paginación**: `?limit=&offset=` y la respuesta `Pagina[T]` (`items`, `total`, `limit`, `offset`).
- **Errores**: un formato único `{codigo, mensaje, detalles}` para 4xx y validaciones.
- **Llamadas entre servicios**: `ClienteServicio` con token de *client credentials*.
- **Ids de otros servicios**: entre schemas no hay FK física, así que `Referencia` + `ValidadorReferencias` preguntan al servicio dueño si el id existe antes de guardar (422 si no existe, 503 si el servicio no responde).
- **CRUD genérico** (`rrhh_common.crud`, extra `[db]`): `router_crud(...)` arma GET lista, POST y GET/PATCH/DELETE por id sobre un modelo SQLAlchemy, con paginación, filtros por igualdad, búsqueda de texto con `?q=` (parámetro `busqueda`), 404/409 y roles de lectura y escritura.

## Instalar en un microservicio

```bash
pip install "rrhh-common[db] @ git+https://github.com/hmoreli/rrhh-common@main"
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

Un recurso CRUD completo:

```python
from rrhh_common.crud import router_crud

app.include_router(
    router_crud(
        modelo=Hijo,
        crear=HijoCrear,
        parche=HijoParche,
        salida=HijoSalida,
        prefijo="/hijos",
        etiqueta="Gestión de Hijos",
        nombre="Hijo",
        sesion=obtener_sesion,
        filtros={"funcionario_id": int},
    )
)
```

Por defecto leen `rrhh-operador`, `nomina-liquidador`, `consulta` y `servicio-interno` (los otros servicios), y escribe `rrhh-operador` (`rrhh-admin` siempre puede).

Validar ids de otros servicios:

```python
from rrhh_common import Referencia, ValidadorReferencias, verificar_referencias

FUNCIONARIO = Referencia("funcionario_id", "funcionarios", "/funcionarios/{id}", "funcionario")

app.state.referencias = ValidadorReferencias.desde_entorno()  # None si no hay client
router_crud(..., referencias=[FUNCIONARIO])  # valida en POST y PATCH


@router.post("/permisos")
def crear(datos: PermisoCrear, request: Request):
    verificar_referencias(request, [FUNCIONARIO], datos.model_dump())
```

Variables de entorno:

| Variable | Ejemplo | Obligatoria |
| --- | --- | --- |
| `KEYCLOAK_ISSUER` | `http://localhost:8080/realms/rrhh` | Sí |
| `KEYCLOAK_JWKS_URL` | `http://keycloak:8080/realms/rrhh/protocol/openid-connect/certs` | No (se deriva del issuer) |
| `KEYCLOAK_AUDIENCE` | `rrhh-api` | No (por defecto `rrhh-api`) |
| `SERVICIO_CLIENT_ID` | `ms-formacion` | No: sin él no se validan ids de otros servicios |
| `SERVICIO_CLIENT_SECRET` | `ms-formacion-dev` | Si hay `SERVICIO_CLIENT_ID` |
| `KEYCLOAK_TOKEN_URL` | `http://keycloak:8080/realms/rrhh/protocol/openid-connect/token` | No (se deriva de `KEYCLOAK_JWKS_URL`) |
| `SERVICIOS_URL` | `http://ms-{servicio}:8000` | No (ese es el valor por defecto) |

Dentro de Docker, `KEYCLOAK_JWKS_URL` apunta a `keycloak:8080` mientras el issuer sigue siendo `localhost:8080`, que es el que figura en el token.

## Desarrollo

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```
