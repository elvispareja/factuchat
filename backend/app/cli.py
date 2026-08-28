"""CLI administrativa (OWASP A07: sin credenciales por defecto).

El primer SUPERADMIN se crea por consola con contraseña fuerte; nunca hay
usuarios sembrados en producción. Usa la conexión de administración
(DATABASE_URL_ADMIN), no la de la app.

Uso:
    python -m app.cli create-superadmin --email admin@dominio --nombre "Nombre"
    python -m app.cli create-tenant --ruc 179... --razon-social "Empresa" --email x@y
"""

import argparse
import json
import sys
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, text

from app.core.config import get_settings


def _admin_engine():
    return create_engine(get_settings().database_url_admin)


def create_superadmin(email: str, nombre: str, password: str | None = None) -> None:
    """Crea una cuenta de superadmin.

    Ya no lleva contraseña: el personal interno entra con su correo y el código
    de su app de autenticación, que se configura en el primer intento de acceso.
    El parámetro `password` se conserva para no romper a quien invoque el
    comando con la firma antigua, pero se ignora y se avisa.
    """
    if password:
        print("Aviso: las contraseñas ya no se usan. Se ignora la que has pasado.")

    user_id = uuid.uuid4()
    with _admin_engine().begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM users WHERE lower(email) = lower(:email)"), {"email": email}
        ).first()
        if exists:
            print(f"Ya existe un usuario con el correo {email}")
            sys.exit(1)
        conn.execute(
            text(
                "INSERT INTO users (id, tenant_id, email, nombre, rol,"
                " is_active, totp_enabled, failed_attempts, lockout_count)"
                " VALUES (:id, NULL, :email, :nombre, 'SUPERADMIN', true, false, 0, 0)"
            ),
            {"id": user_id, "email": email, "nombre": nombre},
        )
        conn.execute(
            text(
                "INSERT INTO audit_log (id, actor_user_id, accion, tabla, registro_id, despues)"
                " VALUES (gen_random_uuid(), :id, 'INSERT', 'users', :rid,"
                " jsonb_build_object('email', CAST(:email AS text),"
                " 'rol', 'SUPERADMIN', 'origen', 'cli'))"
            ),
            {"id": user_id, "rid": str(user_id), "email": email},
        )
    print(f"SUPERADMIN creado: {email} ({user_id})")
    print("Entra con ese correo: el primer intento te hará configurar la app de autenticación.")


def probar_correo(destino: str) -> None:
    """Manda un correo de prueba y cuenta con detalle qué pasó.

    Existe porque un fallo de SMTP se manifiesta, si no, como «el cliente no
    recibió su código» horas después y sin rastro de por qué.
    """
    s = get_settings()
    if not s.smtp_host:
        print("SMTP_HOST está vacío: los correos se escriben en", s.email_outbox_dir)
        print("Rellena deploy/.env y reinicia el contenedor api.")
        sys.exit(1)

    modo = "TLS implícito (465)" if s.smtp_tls_implicito else "STARTTLS"
    print(f"Servidor : {s.smtp_host}:{s.smtp_port}  ·  {modo}")
    print(f"Usuario  : {s.smtp_user or '(sin autenticación)'}")
    print(f"Remitente: {s.email_from or 'no-reply@localhost'}")
    if s.smtp_user and not s.smtp_password:
        print()
        print("Falta SMTP_PASSWORD en deploy/.env.")
        sys.exit(1)

    from app.core.mailer import enviar_correo

    try:
        ident = enviar_correo(
            destino,
            "Prueba de envío de Factuchat",
            "<p style='font-family:system-ui'>Si lees esto, el correo saliente "
            "funciona. Ya se pueden mandar los códigos de acceso.</p>",
        )
    except Exception as e:  # noqa: BLE001 — aquí interesa el motivo exacto
        print()
        print(f"NO se pudo enviar: {type(e).__name__}: {e}")
        print()
        print("Pistas habituales:")
        print("  · «authentication failed» → usuario o contraseña del buzón")
        print("  · se queda colgado       → el 465 tratado como STARTTLS, o el puerto cerrado")
        print("  · «certificate verify»   → el nombre del servidor no coincide con su certificado")
        sys.exit(1)
    print()
    print(f"Enviado a {destino}  ({ident})")


def create_tenant(ruc: str, razon_social: str, email: str) -> None:
    tenant_id = uuid.uuid4()
    with _admin_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tenants (id, ruc, razon_social, email, estado, ambiente_sri,"
                " obligado_contabilidad)"
                " VALUES (:id, :ruc, :rs, :email, 'ACTIVO', 'PRUEBAS', false)"
            ),
            {"id": tenant_id, "ruc": ruc, "rs": razon_social, "email": email},
        )
        conn.execute(
            text(
                "INSERT INTO audit_log (id, accion, tabla, registro_id, despues)"
                " VALUES (gen_random_uuid(), 'INSERT', 'tenants', :rid,"
                " jsonb_build_object('ruc', CAST(:ruc AS text), 'origen', 'cli'))"
            ),
            {"rid": str(tenant_id), "ruc": ruc},
        )
    print(f"Tenant creado: {razon_social} ({tenant_id})")


def seed_planes() -> None:
    """Carga los 4 planes comerciales con la matriz de la maqueta (fase 3.2).

    Idempotente: se puede correr en cada despliegue. Un cambio de precio NO se
    hace aquí, sino creando una versión con vigente_desde futuro (fase 4).
    """
    from app.services.planes import LIMITES_POR_PLAN

    vigente_desde = date(2026, 1, 1)
    with _admin_engine().begin() as conn:
        for nombre, limites in LIMITES_POR_PLAN.items():
            valores = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in limites.items()}
            conn.execute(
                text(
                    "INSERT INTO planes (id, codigo, nombre, precio_mensual, limites,"
                    " vigente_desde, activo, created_at, updated_at)"
                    " VALUES (gen_random_uuid(), :codigo, :nombre, :precio,"
                    " CAST(:limites AS jsonb), :desde, true, now(), now())"
                    " ON CONFLICT (codigo, vigente_desde) DO UPDATE"
                    " SET nombre = EXCLUDED.nombre, precio_mensual = EXCLUDED.precio_mensual,"
                    " limites = EXCLUDED.limites, updated_at = now()"
                ),
                {
                    "codigo": nombre.upper(),
                    "nombre": nombre,
                    "precio": limites["precio"],
                    "limites": json.dumps(valores),
                    "desde": vigente_desde,
                },
            )
    print(f"Planes cargados: {', '.join(LIMITES_POR_PLAN)}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="factuchat")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("create-superadmin")
    p1.add_argument("--email", required=True)
    p1.add_argument("--nombre", required=True)
    p1.add_argument("--password", help="Ignorado: ya no se usan contraseñas")

    p2 = sub.add_parser("create-tenant")
    p2.add_argument("--ruc", required=True)
    p2.add_argument("--razon-social", required=True)
    p2.add_argument("--email", required=True)

    sub.add_parser("seed-planes")

    p3 = sub.add_parser("probar-correo", help="Envía un correo de prueba y explica los fallos")
    p3.add_argument("--a", required=True, dest="destino", help="Dirección de destino")

    args = parser.parse_args()
    if args.cmd == "create-superadmin":
        create_superadmin(args.email, args.nombre, args.password)
    elif args.cmd == "create-tenant":
        create_tenant(args.ruc, args.razon_social, args.email)
    elif args.cmd == "seed-planes":
        seed_planes()
    elif args.cmd == "probar-correo":
        probar_correo(args.destino)


if __name__ == "__main__":
    main()
