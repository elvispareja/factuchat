"""Fixtures: base de datos real (PostgreSQL con RLS), seeds y cliente HTTP.

Los tests corren DENTRO del contenedor api contra el postgres del compose de
desarrollo: así se prueba el RLS de verdad, no un sqlite de juguete.

PERO EN SU PROPIA BASE. Hasta ahora compartían la de desarrollo y, como la
suite empieza con `DROP SCHEMA public CASCADE`, cada ejecución borraba lo que
hubiera cargado a mano quien estuviera probando la aplicación. Ahora se crea y
se usa `<base>_test`, y hay un cortafuegos: si por lo que sea el nombre no
acaba en `_test`, la suite se niega a arrancar antes de tocar nada.
"""

import os
import uuid
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

import pytest
from sqlalchemy import create_engine, text


def _con_sufijo_test(url: str) -> str:
    """Devuelve la misma URL apuntando a `<base>_test`."""
    partes = urlsplit(url)
    base = partes.path.lstrip("/")
    if base.endswith("_test"):
        return url
    return urlunsplit(partes._replace(path=f"/{base}_test"))


def _preparar_base_de_tests() -> None:
    """Crea la base de tests si falta y redirige la configuración hacia ella.

    Se hace ANTES de importar nada de `app`, porque `get_settings()` está
    cacheado con lru_cache: si la aplicación se importara primero, se quedaría
    con la base de desarrollo y los tests la machacarían igual.
    """
    from app.core.config import Settings  # import local: solo lee el entorno

    ajustes = Settings()
    url_admin = _con_sufijo_test(ajustes.database_url_admin)
    url_app = _con_sufijo_test(ajustes.database_url)

    nombre = urlsplit(url_admin).path.lstrip("/")
    if not nombre.endswith("_test"):
        raise RuntimeError(
            f"La base de tests sería «{nombre}», que no acaba en _test. "
            "La suite borra el esquema entero: no se ejecuta contra otra cosa."
        )

    # CREATE DATABASE no puede ir en una transacción, y hay que estar conectado
    # a OTRA base para crearla.
    servidor = urlunsplit(urlsplit(url_admin)._replace(path="/postgres"))
    motor = create_engine(servidor, isolation_level="AUTOCOMMIT")
    with motor.connect() as conn:
        existe = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": nombre}
        ).first()
        if not existe:
            conn.execute(text(f'CREATE DATABASE "{nombre}"'))
    motor.dispose()

    os.environ["DATABASE_URL"] = url_app
    os.environ["DATABASE_URL_ADMIN"] = url_admin

    # NADA DE CORREO DE VERDAD. En cuanto se configuró el SMTP real, la suite
    # empezó a enviar mensajes al exterior: RIDEs de facturas inventadas y
    # códigos de acceso, contra un servidor que cobra reputación por cada
    # rebote. Sin SMTP_HOST el mailer escribe un .eml en disco, que además es lo
    # que los tests inspeccionan para comprobar el contenido.
    os.environ["SMTP_HOST"] = ""
    os.environ["SMTP_USER"] = ""
    os.environ["SMTP_PASSWORD"] = ""


_preparar_base_de_tests()

# A partir de aquí ya se puede importar la aplicación: leerá la base de tests.
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from alembic import command  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.models import Establecimiento, Plan, Tenant, User  # noqa: E402
from app.db.models.enums import Rol  # noqa: E402
from app.main import app  # noqa: E402
from app.services.planes import LIMITES_POR_PLAN  # noqa: E402

# --- Identidades de prueba -------------------------------------------------

TENANT_A = uuid.uuid5(uuid.NAMESPACE_DNS, "tenant-a.factuchat.test")
TENANT_B = uuid.uuid5(uuid.NAMESPACE_DNS, "tenant-b.factuchat.test")

USERS = {
    "ana": {"email": "ana@empresa-a.ec", "password": "ClaveSegura123A", "tenant": TENANT_A},
    "bob": {"email": "bob@empresa-b.ec", "password": "ClaveSegura123B", "tenant": TENANT_B},
    "lock": {"email": "lock@empresa-a.ec", "password": "ClaveSegura123L", "tenant": TENANT_A},
    "root": {"email": "root@factuchat.ec", "password": "AdminSeguro123X", "tenant": None},
    # Usuarios desechables: los tests de rate limit los dejan bloqueados en BD
    "rl1": {"email": "rl1@empresa-a.ec", "password": "ClaveSegura123R", "tenant": TENANT_A},
    "rl2": {"email": "rl2@empresa-b.ec", "password": "ClaveSegura123S", "tenant": TENANT_B},
    # Usuario para el test de enmascaramiento (su hash se sobreescribe)
    "mask": {"email": "mask@empresa-b.ec", "password": "ClaveSegura123M", "tenant": TENANT_B},
    # Personal interno para la matriz de roles del panel interno (fase 4)
    "soporte": {
        "email": "soporte@factuchat.ec",
        "password": "SoporteSeguro123",
        "tenant": None,
        "rol": Rol.SOPORTE,
    },
    "lectura": {
        "email": "lectura@factuchat.ec",
        "password": "LecturaSegura123",
        "tenant": None,
        "rol": Rol.LECTURA,
    },
}


@pytest.fixture(scope="session")
def admin_engine():
    return create_engine(get_settings().database_url_admin)


@pytest.fixture(scope="session")
def app_engine():
    return create_engine(get_settings().database_url)


@pytest.fixture(scope="session", autouse=True)
def database(admin_engine):
    """Esquema limpio + migraciones + seeds, una vez por sesión de tests."""
    with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        # Doble comprobación antes de destruir: la fixture arrasa el esquema y
        # equivocarse de base aquí cuesta los datos de quien esté probando.
        actual = conn.execute(text("SELECT current_database()")).scalar_one()
        assert str(actual).endswith("_test"), f"NO se borra el esquema de «{actual}»"
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO factuchat_app"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO factuchat_security"))

    command.upgrade(Config("alembic.ini"), "head")

    session_local = sessionmaker(bind=admin_engine)
    with session_local() as db:
        db.add(
            Tenant(
                id=TENANT_A,
                ruc="1790012345001",
                razon_social="Empresa A S.A.S.",
                email="contacto@empresa-a.ec",
                direccion_matriz="Av. Amazonas N23-45, Quito",
            )
        )
        db.add(
            Tenant(
                id=TENANT_B,
                ruc="1790099999001",
                razon_social="Empresa B Cia. Ltda.",
                email="contacto@empresa-b.ec",
                direccion_matriz="Malecón 100, Guayaquil",
            )
        )
        db.flush()  # los tenants deben existir antes de las filas que los referencian
        db.add(
            Establecimiento(
                tenant_id=TENANT_A,
                codigo="001",
                nombre="Matriz",
                direccion="Av. Amazonas N23-45, Quito",
            )
        )
        # Los 4 planes reales, con la matriz de la maqueta (fase 3.2)
        for nombre, limites in LIMITES_POR_PLAN.items():
            db.add(
                Plan(
                    codigo=nombre.upper(),
                    nombre=nombre,
                    precio_mensual=limites["precio"],
                    limites={
                        k: (str(v) if isinstance(v, Decimal) else v) for k, v in limites.items()
                    },
                    vigente_desde=date(2026, 1, 1),
                )
            )
        for key, info in USERS.items():
            rol = info.get("rol") or (Rol.SUPERADMIN if info["tenant"] is None else Rol.CLIENTE)
            db.add(
                User(
                    tenant_id=info["tenant"],
                    email=info["email"],
                    nombre=key.capitalize(),
                    rol=rol,
                )
            )
        db.commit()

        # Firma electrónica de los dos negocios de prueba.
        #
        # No es adorno: desde que existe `exigir_firma`, un negocio SIN
        # certificado no puede operar, así que sin esto la mitad de la suite
        # estaría probando el bloqueo en vez de lo suyo. Se siembra aquí para
        # que los tests de RLS sigan midiendo aislamiento y no el candado.
        from app.services.certificados import guardar_certificado
        from tests.sri_utils import generar_p12_prueba

        for tenant_id, ruc in ((TENANT_A, "1790012345001"), (TENANT_B, "1790099999001")):
            p12, clave, _ = generar_p12_prueba(identificacion=ruc[:10], dias_validez=365)
            guardar_certificado(db, tenant_id, p12, clave)
        db.commit()
    yield


@pytest.fixture(scope="session")
def client(database):
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_redis():
    """Cada test parte con contadores de rate limit en cero."""
    from app.core.ratelimit import get_redis

    get_redis().flushdb()
    yield


@pytest.fixture()
def admin_db(admin_engine):
    """Sesión de administración (sin RLS) para VERIFICAR efectos en los tests."""
    with Session(admin_engine) as db:
        yield db


def codigo_de(admin_engine, email: str) -> str:
    """Emite un código de acceso y lo devuelve en claro.

    En producción el código viaja por correo y de la base solo sale su sha256,
    así que un test no puede «leerlo»: lo pide por la misma vía que la ruta y se
    queda con el valor. El resto del camino —comprobación, caducidad, contador
    de intentos— es exactamente el de verdad.
    """
    from app.services import acceso

    with Session(admin_engine) as db:
        uid = db.execute(
            text("SELECT id FROM users WHERE lower(email) = lower(:e)"), {"e": email}
        ).scalar_one()
        codigo = acceso.emitir(db, uid, "10.0.0.1")
        db.commit()
    return codigo


def do_login(
    client: TestClient,
    who: str,
    admin_engine=None,
    codigo: str | None = None,
    ip: str = "10.9.9.9",
):
    """Entra como `who`. Ya no hay contraseñas.

    Si la cuenta usa app de autenticación, el `codigo` lo pasa quien llama
    (sacado de pyotp). Si no, se emite uno como haría el correo.
    """
    info = USERS[who]
    if codigo is None:
        assert admin_engine is not None, "hace falta admin_engine para emitir el código"
        codigo = codigo_de(admin_engine, info["email"])
    return client.post(
        "/api/v1/auth/login",
        json={"email": info["email"], "codigo": codigo},
        headers={"X-Real-IP": ip},
    )


def _alta_2fa(client, admin_engine, who: str, ip: str) -> dict:
    """Alta de la app de autenticación para una cuenta interna.

    El alta NO es gratis: exige antes el código que llega al correo. Sin esa
    condición, cualquiera que supiera la dirección del superadmin podría
    registrarse en su 2FA y entrar, porque ya no hay contraseña que lo frene.
    """
    import pyotp

    r = do_login(client, who, admin_engine=admin_engine, ip=ip)
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "TOTP_SETUP_REQUIRED"
    setup_token = r.json()["setup_token"]

    r = client.post("/api/v1/auth/2fa/setup", json={"setup_token": setup_token})
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]

    r = client.post(
        "/api/v1/auth/2fa/activate",
        json={"setup_token": setup_token, "code": pyotp.TOTP(secret).now()},
    )
    assert r.status_code == 204, r.text

    r = do_login(client, who, codigo=pyotp.TOTP(secret).now(), ip=ip)
    assert r.status_code == 200, r.text
    data = r.json()
    return {
        "access": data["access_token"],
        "refresh": data["refresh_token"],
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "secret": secret,
    }


@pytest.fixture(scope="session")
def admin_auth(client, admin_engine):
    """SUPERADMIN: código por correo, alta de 2FA y entrada con la app."""
    return _alta_2fa(client, admin_engine, "root", ip="10.9.9.9")


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def ana_tokens(client, admin_engine):
    r = do_login(client, "ana", admin_engine=admin_engine)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def bob_tokens(client, admin_engine):
    r = do_login(client, "bob", admin_engine=admin_engine)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="session")
def soporte_tokens(client, admin_engine):
    """Personal interno que puede actuar sobre inquilinos, pero no configurar.

    Como el resto del personal interno, entra con su app de autenticación: sin
    contraseña, el código del correo solo sirve para darse de alta en ella.
    """
    return _alta_2fa(client, admin_engine, "soporte", ip="10.4.4.1")


@pytest.fixture(scope="session")
def lectura_tokens(client, admin_engine):
    """Personal interno que solo mira."""
    return _alta_2fa(client, admin_engine, "lectura", ip="10.4.4.2")
