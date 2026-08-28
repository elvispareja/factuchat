"""Checklist F1: audit_log registra todo — quién, qué, tenant, antes/después,
IP, user agent y timestamp; los secretos van enmascarados."""

from sqlalchemy import select, text

from app.db.models import AuditLog, User
from tests.conftest import TENANT_A, USERS, auth_headers, do_login

CLIENTE = {
    "tipo_identificacion": "RUC",
    "identificacion": "1791234567001",
    "razon_social": "Auditada S.A.",
}


class TestAuditoriaEscrituras:
    def test_insert_queda_registrado(self, client, ana_tokens, admin_db):
        r = client.post(
            "/api/v1/clientes",
            json=CLIENTE,
            headers={**auth_headers(ana_tokens["access_token"]), "X-Real-IP": "10.7.7.7"},
        )
        assert r.status_code == 201
        cliente_id = r.json()["id"]

        entry = admin_db.scalars(
            select(AuditLog).where(
                AuditLog.tabla == "clientes_finales",
                AuditLog.registro_id == cliente_id,
                AuditLog.accion == "INSERT",
            )
        ).one()
        assert str(entry.tenant_id) == str(TENANT_A)
        assert entry.actor_rol == "CLIENTE"
        assert entry.actor_user_id is not None
        assert entry.ip == "10.7.7.7"
        assert entry.user_agent  # TestClient manda su user agent
        assert entry.despues["razon_social"] == "Auditada S.A."
        assert entry.antes is None
        assert entry.created_at is not None

    def test_update_registra_antes_y_despues(self, client, ana_tokens, admin_db):
        r = client.post(
            "/api/v1/clientes",
            json={**CLIENTE, "identificacion": "1791234568001"},
            headers=auth_headers(ana_tokens["access_token"]),
        )
        cliente_id = r.json()["id"]
        r = client.put(
            f"/api/v1/clientes/{cliente_id}",
            json={**CLIENTE, "identificacion": "1791234568001", "razon_social": "Renombrada SA"},
            headers=auth_headers(ana_tokens["access_token"]),
        )
        assert r.status_code == 200

        entry = admin_db.scalars(
            select(AuditLog).where(
                AuditLog.tabla == "clientes_finales",
                AuditLog.registro_id == cliente_id,
                AuditLog.accion == "UPDATE",
            )
        ).one()
        assert entry.antes["razon_social"] == "Auditada S.A."
        assert entry.despues["razon_social"] == "Renombrada SA"
        # Solo los campos que cambiaron
        assert "identificacion" not in entry.despues


class TestAuditoriaLogin:
    def test_login_ok_y_fallido_quedan_en_bitacora(self, client, admin_db, admin_engine):
        do_login(client, "ana", codigo="000000", ip="10.8.8.8")
        do_login(client, "ana", admin_engine=admin_engine, ip="10.8.8.8")

        acciones = (
            admin_db.execute(
                text(
                    "SELECT accion FROM audit_log a JOIN users u ON u.id = a.actor_user_id"
                    " WHERE u.email = :email ORDER BY a.created_at"
                ),
                {"email": USERS["ana"]["email"]},
            )
            .scalars()
            .all()
        )
        assert "LOGIN_FALLIDO" in acciones
        assert "LOGIN_OK" in acciones


class TestEnmascaramiento:
    def test_los_secretos_nunca_van_en_claro_a_la_auditoria(self, admin_engine, database, admin_db):
        """El listener enmascara los campos sensibles antes de escribirlos.

        Antes esto se comprobaba sobre `password_hash`; esa columna ya no
        existe —se entra con código, no con contraseña— así que ahora se mide
        sobre el secreto de la app de autenticación, que es el que queda.
        """
        from app.core.audit import SENSITIVE_FIELDS

        assert "totp_secret_enc" in SENSITIVE_FIELDS
        user = admin_db.scalars(select(User).where(User.email == "ana@empresa-a.ec")).one()
        user.totp_secret_enc = "secreto-que-no-debe-verse"
        admin_db.commit()

        entry = admin_db.scalars(
            select(AuditLog)
            .where(AuditLog.tabla == "users", AuditLog.registro_id == str(user.id))
            .order_by(AuditLog.created_at.desc())
        ).first()
        assert entry is not None
        assert entry.despues["totp_secret_enc"] == "***"
        assert "secreto-que-no-debe-verse" not in str(entry.despues)

    def test_totp_config_enmascarado(self, client, admin_auth, admin_db):
        entry = admin_db.scalars(
            select(AuditLog).where(AuditLog.accion == "TOTP_CONFIG").limit(1)
        ).first()
        assert entry is not None
        assert entry.despues["totp_secret_enc"] == "***"
