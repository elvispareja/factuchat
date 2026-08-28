"""Checklist F6:
 1. un pedido por transferencia crea registro y notifica;
 2. la aceptación de términos queda auditada CON VERSIÓN.

Además: consumidor final hasta $200, precios que salen del catálogo (no del
cliente) y la tienda gated por plan.
"""

import json
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import AceptacionTerminos, Producto, SolicitudContacto
from app.services import terminos
from tests.conftest import TENANT_A, auth_headers


@pytest.fixture()
def con_tienda(admin_db):
    """El plan que trae la tienda (solo el tope la incluye)."""
    from app.db.models import Plan, Suscripcion
    from app.db.models.enums import EstadoSuscripcion

    plan = admin_db.scalars(select(Plan).where(Plan.codigo == "EMPRESARIO")).one()
    for previa in admin_db.scalars(
        select(Suscripcion).where(Suscripcion.tenant_id == TENANT_A)
    ).all():
        admin_db.delete(previa)
    admin_db.flush()
    sus = Suscripcion(
        tenant_id=TENANT_A,
        plan_id=plan.id,
        estado=EstadoSuscripcion.ACTIVA,
        precio=plan.precio_mensual,
        inicia=date(2026, 1, 1),
    )
    admin_db.add(sus)
    admin_db.commit()
    yield
    obj = admin_db.get(Suscripcion, sus.id)
    if obj is not None:
        admin_db.delete(obj)
        admin_db.commit()


@pytest.fixture()
def producto_en_vitrina(client, ana_tokens, admin_db, con_tienda):
    """Un artículo con stock, marcado para la tienda."""
    codigo = f"TND{uuid.uuid4().hex[:6].upper()}"
    r = client.post(
        "/api/v1/productos",
        json={
            "codigo": codigo,
            "nombre": "Teclado mecánico",
            "tipo": "BIEN",
            "precio_sin_iva": "40.00",
            "codigo_iva": "4",
            "maneja_inventario": True,
            "stock": "10",
            "stock_minimo": "2",
            "mostrar_en_tienda": True,
        },
        headers=auth_headers(ana_tokens["access_token"]),
    )
    assert r.status_code == 201, r.text
    yield r.json()
    obj = admin_db.get(Producto, uuid.UUID(r.json()["id"]))
    if obj is not None:
        admin_db.delete(obj)
        admin_db.commit()


def _h(tokens):
    return auth_headers(tokens["access_token"])


class TestChecklistPedidoPorTransferencia:
    """1. Un pedido por transferencia crea registro y notifica."""

    def test_flujo_completo(self, client, ana_tokens, admin_db, producto_en_vitrina):
        # El equipo arma la venta desde la vitrina
        r = client.post(
            "/api/v1/tienda/pedidos",
            json={
                "items": [{"producto_id": producto_en_vitrina["id"], "cantidad": "2"}],
                "metodo_pago": "TRANSFERENCIA",
                "comprador_nombre": "Marcia Villavicencio",
                "comprador_telefono": "0999123456",
            },
            headers=_h(ana_tokens),
        )
        assert r.status_code == 201, r.text
        pedido = r.json()

        # Queda REGISTRADO, con su número y esperando confirmación del pago
        assert pedido["numero"].startswith("PD-")
        assert pedido["estado"] == "TRANSFERENCIA_POR_CONFIRMAR"
        # El precio sale del catálogo: 2 × $40 = $80 + 15% = $92
        assert Decimal(pedido["subtotal"]) == Decimal("80.00")
        assert Decimal(pedido["iva"]) == Decimal("12.00")
        assert Decimal(pedido["total"]) == Decimal("92.00")

        # Y aparece en la bandeja, contado en su estado
        r = client.get("/api/v1/tienda/pedidos", headers=_h(ana_tokens))
        assert r.status_code == 200
        datos = r.json()
        assert datos["resumen"]["TRANSFERENCIA_POR_CONFIRMAR"] >= 1
        assert any(p["id"] == pedido["id"] for p in datos["pedidos"])

        # No se puede facturar antes de confirmar que el dinero llegó
        r = client.post(f"/api/v1/tienda/pedidos/{pedido['id']}/facturar", headers=_h(ana_tokens))
        assert r.status_code == 422
        assert "Confirma primero" in r.json()["detail"]

        # El equipo confirma el pago → pasa a por entregar
        r = client.post(
            f"/api/v1/tienda/pedidos/{pedido['id']}/confirmar-pago", headers=_h(ana_tokens)
        )
        assert r.status_code == 200, r.text
        assert r.json()["estado"] == "POR_ENTREGAR"

        # Ahora sí se emite el comprobante y baja el inventario
        r = client.post(f"/api/v1/tienda/pedidos/{pedido['id']}/facturar", headers=_h(ana_tokens))
        assert r.status_code == 201, r.text
        assert r.json()["pedido"]["estado"] == "PAGADO"
        assert r.json()["comprobante_id"]

        admin_db.expire_all()
        producto = admin_db.get(Producto, uuid.UUID(producto_en_vitrina["id"]))
        assert producto.stock == Decimal("8")  # 10 − 2

    def test_no_se_factura_dos_veces(self, client, ana_tokens, producto_en_vitrina):
        pedido = client.post(
            "/api/v1/tienda/pedidos",
            json={
                "items": [{"producto_id": producto_en_vitrina["id"], "cantidad": "1"}],
                "metodo_pago": "EFECTIVO",
            },
            headers=_h(ana_tokens),
        ).json()
        assert (
            client.post(
                f"/api/v1/tienda/pedidos/{pedido['id']}/facturar", headers=_h(ana_tokens)
            ).status_code
            == 201
        )
        r = client.post(f"/api/v1/tienda/pedidos/{pedido['id']}/facturar", headers=_h(ana_tokens))
        assert r.status_code == 422
        assert "ya tiene su comprobante" in r.json()["detail"]

    def test_el_precio_no_viene_del_cliente(self, client, ana_tokens, producto_en_vitrina):
        """Mandar un precio en el cuerpo no cambia lo que se cobra."""
        r = client.post(
            "/api/v1/tienda/pedidos",
            json={
                "items": [
                    {
                        "producto_id": producto_en_vitrina["id"],
                        "cantidad": "1",
                        "precio_unitario": "0.01",  # intento de manipulación
                    }
                ],
                "metodo_pago": "EFECTIVO",
            },
            headers=_h(ana_tokens),
        )
        assert r.status_code == 201, r.text
        # Se cobra el precio del catálogo, no el enviado
        assert Decimal(r.json()["subtotal"]) == Decimal("40.00")

    def test_no_vende_mas_de_lo_que_hay(self, client, ana_tokens, producto_en_vitrina):
        r = client.post(
            "/api/v1/tienda/pedidos",
            json={
                "items": [{"producto_id": producto_en_vitrina["id"], "cantidad": "99"}],
                "metodo_pago": "EFECTIVO",
            },
            headers=_h(ana_tokens),
        )
        assert r.status_code == 422
        assert "Solo quedan" in r.json()["detail"]

    def test_consumidor_final_tope_200(self, client, ana_tokens, producto_en_vitrina):
        """6.3: sin datos del comprador, hasta $200."""
        # 6 × $40 = $240 + IVA → supera el tope
        r = client.post(
            "/api/v1/tienda/pedidos",
            json={
                "items": [{"producto_id": producto_en_vitrina["id"], "cantidad": "6"}],
                "metodo_pago": "EFECTIVO",
            },
            headers=_h(ana_tokens),
        )
        assert r.status_code == 422
        assert "200" in r.json()["detail"]
        assert "cédula o el RUC" in r.json()["detail"]

    def test_con_datos_del_comprador_no_hay_tope(self, client, ana_tokens, producto_en_vitrina):
        ident = f"17{uuid.uuid4().int % 100_000_000:08d}"
        cliente = client.post(
            "/api/v1/clientes",
            json={
                "tipo_identificacion": "CEDULA",
                "identificacion": ident,
                "razon_social": "Compradora Grande",
            },
            headers=_h(ana_tokens),
        ).json()
        r = client.post(
            "/api/v1/tienda/pedidos",
            json={
                "items": [{"producto_id": producto_en_vitrina["id"], "cantidad": "6"}],
                "metodo_pago": "EFECTIVO",
                "cliente_final_id": cliente["id"],
            },
            headers=_h(ana_tokens),
        )
        assert r.status_code == 201, r.text
        assert Decimal(r.json()["total"]) == Decimal("276.00")


class TestTiendaGatedPorPlan:
    def test_sin_plan_no_hay_tienda(self, client, ana_tokens, admin_db):
        from app.db.models import Suscripcion

        for previa in admin_db.scalars(
            select(Suscripcion).where(Suscripcion.tenant_id == TENANT_A)
        ).all():
            admin_db.delete(previa)
        admin_db.commit()

        r = client.get("/api/v1/tienda/pedidos", headers=_h(ana_tokens))
        assert r.status_code == 402
        assert r.json()["detail"]["plan_sugerido"] == "Empresario"

    def test_vitrina_solo_muestra_lo_marcado(self, client, ana_tokens, producto_en_vitrina):
        # Un producto NO marcado para la tienda no aparece en la vitrina
        oculto = client.post(
            "/api/v1/productos",
            json={
                "codigo": f"OCU{uuid.uuid4().hex[:6].upper()}",
                "nombre": "Solo para facturar",
                "tipo": "SERVICIO",
                "precio_sin_iva": "10.00",
                "codigo_iva": "4",
                "mostrar_en_tienda": False,
            },
            headers=_h(ana_tokens),
        ).json()

        r = client.get("/api/v1/tienda/vitrina", headers=_h(ana_tokens))
        assert r.status_code == 200
        ids = [p["id"] for p in r.json()]
        assert producto_en_vitrina["id"] in ids
        assert oculto["id"] not in ids

    def test_la_vitrina_muestra_precio_sin_iva(self, client, ana_tokens, producto_en_vitrina):
        """El precio va sin impuesto y la tarifa aparte: así se evita el doble cobro."""
        r = client.get("/api/v1/tienda/vitrina", headers=_h(ana_tokens))
        item = next(p for p in r.json() if p["id"] == producto_en_vitrina["id"])
        assert Decimal(item["precio_sin_iva"]) == Decimal("40.00")
        assert Decimal(item["porcentaje_iva"]) == Decimal("15.00")


class TestChecklistTerminos:
    """2. La aceptación de términos queda auditada CON VERSIÓN."""

    def test_documento_publico(self, client):
        r = client.get("/api/v1/publico/terminos")
        assert r.status_code == 200
        d = r.json()
        assert d["titulo"] == "Términos de uso y tratamiento de datos"
        assert len(d["secciones"]) == 9
        assert d["version"] and len(d["sha256"]) == 64
        assert "Última actualización" in d["pie"]
        assert "Acepto los términos y condiciones de uso" in d["texto_casilla"]

    def test_checkout_registra_la_aceptacion_con_version(self, client, admin_db):
        email = f"prueba{uuid.uuid4().hex[:8]}@mail.ec"
        r = client.post(
            "/api/v1/publico/checkout",
            json={
                "nombres": "Juan Carlos",
                "apellidos": "Andrade Loor",
                "identificacion": "1712345678",
                "telefono": "0999999999",
                "email": email,
                "pais": "Ecuador",
                "provincia": "Pichincha",
                "ciudad": "Quito",
                "plan": "INDEPENDIENTE",
                "metodo_pago": "TRANSFERENCIA",
                "acepta": {"condiciones": True, "datos": True},
            },
            headers={"X-Real-IP": "190.1.1.1"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["sube_comprobante"] is True

        filas = admin_db.scalars(
            select(AceptacionTerminos).where(AceptacionTerminos.email == email)
        ).all()
        # DOS constancias: condiciones y datos, cada una con su versión y hash
        assert len(filas) == 2
        assert {f.documento for f in filas} == {"TERMINOS", "DATOS_PERSONALES"}
        for f in filas:
            assert f.version == terminos.DOCUMENTO.version
            assert f.sha256 == terminos.DOCUMENTO.sha256
            assert f.aceptado is True
            assert f.aceptado_at is not None
            assert f.ip == "190.1.1.1"
            assert f.origen == "CHECKOUT"

    def test_sin_aceptar_no_hay_checkout(self, client, admin_db):
        email = f"noacepta{uuid.uuid4().hex[:8]}@mail.ec"
        r = client.post(
            "/api/v1/publico/checkout",
            json={
                "nombres": "Ana",
                "apellidos": "Pérez",
                "identificacion": "1712345678",
                "telefono": "0999999999",
                "email": email,
                "plan": "INICIAL",
                "metodo_pago": "OTRO",
                "acepta": {"condiciones": True, "datos": False},
            },
        )
        assert r.status_code == 422
        assert "Acepta las condiciones" in r.json()["detail"]
        # Y NO quedó ni la solicitud ni media constancia
        assert (
            admin_db.scalars(
                select(SolicitudContacto).where(SolicitudContacto.email == email)
            ).first()
            is None
        )
        assert (
            admin_db.scalars(
                select(AceptacionTerminos).where(AceptacionTerminos.email == email)
            ).first()
            is None
        )

    def test_la_constancia_es_inmutable(self, client, admin_db):
        """Editar una aceptación destruiría justo lo que hay que probar."""
        from sqlalchemy import text as _text

        email = f"inmut{uuid.uuid4().hex[:8]}@mail.ec"
        client.post(
            "/api/v1/publico/checkout",
            json={
                "nombres": "Inmutable",
                "apellidos": "Prueba",
                "identificacion": "1712345678",
                "telefono": "0999999999",
                "email": email,
                "plan": "INICIAL",
                "metodo_pago": "OTRO",
                "acepta": {"condiciones": True, "datos": True},
            },
        )
        with pytest.raises(Exception, match="inmutable"):
            admin_db.execute(
                _text("UPDATE aceptaciones_terminos SET aceptado = false WHERE email = :e"),
                {"e": email},
            )
            admin_db.commit()
        admin_db.rollback()

    def test_si_el_texto_cambia_el_hash_lo_delata(self):
        """El hash es del texto exacto: no se puede cambiar sin que se note."""
        original = terminos.DOCUMENTO.sha256
        modificado = terminos.Documento(
            titulo=terminos.TITULO,
            version=terminos.VERSION,  # misma versión...
            actualizado=terminos.ACTUALIZADO,
            secciones=[("1. Otra cosa", ["Texto distinto"])],  # ...otro texto
        )
        assert modificado.sha256 != original

    def test_consentimiento_vigente_y_retiro(self, client, admin_db):
        email = f"retiro{uuid.uuid4().hex[:8]}@mail.ec"
        client.post(
            "/api/v1/publico/checkout",
            json={
                "nombres": "Con",
                "apellidos": "Retiro",
                "identificacion": "1712345678",
                "telefono": "0999999999",
                "email": email,
                "plan": "INICIAL",
                "metodo_pago": "OTRO",
                "acepta": {"condiciones": True, "datos": True},
            },
        )
        assert terminos.consentimiento_vigente(admin_db, email) is True

        # El retiro no borra: añade su propia fila y deja el histórico intacto
        terminos.registrar_retiro(admin_db, email, canal="WhatsApp")
        admin_db.commit()
        assert terminos.consentimiento_vigente(admin_db, email) is False
        assert len(terminos.historial(admin_db, email)) == 4


class TestLandingPublica:
    def test_planes_publicos(self, client):
        r = client.get("/api/v1/publico/planes")
        assert r.status_code == 200
        planes = {p["nombre"] for p in r.json()}
        assert {"Inicial", "Independiente", "Emprendedor", "Empresario"} <= planes

    def test_panama_muy_pronto(self, client):
        """Corrección de copy obligatoria: solo Ecuador está en operación."""
        r = client.get("/api/v1/publico/paises")
        paises = {p["pais"]: p for p in r.json()}
        assert paises["Ecuador"]["disponible"] is True
        assert paises["Panamá"]["estado"] == "Muy pronto"
        assert paises["Panamá"]["disponible"] is False

    def test_contacto_devuelve_enlace_de_whatsapp(self, client):
        r = client.post(
            "/api/v1/publico/contacto",
            json={
                "nombre": "Interesada",
                "email": "interesada@mail.ec",
                "telefono": "0999999999",
                "asunto": "Quiero contratar un plan",
                "mensaje": "Quisiera saber más del plan Emprendedor.",
            },
            headers={"X-Real-IP": "190.2.2.2"},
        )
        assert r.status_code == 201, r.text
        assert "WhatsApp" in r.json()["mensaje"]

    def test_rate_limit_del_formulario_publico(self, client):
        """Un formulario público sin freno es un buzón de spam."""
        ip = "190.3.3.3"
        cuerpo = {
            "nombre": "Spam",
            "email": "spam@mail.ec",
            "mensaje": "hola",
        }
        codigos = [
            client.post(
                "/api/v1/publico/contacto", json=cuerpo, headers={"X-Real-IP": ip}
            ).status_code
            for _ in range(7)
        ]
        assert 429 in codigos

    def test_comprobante_solo_acepta_imagen_o_pdf(self, client, admin_db):
        email = f"comp{uuid.uuid4().hex[:8]}@mail.ec"
        solicitud = client.post(
            "/api/v1/publico/checkout",
            json={
                "nombres": "Sube",
                "apellidos": "Comprobante",
                "identificacion": "1712345678",
                "telefono": "0999999999",
                "email": email,
                "plan": "INICIAL",
                "metodo_pago": "TRANSFERENCIA",
                "acepta": {"condiciones": True, "datos": True},
            },
            headers={"X-Real-IP": "190.4.4.1"},
        ).json()

        r = client.post(
            f"/api/v1/publico/checkout/{solicitud['id']}/comprobante",
            files={"archivo": ("virus.exe", b"MZ...", "application/x-msdownload")},
            headers={"X-Real-IP": "190.4.4.1"},
        )
        assert r.status_code == 422
        assert "JPG, PNG o WEBP" in r.json()["detail"]

    def test_comprobante_valido_se_guarda(self, client, admin_db):
        email = f"ok{uuid.uuid4().hex[:8]}@mail.ec"
        solicitud = client.post(
            "/api/v1/publico/checkout",
            json={
                "nombres": "Sube",
                "apellidos": "Bien",
                "identificacion": "1712345678",
                "telefono": "0999999999",
                "email": email,
                "plan": "INICIAL",
                "metodo_pago": "TRANSFERENCIA",
                "acepta": {"condiciones": True, "datos": True},
            },
            headers={"X-Real-IP": "190.5.5.1"},
        ).json()

        r = client.post(
            f"/api/v1/publico/checkout/{solicitud['id']}/comprobante",
            files={
                "archivo": ("transferencia.png", b"\x89PNG\r\n\x1a\n" + b"0" * 100, "image/png")
            },
            headers={"X-Real-IP": "190.5.5.1"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["recibido"] is True

        admin_db.expire_all()
        fila = admin_db.get(SolicitudContacto, uuid.UUID(solicitud["id"]))
        assert fila.comprobante_url is not None

    def test_el_comprobante_no_se_puede_reemplazar(self, client, admin_db):
        """Quien conozca el UUID solo puede completar SU pedido, y una vez: si
        el comprobante ya está, no se sobreescribe."""
        email = f"dup{uuid.uuid4().hex[:8]}@mail.ec"
        solicitud = client.post(
            "/api/v1/publico/checkout",
            json={
                "nombres": "Una",
                "apellidos": "Vez",
                "identificacion": "1712345678",
                "telefono": "0999999999",
                "email": email,
                "plan": "INICIAL",
                "metodo_pago": "TRANSFERENCIA",
                "acepta": {"condiciones": True, "datos": True},
            },
            headers={"X-Real-IP": "190.6.6.1"},
        ).json()

        archivo = {"archivo": ("t.png", b"\x89PNG\r\n\x1a\n" + b"0" * 50, "image/png")}
        primera = client.post(
            f"/api/v1/publico/checkout/{solicitud['id']}/comprobante",
            files=archivo,
            headers={"X-Real-IP": "190.6.6.1"},
        )
        segunda = client.post(
            f"/api/v1/publico/checkout/{solicitud['id']}/comprobante",
            files={"archivo": ("t.png", b"\x89PNG\r\n\x1a\n" + b"9" * 50, "image/png")},
            headers={"X-Real-IP": "190.6.6.1"},
        )
        assert primera.status_code == 201
        assert segunda.status_code == 404

    def test_comprobante_de_un_pedido_inexistente(self, client):
        """No se guarda nada en disco por un UUID inventado."""
        r = client.post(
            f"/api/v1/publico/checkout/{uuid.uuid4()}/comprobante",
            files={"archivo": ("t.png", b"\x89PNG\r\n\x1a\n" + b"0" * 50, "image/png")},
            headers={"X-Real-IP": "190.7.7.1"},
        )
        assert r.status_code == 404

    def test_la_referencia_la_genera_el_servidor(self, client):
        """La maqueta la sacaba de Date.now() en el navegador y colisionaba."""
        cuerpo = {
            "nombres": "Refe",
            "apellidos": "Rencia",
            "identificacion": "1712345678",
            "telefono": "0999999999",
            "email": f"ref{uuid.uuid4().hex[:8]}@mail.ec",
            "plan": "INICIAL",
            "metodo_pago": "OTRO",
            "acepta": {"condiciones": True, "datos": True},
        }
        a = client.post(
            "/api/v1/publico/checkout", json=cuerpo, headers={"X-Real-IP": "190.8.8.1"}
        ).json()
        cuerpo["email"] = f"ref{uuid.uuid4().hex[:8]}@mail.ec"
        b = client.post(
            "/api/v1/publico/checkout", json=cuerpo, headers={"X-Real-IP": "190.8.8.2"}
        ).json()
        assert a["referencia"].startswith("FC-")
        assert a["referencia"] != b["referencia"]

    def test_el_pedido_notifica_al_equipo(self, client, admin_db, monkeypatch):
        """Segunda mitad del checklist F6: «crea registro Y NOTIFICA». Un pedido
        pagado del que nadie se entera es dinero cobrado sin servicio."""
        from app.tasks import notificaciones

        enviados: list[tuple[str, str, str]] = []
        monkeypatch.setattr(
            notificaciones,
            "enviar_correo",
            lambda destinatario, asunto, cuerpo_html, adjuntos=None: (
                enviados.append((destinatario, asunto, cuerpo_html)) or "ok"
            ),
        )

        email = f"aviso{uuid.uuid4().hex[:8]}@mail.ec"
        solicitud = client.post(
            "/api/v1/publico/checkout",
            json={
                "nombres": "Avisa",
                "apellidos": "Me",
                "identificacion": "1712345678",
                "telefono": "0999999999",
                "email": email,
                "plan": "EMPRENDEDOR",
                "metodo_pago": "TRANSFERENCIA",
                "acepta": {"condiciones": True, "datos": True},
            },
            headers={"X-Real-IP": "190.9.9.1"},
        ).json()

        notificaciones.aviso_solicitud(solicitud["id"])

        assert len(enviados) == 1, "el equipo no recibió el aviso"
        destinatario, asunto, cuerpo = enviados[0]
        assert "ventas@" in destinatario
        assert "Emprendedor" in asunto and "TRANSFERENCIA" in asunto
        assert email in cuerpo

        # Reintentar no manda un segundo correo
        assert notificaciones.aviso_solicitud(solicitud["id"]) == "ya-avisado"
        assert len(enviados) == 1

        admin_db.expire_all()
        fila = admin_db.get(SolicitudContacto, uuid.UUID(solicitud["id"]))
        assert fila.avisado_at is not None

    def test_el_aviso_escapa_lo_que_escribe_el_visitante(self, client, monkeypatch):
        """El nombre lo escribe un desconocido: no puede inyectar HTML en el
        correo que lee el equipo."""
        from app.tasks import notificaciones

        cuerpos: list[str] = []
        monkeypatch.setattr(
            notificaciones,
            "enviar_correo",
            lambda d, a, cuerpo_html, adjuntos=None: cuerpos.append(cuerpo_html) or "ok",
        )
        solicitud = client.post(
            "/api/v1/publico/contacto",
            json={
                "nombre": "<img src=x onerror=alert(1)>",
                "email": f"xss{uuid.uuid4().hex[:8]}@mail.ec",
                "mensaje": "<script>robar()</script>",
            },
            headers={"X-Real-IP": "190.9.9.2"},
        ).json()

        notificaciones.aviso_solicitud(solicitud["id"])
        assert cuerpos, "no salió el aviso"
        # Lo que escribió el visitante llega como TEXTO: ni una etiqueta suya
        # abre. "onerror=" puede seguir ahí, pero dentro de &lt;img…&gt; es inerte.
        assert "<script>" not in cuerpos[0]
        assert "<img" not in cuerpos[0]
        assert "&lt;script&gt;robar()&lt;/script&gt;" in cuerpos[0]
        assert "&lt;img src=x onerror=alert(1)&gt;" in cuerpos[0]

    def test_solicitudes_solo_las_ve_el_equipo(self, client, ana_tokens):
        """La bandeja de la landing lleva datos personales de gente que todavía
        no es cliente: un inquilino no puede asomarse."""
        r = client.get("/api/v1/sa/solicitudes", headers=auth_headers(ana_tokens["access_token"]))
        assert r.status_code == 403

    def test_config_publica_no_filtra_secretos(self, client):
        """La landing necesita dominio y cuentas; nada más puede salir de aquí."""
        datos = client.get("/api/v1/publico/config").json()
        assert datos["email"].endswith(datos["dominio"])
        assert datos["cobro"]["cuentas"], "sin cuentas no se puede transferir"
        crudo = json.dumps(datos).lower()
        for prohibido in ("secret", "token", "password", "dsn", "key"):
            assert prohibido not in crudo, f"la config pública expone «{prohibido}»"
