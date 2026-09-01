"""La imagen del producto: la miniatura del catálogo y de la tienda.

Es la primera subida de archivos que hace un usuario ya autenticado contra una
fila SUYA, así que lo que se mide no es solo el camino feliz: que el tipo se
decida por los BYTES y no por lo que declare el navegador (un .svg con script
renombrado a .jpg se serviría ejecutando JavaScript), que el nombre que manda
el cliente no toque nunca el sistema de archivos, que reemplazar no deje
basura en disco, y que la RLS siga siendo la que decide de quién es cada
producto.
"""

import random
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Producto
from tests.conftest import TENANT_A, auth_headers

# Un PNG de 1x1 de verdad (cabecera + IHDR + IDAT + IEND).
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)
JPEG_MINIMO = b"\xff\xd8\xff\xe0" + b"\x00" * 32
# Lo que de verdad se cuela si uno se fía del content_type: un SVG con script.
SVG_MALICIOSO = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


@pytest.fixture()
def producto(client, ana_tokens, admin_db):
    """Un producto del tenant A, borrado al terminar (el cupo del plan cuenta
    productos activos y dejarlos se lo come al resto de la suite)."""
    headers = auth_headers(ana_tokens["access_token"])
    r = client.post(
        "/api/v1/productos",
        json={
            "codigo": f"IMG{random.randint(100000, 999999)}",
            "nombre": f"Con foto {random.randint(1, 999999)}",
            "tipo": "BIEN",
            "precio_sin_iva": "10.00",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    yield r.json()

    admin_db.expire_all()
    for fila in admin_db.scalars(
        select(Producto).where(Producto.tenant_id == TENANT_A, Producto.nombre.like("Con foto%"))
    ).all():
        admin_db.delete(fila)
    admin_db.commit()


def _ruta_en_disco(admin_db, producto_id: str) -> str | None:
    admin_db.expire_all()
    return admin_db.scalars(select(Producto.imagen_path).where(Producto.id == producto_id)).first()


def _subir(client, headers, producto_id, contenido, nombre="foto.png", tipo="image/png"):
    return client.post(
        f"/api/v1/productos/{producto_id}/imagen",
        files={"archivo": (nombre, contenido, tipo)},
        headers=headers,
    )


class TestCaminoFeliz:
    def test_subir_y_recuperar(self, client, ana_tokens, producto, admin_db):
        headers = auth_headers(ana_tokens["access_token"])
        assert producto["tiene_imagen"] is False

        r = _subir(client, headers, producto["id"], PNG_1X1)
        assert r.status_code == 200, r.text
        assert r.json()["tiene_imagen"] is True
        # La ruta del disco NO sale hacia el navegador
        assert "imagen_path" not in r.json()

        r = client.get(f"/api/v1/productos/{producto['id']}/imagen", headers=headers)
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content == PNG_1X1

        # Guardado bajo el directorio del tenant, con nombre nuestro
        ruta = Path(_ruta_en_disco(admin_db, producto["id"]))
        assert ruta.parent == Path(get_settings().storage_dir) / str(TENANT_A) / "productos"
        assert ruta.suffix == ".png"

    def test_el_listado_y_la_tienda_dicen_si_hay_imagen(self, client, ana_tokens, producto):
        headers = auth_headers(ana_tokens["access_token"])
        assert _subir(client, headers, producto["id"], JPEG_MINIMO).status_code == 200

        r = client.get("/api/v1/productos", headers=headers)
        assert r.status_code == 200
        assert {p["id"]: p["tiene_imagen"] for p in r.json()}[producto["id"]] is True

    def test_sin_imagen_devuelve_404(self, client, ana_tokens, producto):
        r = client.get(
            f"/api/v1/productos/{producto['id']}/imagen",
            headers=auth_headers(ana_tokens["access_token"]),
        )
        assert r.status_code == 404

    def test_borrar_quita_el_archivo_y_la_marca(self, client, ana_tokens, producto, admin_db):
        headers = auth_headers(ana_tokens["access_token"])
        assert _subir(client, headers, producto["id"], PNG_1X1).status_code == 200
        ruta = Path(_ruta_en_disco(admin_db, producto["id"]))

        r = client.delete(f"/api/v1/productos/{producto['id']}/imagen", headers=headers)
        assert r.status_code == 204
        assert not ruta.exists()
        assert _ruta_en_disco(admin_db, producto["id"]) is None
        assert (
            client.get(f"/api/v1/productos/{producto['id']}/imagen", headers=headers).status_code
            == 404
        )


class TestRechazos:
    def test_no_basta_con_decir_que_es_una_imagen(self, client, ana_tokens, producto, admin_db):
        """content_type y extensión los elige quien sube: mandan los bytes."""
        r = _subir(
            client,
            headers := auth_headers(ana_tokens["access_token"]),
            producto["id"],
            SVG_MALICIOSO,
            nombre="foto.png",
            tipo="image/png",
        )
        assert r.status_code == 400
        assert "JPG, PNG o WEBP" in r.json()["detail"]
        assert _ruta_en_disco(admin_db, producto["id"]) is None
        assert (
            client.get(f"/api/v1/productos/{producto['id']}/imagen", headers=headers).status_code
            == 404
        )

    def test_demasiado_grande(self, client, ana_tokens, producto, admin_db):
        gorda = PNG_1X1 + b"\x00" * (2 * 1024 * 1024)
        r = _subir(client, auth_headers(ana_tokens["access_token"]), producto["id"], gorda)
        assert r.status_code == 400
        assert "2 MB" in r.json()["detail"]
        assert _ruta_en_disco(admin_db, producto["id"]) is None

    def test_el_filename_no_construye_la_ruta(self, client, ana_tokens, producto, admin_db):
        """«../../x.png» es un nombre de archivo válido: no puede escribir fuera."""
        headers = auth_headers(ana_tokens["access_token"])
        fuera = Path(get_settings().storage_dir).parent / "x.png"
        r = _subir(client, headers, producto["id"], PNG_1X1, nombre="../../x.png")
        assert r.status_code == 200, r.text

        ruta = Path(_ruta_en_disco(admin_db, producto["id"])).resolve()
        base = (Path(get_settings().storage_dir) / str(TENANT_A) / "productos").resolve()
        assert ruta.parent == base
        assert ".." not in str(ruta)
        assert not fuera.exists()


class TestReemplazo:
    def test_reemplazar_borra_la_anterior(self, client, ana_tokens, producto, admin_db):
        headers = auth_headers(ana_tokens["access_token"])
        assert _subir(client, headers, producto["id"], PNG_1X1).status_code == 200
        vieja = Path(_ruta_en_disco(admin_db, producto["id"]))
        assert vieja.exists()

        assert _subir(client, headers, producto["id"], JPEG_MINIMO).status_code == 200
        nueva = Path(_ruta_en_disco(admin_db, producto["id"]))
        assert nueva != vieja
        assert nueva.exists()
        assert not vieja.exists()  # si no, cada reemplazo deja basura para siempre

        r = client.get(f"/api/v1/productos/{producto['id']}/imagen", headers=headers)
        assert r.headers["content-type"] == "image/jpeg"
        assert r.content == JPEG_MINIMO


class TestAislamiento:
    def test_producto_de_otro_tenant(self, client, ana_tokens, bob_tokens, producto, admin_db):
        """Bob no ve el producto de Ana: ni le sube imagen, ni se la lee, ni la borra."""
        de_bob = auth_headers(bob_tokens["access_token"])
        assert _subir(client, de_bob, producto["id"], PNG_1X1).status_code == 404
        assert _ruta_en_disco(admin_db, producto["id"]) is None

        # Y con imagen puesta por su dueña, sigue sin existir para Bob
        assert (
            _subir(
                client, auth_headers(ana_tokens["access_token"]), producto["id"], PNG_1X1
            ).status_code
            == 200
        )
        assert (
            client.get(f"/api/v1/productos/{producto['id']}/imagen", headers=de_bob).status_code
            == 404
        )
        assert (
            client.delete(f"/api/v1/productos/{producto['id']}/imagen", headers=de_bob).status_code
            == 404
        )
        assert _ruta_en_disco(admin_db, producto["id"]) is not None  # nada se borró
