"""Patrón superadmin (fase 1.4): consultas cross-tenant SOLO vía funciones
seguras que dejan rastro en audit_log."""

from sqlalchemy import select

from app.db.models import AuditLog
from tests.conftest import auth_headers


class TestPanelInterno:
    def test_superadmin_lista_tenants_y_queda_auditado(self, client, admin_auth, admin_db):
        r = client.get(
            "/api/v1/admin/tenants",
            params={"motivo": "revision de prueba"},
            headers=auth_headers(admin_auth["access"]),
        )
        assert r.status_code == 200
        rucs = {t["ruc"] for t in r.json()}
        assert {"1790012345001", "1790099999001"} <= rucs

        entry = admin_db.scalars(
            select(AuditLog)
            .where(AuditLog.accion == "SA_SELECT", AuditLog.tabla == "tenants")
            .order_by(AuditLog.created_at.desc())
        ).first()
        assert entry is not None
        assert entry.despues["motivo"] == "revision de prueba"
        assert entry.actor_rol == "SUPERADMIN"

    def test_cliente_no_accede_al_panel_interno(self, client, ana_tokens):
        r = client.get("/api/v1/admin/tenants", headers=auth_headers(ana_tokens["access_token"]))
        assert r.status_code == 403
