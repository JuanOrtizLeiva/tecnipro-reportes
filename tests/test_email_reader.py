"""Tests para el lector de emails IMAP."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from src.ingest.email_reader import (
    descargar_adjuntos_moodle,
    _decodificar_header,
    _es_adjunto_moodle,
    _obtener_nombre_adjunto,
    _guardar_adjunto,
)


class TestDecodificarHeader:
    """Tests para decodificación de headers MIME."""

    def test_header_simple(self):
        """Header simple sin codificación."""
        resultado = _decodificar_header("Test Subject")
        assert resultado == "Test Subject"

    def test_header_vacio(self):
        """Header vacío."""
        resultado = _decodificar_header("")
        assert resultado == ""

    def test_header_none(self):
        """Header None."""
        resultado = _decodificar_header(None)
        assert resultado == ""


class TestEsAdjuntoMoodle:
    """Tests para detección de adjuntos."""

    def test_con_disposition_attachment(self):
        """Part con Content-Disposition: attachment."""
        part = Mock()
        part.get.return_value = "attachment; filename=test.csv"
        part.get_filename.return_value = "test.csv"

        assert _es_adjunto_moodle(part) is True

    def test_con_filename_sin_disposition(self):
        """Part con filename pero sin disposition."""
        part = Mock()
        part.get.return_value = ""
        part.get_filename.return_value = "test.csv"

        assert _es_adjunto_moodle(part) is False

    def test_sin_disposition_ni_filename(self):
        """Part sin disposition ni filename."""
        part = Mock()
        part.get.return_value = ""
        part.get_filename.return_value = None

        assert _es_adjunto_moodle(part) is False


class TestObtenerNombreAdjunto:
    """Tests para obtención de nombre de adjunto."""

    def test_filename_simple(self):
        """Filename simple."""
        part = Mock()
        part.get_filename.return_value = "Greporte.csv"

        resultado = _obtener_nombre_adjunto(part)
        assert resultado == "Greporte.csv"

    def test_sin_filename(self):
        """Part sin filename."""
        part = Mock()
        part.get_filename.return_value = None

        resultado = _obtener_nombre_adjunto(part)
        assert resultado is None


class TestGuardarAdjunto:
    """Tests para guardado de adjuntos."""

    @patch("src.ingest.email_reader.settings")
    def test_guardar_greporte(self, mock_settings, tmp_path):
        """Guarda Greporte.csv correctamente."""
        mock_settings.DATA_INPUT_PATH = tmp_path

        part = Mock()
        part.get_payload.return_value = b"test,data\n1,2"

        archivos_encontrados = {"Greporte.csv": False, "Dreporte.csv": False}
        _guardar_adjunto(part, "Greporte.csv", archivos_encontrados)

        # Verificar que se guardó
        assert (tmp_path / "Greporte.csv").exists()
        assert archivos_encontrados["Greporte.csv"] is True

        # Verificar contenido
        contenido = (tmp_path / "Greporte.csv").read_bytes()
        assert contenido == b"test,data\n1,2"

    @patch("src.ingest.email_reader.settings")
    def test_guardar_dreporte(self, mock_settings, tmp_path):
        """Guarda Dreporte.csv correctamente."""
        mock_settings.DATA_INPUT_PATH = tmp_path

        part = Mock()
        part.get_payload.return_value = b"student,name\n1,Juan"

        archivos_encontrados = {"Greporte.csv": False, "Dreporte.csv": False}
        _guardar_adjunto(part, "Dreporte.csv", archivos_encontrados)

        # Verificar que se guardó
        assert (tmp_path / "Dreporte.csv").exists()
        assert archivos_encontrados["Dreporte.csv"] is True

    @patch("src.ingest.email_reader.settings")
    def test_ignorar_otros_archivos(self, mock_settings, tmp_path):
        """Ignora archivos que no son G/Dreporte."""
        mock_settings.DATA_INPUT_PATH = tmp_path

        part = Mock()
        part.get_payload.return_value = b"data"

        archivos_encontrados = {"Greporte.csv": False, "Dreporte.csv": False}
        _guardar_adjunto(part, "otro_archivo.csv", archivos_encontrados)

        # No debe guardar nada
        assert not (tmp_path / "otro_archivo.csv").exists()
        assert archivos_encontrados["Greporte.csv"] is False


class TestDescargarAdjuntosMoodle:
    """Tests de integración para descarga de emails."""

    @patch("src.ingest.email_reader.settings")
    @patch("src.ingest.email_reader.imaplib.IMAP4_SSL")
    def test_sin_credenciales(self, mock_imap, mock_settings):
        """Error si no hay credenciales configuradas."""
        mock_settings.EMAIL_MOODLE_USER = ""
        mock_settings.EMAIL_MOODLE_PASSWORD = ""

        with pytest.raises(RuntimeError, match="Credenciales de email no configuradas"):
            descargar_adjuntos_moodle()

    @patch("src.ingest.email_reader.settings")
    @patch("src.ingest.email_reader.imaplib.IMAP4_SSL")
    def test_sin_emails_nuevos(self, mock_imap, mock_settings):
        """Retorna OK si no hay emails nuevos."""
        mock_settings.EMAIL_MOODLE_USER = "test@gmail.com"
        mock_settings.EMAIL_MOODLE_PASSWORD = "password"
        mock_settings.IMAP_SERVER = "imap.gmail.com"

        # Mock conexión IMAP
        mock_mail = MagicMock()
        mock_imap.return_value = mock_mail
        mock_mail.search.return_value = ("OK", [b""])

        resultado = descargar_adjuntos_moodle()

        assert resultado["status"] == "OK"
        assert resultado["emails_procesados"] == 0
        assert len(resultado["archivos_descargados"]) == 0

    @patch("src.ingest.email_reader.settings")
    @patch("src.ingest.email_reader.imaplib.IMAP4_SSL")
    def test_error_imap(self, mock_imap, mock_settings):
        """Error de conexión IMAP."""
        mock_settings.EMAIL_MOODLE_USER = "test@gmail.com"
        mock_settings.EMAIL_MOODLE_PASSWORD = "wrong_password"
        mock_settings.IMAP_SERVER = "imap.gmail.com"

        # Mock error de login
        mock_imap.side_effect = Exception("Authentication failed")

        with pytest.raises(RuntimeError, match="Error procesando emails"):
            descargar_adjuntos_moodle()
