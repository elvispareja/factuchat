"""Firma XAdES-BES de comprobantes con el certificado .p12 del tenant (fase 2.2).

El .p12 y su contraseña llegan cifrados (AES-256-GCM, clave maestra del entorno)
y se descifran SOLO aquí, en memoria, en el momento de firmar. Ni el archivo ni
la contraseña ni las claves privadas se registran jamás en logs (checklist F2).
"""

from base64 import b64encode
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree
from lxml.etree import SubElement
from signxml import CanonicalizationMethod, DigestAlgorithm, SignatureMethod, methods
from signxml.util import add_pem_header
from signxml.xades import XAdESDataObjectFormat, XAdESSigner, XAdESVerifier
from signxml.xades.xades import ds_tag, xades_tag

from app.core.config import get_settings
from app.core.crypto import aesgcm_decrypt

AAD_P12 = b"factuchat:p12"
AAD_P12_PASSWORD = b"factuchat:p12-password"


class FirmaError(Exception):
    """Error de firma con mensaje apto para el usuario (sin datos sensibles)."""


def cargar_p12(p12_bytes: bytes, password: str) -> tuple[Any, Any, list[Any]]:
    """Devuelve (clave_privada, certificado, cadena). Lanza FirmaError si no abre."""
    try:
        key, cert, chain = pkcs12.load_key_and_certificates(p12_bytes, password.encode())
    except Exception as e:  # contraseña incorrecta o archivo corrupto
        raise FirmaError("No se pudo abrir el certificado: revise el archivo y su clave") from e
    if key is None or cert is None:
        raise FirmaError("El certificado no contiene una clave privada")
    return key, cert, list(chain or [])


def metadata_certificado(p12_bytes: bytes, password: str) -> dict[str, Any]:
    """Extrae datos NO sensibles del certificado para mostrarlos en el panel."""
    _key, cert, _chain = cargar_p12(p12_bytes, password)
    cn = cert.subject.rfc4514_string()
    issuer = cert.issuer.rfc4514_string()
    # serialNumber del subject (OID 2.5.4.5): las CA ecuatorianas publican ahí
    # la cédula/RUC del titular. No confundir con el número de serie del cert.
    serial_subject = ""
    atributos = cert.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER)
    if atributos:
        serial_subject = str(atributos[0].value)
    return {
        "subject_cn": cn[:300],
        "issuer_cn": issuer[:300],
        "serial": str(cert.serial_number),
        "serial_number_subject": serial_subject[:100],
        "valido_desde": cert.not_valid_before_utc,
        "valido_hasta": cert.not_valid_after_utc,
    }


def descifrar_p12(p12_data_enc: str, p12_password_enc: str) -> tuple[bytes, str]:
    s = get_settings()
    p12 = aesgcm_decrypt(s.cert_enc_key, p12_data_enc, AAD_P12, "CERT_ENC_KEY")
    password = aesgcm_decrypt(
        s.cert_enc_key, p12_password_enc, AAD_P12_PASSWORD, "CERT_ENC_KEY"
    ).decode()
    return p12, password


class _FirmanteSRI(XAdESSigner):
    """XAdES-BES como lo espera el validador del SRI: SigningCertificate
    clásico (CertDigest SHA-1 + IssuerSerial), no SigningCertificateV2."""

    def add_signing_certificate(self, signed_signature_properties, sig_root, signing_settings):
        assert signing_settings.cert_chain is not None
        signing_cert = SubElement(
            signed_signature_properties, xades_tag("SigningCertificate"), nsmap=self.namespaces
        )
        for cert in signing_settings.cert_chain:
            if isinstance(cert, x509.Certificate):
                loaded = cert
            else:
                loaded = x509.load_pem_x509_certificate(add_pem_header(cert))
            der = loaded.public_bytes(Encoding.DER)
            sha1 = self._get_digest(der, algorithm=DigestAlgorithm.SHA1)

            cert_node = SubElement(signing_cert, xades_tag("Cert"), nsmap=self.namespaces)
            cert_digest = SubElement(cert_node, xades_tag("CertDigest"), nsmap=self.namespaces)
            SubElement(
                cert_digest,
                ds_tag("DigestMethod"),
                nsmap=self.namespaces,
                Algorithm=DigestAlgorithm.SHA1.value,
            )
            digest_value = SubElement(cert_digest, ds_tag("DigestValue"), nsmap=self.namespaces)
            digest_value.text = b64encode(sha1).decode()

            issuer_serial = SubElement(cert_node, xades_tag("IssuerSerial"), nsmap=self.namespaces)
            issuer_name = SubElement(issuer_serial, ds_tag("X509IssuerName"), nsmap=self.namespaces)
            issuer_name.text = loaded.issuer.rfc4514_string()
            serial = SubElement(issuer_serial, ds_tag("X509SerialNumber"), nsmap=self.namespaces)
            serial.text = str(loaded.serial_number)


def firmar_comprobante(xml_bytes: bytes, p12_bytes: bytes, password: str) -> bytes:
    """Firma XAdES-BES enveloped sobre el elemento id="comprobante"."""
    key, cert, chain = cargar_p12(p12_bytes, password)
    doc = etree.fromstring(xml_bytes)

    signer = _FirmanteSRI(
        data_object_format=XAdESDataObjectFormat(
            Description="Comprobante electrónico SRI", MimeType="text/xml"
        ),
        method=methods.enveloped,
        signature_algorithm=SignatureMethod.RSA_SHA256,
        digest_algorithm=DigestAlgorithm.SHA256,
        # OBLIGATORIO: el validador del SRI (MITyCLibXAdES) solo reconoce
        # Canonical XML 1.0 inclusiva. signxml usa c14n 1.1 por defecto, que el
        # SRI rechaza con "firma inválida" en TODOS los comprobantes.
        c14n_algorithm=CanonicalizationMethod.CANONICAL_XML_1_0,
    )
    signed = signer.sign(
        doc,
        key=key,
        cert=[cert, *chain],
        reference_uri="#comprobante",
        id_attribute="id",
    )
    return etree.tostring(signed, xml_declaration=True, encoding="UTF-8")


def verificar_firma(xml_firmado: bytes, cert_pem: str | None = None) -> None:
    """Verificación local de la firma (tests y diagnóstico). Lanza si es inválida.

    Con cert_pem se valida contra ese certificado explícito (necesario para
    certificados de prueba autofirmados)."""
    doc = etree.fromstring(xml_firmado)
    verifier = XAdESVerifier()
    verifier.verify(
        doc,
        require_x509=True,
        x509_cert=cert_pem,
        expect_references=3,  # comprobante + SignedProperties + KeyInfo
    )


def huella_sha256(data: bytes) -> str:
    digest = hashes.Hash(hashes.SHA256())
    digest.update(data)
    return digest.finalize().hex()
