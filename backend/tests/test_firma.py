"""Firma XAdES-BES (fase 2.2): firma válida y verificable, estructura XAdES,
y manejo de errores sin filtrar secretos."""

from decimal import Decimal

import pytest
from lxml import etree

from app.sri.firma import FirmaError, firmar_comprobante, metadata_certificado, verificar_firma
from app.sri.xml_builder import construir_factura
from tests.sri_utils import generar_p12_prueba
from tests.test_xml_builder import BASE_DOC, COMPRADOR, EMISOR, ITEM, TOTALES

NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS_XADES = "http://uri.etsi.org/01903/v1.3.2#"


@pytest.fixture(scope="module")
def p12():
    return generar_p12_prueba()


@pytest.fixture(scope="module")
def xml_factura() -> bytes:
    return construir_factura(
        EMISOR,
        {
            **BASE_DOC,
            "comprador": COMPRADOR,
            "items": [ITEM],
            "totales": TOTALES,
            "pagos": [{"forma": "01", "total": Decimal("23.00")}],
        },
    )


class TestFirma:
    def test_firma_y_verifica(self, p12, xml_factura):
        p12_bytes, password, cert_pem = p12
        firmado = firmar_comprobante(xml_factura, p12_bytes, password)

        root = etree.fromstring(firmado)
        assert root.tag == "factura"  # enveloped: la firma vive DENTRO del comprobante
        firmas = root.findall(f"{{{NS_DS}}}Signature")
        assert len(firmas) == 1

        # Estructura XAdES-BES: SignedProperties con SigningTime y SigningCertificate
        # CLÁSICO (v1, digest SHA-1 + IssuerSerial) como exige el validador del SRI
        sp = firmas[0].find(f".//{{{NS_XADES}}}SignedProperties")
        assert sp is not None
        assert sp.find(f".//{{{NS_XADES}}}SigningCertificate") is not None
        assert sp.find(f".//{{{NS_XADES}}}SigningCertificateV2") is None
        assert sp.find(f".//{{{NS_XADES}}}SigningTime") is not None
        cert_digest = sp.find(f".//{{{NS_XADES}}}SigningCertificate//{{{NS_DS}}}DigestMethod")
        assert cert_digest.get("Algorithm").endswith("sha1")

        # La referencia principal apunta al comprobante
        uris = [r.get("URI") for r in firmas[0].findall(f".//{{{NS_DS}}}Reference")]
        assert "#comprobante" in uris

        # CANONICALIZACIÓN: el validador del SRI solo acepta Canonical XML 1.0
        # inclusiva. signxml usa c14n 1.1 por defecto y el SRI la rechaza.
        c14n_sri = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
        c14n = firmas[0].find(f".//{{{NS_DS}}}CanonicalizationMethod")
        assert c14n.get("Algorithm") == c14n_sri
        transforms = [t.get("Algorithm") for t in firmas[0].findall(f".//{{{NS_DS}}}Transform")]
        assert "http://www.w3.org/2006/12/xml-c14n11" not in transforms
        assert c14n_sri in transforms

        # Verificación criptográfica local
        verificar_firma(firmado, cert_pem)

    def test_firma_alterada_no_verifica(self, p12, xml_factura):
        p12_bytes, password, cert_pem = p12
        from signxml.exceptions import InvalidDigest, InvalidSignature

        firmado = firmar_comprobante(xml_factura, p12_bytes, password)
        alterado = firmado.replace(b"Juana", b"Julia")
        with pytest.raises((InvalidDigest, InvalidSignature)):
            verificar_firma(alterado, cert_pem)

    def test_password_incorrecta_mensaje_limpio(self, p12, xml_factura):
        p12_bytes, _password, _pem = p12
        with pytest.raises(FirmaError) as exc:
            firmar_comprobante(xml_factura, p12_bytes, "otra-clave")
        assert "clave" in str(exc.value).lower()
        assert "otra-clave" not in str(exc.value)  # el secreto no viaja en el error

    def test_metadata_sin_datos_sensibles(self, p12):
        p12_bytes, password, _pem = p12
        meta = metadata_certificado(p12_bytes, password)
        assert "FIRMA DE PRUEBAS FACTUCHAT" in meta["subject_cn"]
        assert meta["valido_hasta"] > meta["valido_desde"]
        assert password not in str(meta)
