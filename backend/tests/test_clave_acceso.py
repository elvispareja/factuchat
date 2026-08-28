"""Clave de acceso de 49 dígitos y dígito verificador módulo 11 (fase 2.1)."""

from datetime import date

import pytest

from app.sri.clave import digito_verificador_mod11, generar_clave_acceso


class TestDigitoVerificador:
    def test_vector_conocido(self):
        # Verificación manual: pesos 2..7 desde la derecha
        # "41261533" → 3*2+3*3+5*4+1*5+6*6+2*7+1*2+4*3 = 104; 11-(104%11)=6
        assert digito_verificador_mod11("41261533") == 6

    def test_casos_especiales_11_y_10(self):
        # "62": 2*2+6*3 = 22 → 22%11=0 → 11-0=11 → dígito 0
        assert digito_verificador_mod11("62") == 0
        # "23": 3*2+2*3 = 12 → 12%11=1 → 11-1=10 → dígito 1
        assert digito_verificador_mod11("23") == 1

    def test_solo_digitos(self):
        with pytest.raises(ValueError):
            digito_verificador_mod11("12a4")


class TestClaveAcceso:
    def test_estructura_49_digitos(self):
        clave = generar_clave_acceso(
            fecha_emision=date(2026, 8, 24),
            codigo_documento="01",
            ruc="1790012345001",
            ambiente="1",
            establecimiento="1",
            punto_emision="1",
            secuencial=123,
            codigo_numerico="12345678",
        )
        assert len(clave) == 49
        assert clave.isdigit()
        assert clave.startswith("24082026")  # ddmmaaaa
        assert clave[8:10] == "01"  # tipo factura
        assert clave[10:23] == "1790012345001"
        assert clave[23] == "1"  # ambiente pruebas
        assert clave[24:30] == "001001"  # serie con relleno
        assert clave[30:39] == "000000123"
        assert clave[39:47] == "12345678"
        assert clave[47] == "1"  # emisión normal
        # dígito verificador consistente
        assert clave[48] == str(digito_verificador_mod11(clave[:48]))

    def test_clave_reproducible_y_variable(self):
        args = {
            "fecha_emision": date(2026, 8, 24),
            "codigo_documento": "01",
            "ruc": "1790012345001",
            "ambiente": "1",
            "establecimiento": "001",
            "punto_emision": "001",
            "secuencial": 1,
        }
        c1 = generar_clave_acceso(**args, codigo_numerico="00000001")
        c2 = generar_clave_acceso(**args, codigo_numerico="00000001")
        assert c1 == c2  # determinista con el mismo código numérico

        # Sin código numérico se sortea uno nuevo cada vez: sobre 20 claves,
        # que TODAS coincidan es imposible salvo que el sorteo esté roto.
        aleatorias = {generar_clave_acceso(**args)[39:47] for _ in range(20)}
        assert len(aleatorias) > 1
        for codigo in aleatorias:
            assert codigo.isdigit() and len(codigo) == 8

    def test_valida_entradas(self):
        with pytest.raises(ValueError):
            generar_clave_acceso(date(2026, 1, 1), "01", "123", "1", "001", "001", 1)
        with pytest.raises(ValueError):
            generar_clave_acceso(date(2026, 1, 1), "01", "1790012345001", "9", "001", "001", 1)
