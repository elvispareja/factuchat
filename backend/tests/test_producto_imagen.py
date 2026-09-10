"""Las fotos del artículo: varias, subidas o tomadas, con una principal.

Antes era UNA imagen y subir otra reemplazaba la anterior. Ahora es una galería,
así que a lo que ya había que vigilar —que el tipo lo decidan los BYTES y no lo
que declare el navegador, que el nombre que manda el cliente no toque el sistema
de archivos, que borrar no deje basura en disco y que la RLS siga decidiendo de
quién es cada producto— se suma lo propio de tener varias: que convivan sin
pisarse, que la principal sea siempre exactamente una, y que borrarla ascienda a
la siguiente en vez de dejar al artículo sin ninguna.
"""

import random
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Producto, ProductoImagen
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


def _rutas_en_disco(admin_db, producto_id: str) -> list[str]:
    admin_db.expire_all()
    return list(
        admin_db.scalars(
            select(ProductoImagen.ruta)
            .where(ProductoImagen.producto_id == producto_id)
            .order_by(ProductoImagen.orden)
        ).all()
    )


def _subir(client, headers, producto_id, contenido, nombre="foto.png", tipo="image/png"):
    return client.post(
        f"/api/v1/productos/{producto_id}/imagenes",
        files={"archivo": (nombre, contenido, tipo)},
        headers=headers,
    )


def _listar(client, headers, producto_id):
    return client.get(f"/api/v1/productos/{producto_id}/imagenes", headers=headers)


class TestCaminoFeliz:
    def test_subir_y_recuperar(self, client, ana_tokens, producto, admin_db):
        headers = auth_headers(ana_tokens["access_token"])
        assert producto["tiene_imagen"] is False

        r = _subir(client, headers, producto["id"], PNG_1X1)
        assert r.status_code == 201, r.text
        foto = r.json()
        assert foto["orden"] == 0
        # La ruta del disco NO sale hacia el navegador
        assert "ruta" not in foto and "imagen_path" not in foto

        r = client.get(f"/api/v1/productos/{producto['id']}/imagenes/{foto['id']}", headers=headers)
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content == PNG_1X1

        # Guardada bajo el directorio del tenant, con nombre nuestro
        ruta = Path(_rutas_en_disco(admin_db, producto["id"])[0])
        assert ruta.parent == Path(get_settings().storage_dir) / str(TENANT_A) / "productos"
        assert ruta.suffix == ".png"

    def test_el_listado_dice_si_hay_imagen(self, client, ana_tokens, producto):
        headers = auth_headers(ana_tokens["access_token"])
        assert _subir(client, headers, producto["id"], JPEG_MINIMO).status_code == 201

        r = client.get("/api/v1/productos", headers=headers)
        assert r.status_code == 200
        assert {p["id"]: p["tiene_imagen"] for p in r.json()}[producto["id"]] is True

    def test_sin_fotos_la_principal_devuelve_404(self, client, ana_tokens, producto):
        headers = auth_headers(ana_tokens["access_token"])
        assert (
            client.get(f"/api/v1/productos/{producto['id']}/imagen", headers=headers).status_code
            == 404
        )
        assert _listar(client, headers, producto["id"]).json() == []

    def test_borrar_quita_el_archivo_y_la_fila(self, client, ana_tokens, producto, admin_db):
        headers = auth_headers(ana_tokens["access_token"])
        foto = _subir(client, headers, producto["id"], PNG_1X1).json()
        ruta = Path(_rutas_en_disco(admin_db, producto["id"])[0])

        r = client.delete(
            f"/api/v1/productos/{producto['id']}/imagenes/{foto['id']}", headers=headers
        )
        assert r.status_code == 204
        assert not ruta.exists()  # si no, cada borrado deja basura para siempre
        assert _rutas_en_disco(admin_db, producto["id"]) == []


class TestVariasFotos:
    def test_subir_otra_no_reemplaza_a_la_anterior(self, client, ana_tokens, producto):
        """Este es el cambio: antes la segunda foto se comía a la primera."""
        headers = auth_headers(ana_tokens["access_token"])
        primera = _subir(client, headers, producto["id"], PNG_1X1).json()
        segunda = _subir(client, headers, producto["id"], JPEG_MINIMO).json()

        fotos = _listar(client, headers, producto["id"]).json()
        assert [f["id"] for f in fotos] == [primera["id"], segunda["id"]]
        assert [f["orden"] for f in fotos] == [0, 1]

        # Y cada una devuelve SU archivo, no el de la otra
        for foto, contenido, tipo in (
            (primera, PNG_1X1, "image/png"),
            (segunda, JPEG_MINIMO, "image/jpeg"),
        ):
            r = client.get(
                f"/api/v1/productos/{producto['id']}/imagenes/{foto['id']}", headers=headers
            )
            assert r.content == contenido
            assert r.headers["content-type"] == tipo

    def test_la_primera_es_la_principal(self, client, ana_tokens, producto):
        headers = auth_headers(ana_tokens["access_token"])
        _subir(client, headers, producto["id"], PNG_1X1)
        _subir(client, headers, producto["id"], JPEG_MINIMO)

        r = client.get(f"/api/v1/productos/{producto['id']}/imagen", headers=headers)
        assert r.status_code == 200
        assert r.content == PNG_1X1  # la de orden 0

    def test_ascender_otra_a_principal_reordena_sin_huecos(self, client, ana_tokens, producto):
        headers = auth_headers(ana_tokens["access_token"])
        primera = _subir(client, headers, producto["id"], PNG_1X1).json()
        segunda = _subir(client, headers, producto["id"], JPEG_MINIMO).json()

        r = client.put(
            f"/api/v1/productos/{producto['id']}/imagenes/{segunda['id']}/principal",
            json={},
            headers=headers,
        )
        assert r.status_code == 200
        assert [f["id"] for f in r.json()] == [segunda["id"], primera["id"]]
        assert [f["orden"] for f in r.json()] == [0, 1]

        assert (
            client.get(f"/api/v1/productos/{producto['id']}/imagen", headers=headers).content
            == JPEG_MINIMO
        )

    def test_borrar_la_principal_asciende_a_la_siguiente(self, client, ana_tokens, producto):
        """Sin renumerar, el artículo se quedaba con su primera foto en orden 1
        y ninguna en 0: «la principal» pasaba a depender de cómo ordenara la
        consulta."""
        headers = auth_headers(ana_tokens["access_token"])
        primera = _subir(client, headers, producto["id"], PNG_1X1).json()
        _subir(client, headers, producto["id"], JPEG_MINIMO)

        client.delete(
            f"/api/v1/productos/{producto['id']}/imagenes/{primera['id']}", headers=headers
        )
        fotos = _listar(client, headers, producto["id"]).json()
        assert [f["orden"] for f in fotos] == [0]
        assert (
            client.get(f"/api/v1/productos/{producto['id']}/imagen", headers=headers).content
            == JPEG_MINIMO
        )

    def test_hay_un_tope_de_fotos(self, client, ana_tokens, producto):
        from app.api.routes.productos import MAX_IMAGENES

        headers = auth_headers(ana_tokens["access_token"])
        for _ in range(MAX_IMAGENES):
            assert _subir(client, headers, producto["id"], PNG_1X1).status_code == 201
        r = _subir(client, headers, producto["id"], PNG_1X1)
        assert r.status_code == 400
        assert str(MAX_IMAGENES) in r.json()["detail"]

    def test_borrar_dos_veces_no_es_un_error(self, client, ana_tokens, producto):
        headers = auth_headers(ana_tokens["access_token"])
        foto = _subir(client, headers, producto["id"], PNG_1X1).json()
        ruta = f"/api/v1/productos/{producto['id']}/imagenes/{foto['id']}"
        assert client.delete(ruta, headers=headers).status_code == 204
        assert client.delete(ruta, headers=headers).status_code == 204


class TestRechazos:
    def test_no_basta_con_decir_que_es_una_imagen(self, client, ana_tokens, producto, admin_db):
        """content_type y extensión los elige quien sube: mandan los bytes."""
        headers = auth_headers(ana_tokens["access_token"])
        r = _subir(
            client,
            headers,
            producto["id"],
            SVG_MALICIOSO,
            nombre="foto.png",
            tipo="image/png",
        )
        assert r.status_code == 400
        assert "JPG, PNG o WEBP" in r.json()["detail"]
        assert _rutas_en_disco(admin_db, producto["id"]) == []

    def test_demasiado_grande(self, client, ana_tokens, producto, admin_db):
        gorda = PNG_1X1 + b"\x00" * (2 * 1024 * 1024)
        r = _subir(client, auth_headers(ana_tokens["access_token"]), producto["id"], gorda)
        assert r.status_code == 400
        assert "2 MB" in r.json()["detail"]
        assert _rutas_en_disco(admin_db, producto["id"]) == []

    def test_el_filename_no_construye_la_ruta(self, client, ana_tokens, producto, admin_db):
        """«../../x.png» es un nombre de archivo válido: no puede escribir fuera."""
        headers = auth_headers(ana_tokens["access_token"])
        fuera = Path(get_settings().storage_dir).parent / "x.png"
        r = _subir(client, headers, producto["id"], PNG_1X1, nombre="../../x.png")
        assert r.status_code == 201, r.text

        ruta = Path(_rutas_en_disco(admin_db, producto["id"])[0]).resolve()
        base = (Path(get_settings().storage_dir) / str(TENANT_A) / "productos").resolve()
        assert ruta.parent == base
        assert ".." not in str(ruta)
        assert not fuera.exists()

    def test_una_foto_de_otro_producto_no_se_sirve_por_esta_ruta(
        self, client, ana_tokens, producto, admin_db
    ):
        """El id de la foto se comprueba contra el producto de la URL: si no,
        bastaría conocer un uuid para leer la foto de cualquier artículo."""
        headers = auth_headers(ana_tokens["access_token"])
        foto = _subir(client, headers, producto["id"], PNG_1X1).json()

        otro = client.post(
            "/api/v1/productos",
            json={
                "codigo": f"IMG{random.randint(100000, 999999)}",
                "nombre": f"Con foto {random.randint(1, 999999)}",
                "tipo": "BIEN",
                "precio_sin_iva": "1.00",
            },
            headers=headers,
        ).json()
        r = client.get(f"/api/v1/productos/{otro['id']}/imagenes/{foto['id']}", headers=headers)
        assert r.status_code == 404


class TestAislamiento:
    def test_producto_de_otro_tenant(self, client, ana_tokens, bob_tokens, producto, admin_db):
        """Bob no ve el producto de Ana: ni le sube fotos, ni se las lee, ni las borra."""
        de_bob = auth_headers(bob_tokens["access_token"])
        de_ana = auth_headers(ana_tokens["access_token"])

        assert _subir(client, de_bob, producto["id"], PNG_1X1).status_code == 404
        assert _rutas_en_disco(admin_db, producto["id"]) == []

        foto = _subir(client, de_ana, producto["id"], PNG_1X1).json()
        assert _listar(client, de_bob, producto["id"]).status_code == 404
        assert (
            client.get(
                f"/api/v1/productos/{producto['id']}/imagenes/{foto['id']}", headers=de_bob
            ).status_code
            == 404
        )
        assert (
            client.delete(
                f"/api/v1/productos/{producto['id']}/imagenes/{foto['id']}", headers=de_bob
            ).status_code
            == 404
        )
        assert _rutas_en_disco(admin_db, producto["id"]) != []  # nada se borró
