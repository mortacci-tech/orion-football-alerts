import io
import ssl
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from urllib.error import URLError
from unittest.mock import patch

from orion_football import futebol


class FakeResponse:
    def __init__(self, content_type='application/pdf', url='https://stcbfsiteprdimgbrs.blob.core.windows.net/tabela.pdf'):
        self.headers = Message()
        self.headers['Content-Type'] = content_type
        self.status = 200
        self.url = url

    def geturl(self):
        return self.url


class FakePage:
    def extract_text(self):
        return 'texto PDF de teste'


class CbfFallbackTests(unittest.TestCase):
    def config(self):
        config = futebol.load_config()
        config['source']['document_url'] = futebol.REAL_DOCUMENT_DEFAULT
        return config

    def successful_pdf(self):
        return b'%PDF-1.7 fake', FakeResponse()

    def fetch_with_article_failure(self, article_failure):
        config = self.config()
        calls = []
        pdf = self.successful_pdf()

        def download(url, _config, accept):
            calls.append((url, accept))
            if len(calls) == 1:
                if isinstance(article_failure, Exception):
                    raise article_failure
                return article_failure, FakeResponse('text/html'), 200
            return pdf[0], pdf[1], 200

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(futebol, 'RAW_DIR', Path(directory)), patch.object(futebol, '_download', side_effect=download), patch('pypdf.PdfReader') as reader:
                reader.return_value.pages = [FakePage()]
                snapshot = futebol.fetch_real(config)
        return snapshot, calls

    def test_ssl_article_falls_back_to_configured_pdf(self):
        snapshot, calls = self.fetch_with_article_failure(URLError(ssl.SSLCertVerificationError('certificate verify failed')))
        self.assertEqual(calls[1], (futebol.REAL_DOCUMENT_DEFAULT, 'application/pdf'))
        self.assertIn('certificate verify failed', snapshot.article_fallback_reason)

    def test_timeout_article_falls_back_to_configured_pdf(self):
        snapshot, calls = self.fetch_with_article_failure(TimeoutError('article timeout'))
        self.assertEqual(calls[1][0], futebol.REAL_DOCUMENT_DEFAULT)
        self.assertIn('article timeout', snapshot.article_fallback_reason)

    def test_invalid_article_mime_falls_back(self):
        snapshot, calls = self.fetch_with_article_failure(futebol.FutebolError('Tipo de conteúdo inesperado no artigo CBF: application/pdf.'))
        self.assertEqual(calls[0][1], 'text/html')
        self.assertEqual(calls[1][1], 'application/pdf')
        self.assertEqual(snapshot.source_format, 'pdf')

    def test_article_without_pdf_falls_back(self):
        snapshot, _ = self.fetch_with_article_failure(b'<html>sem link PDF</html>')
        self.assertIn('não contém link PDF', snapshot.article_fallback_reason)

    def test_normalized_result_records_article_fallback(self):
        config = self.config()
        snapshot = futebol.SourceSnapshot(
            'CBF', futebol.REAL_DOCUMENT_DEFAULT, 'real', futebol.now_iso(config['timezone']),
            futebol.FIXTURE_PATH.read_text(encoding='utf-8'), None, article_fallback_reason='SSL do artigo falhou'
        )
        data = futebol.normalize_snapshot(config, snapshot)
        self.assertEqual(data['source']['article_discovery'], 'failed; configured official document_url used')
        self.assertEqual(data['source']['article_failure_reason'], 'SSL do artigo falhou')

    def test_article_and_pdf_fail_have_combined_error(self):
        config = self.config()
        with patch.object(futebol, '_download', side_effect=[URLError('SSL failure'), futebol.FutebolError('HTTP 503')]):
            with self.assertRaisesRegex(futebol.FutebolError, 'Falha no artigo.*SSL failure.*document_url oficial.*HTTP 503'):
                futebol.fetch_real(config)

    def test_fallback_rejects_unapproved_host(self):
        config = self.config()
        config['source']['document_url'] = 'https://example.com/tabela.pdf'
        with patch.object(futebol, '_download') as download:
            with self.assertRaises(futebol.FutebolError):
                futebol.fetch_real(config)
        download.assert_not_called()

    def test_fallback_validates_mime_and_pdf_signature(self):
        config = self.config()
        with patch.object(futebol, '_download', side_effect=[URLError('SSL failure'), (b'not pdf', FakeResponse('text/html'), 200)]):
            with self.assertRaisesRegex(futebol.FutebolError, 'document_url oficial.*não é PDF'):
                futebol.fetch_real(config)

    def test_no_insecure_ssl_escape_hatch_exists(self):
        source = Path(futebol.__file__).read_text(encoding='utf-8')
        self.assertNotIn('verify=False', source)
        self.assertNotIn('_create_unverified_context', source)

    def test_preview_real_does_not_access_network(self):
        config = self.config()
        source = futebol.SourceSnapshot('CBF', futebol.REAL_DOCUMENT_DEFAULT, 'real', futebol.now_iso(config['timezone']), '', None)
        data = {'data_mode': 'real', 'timezone': config['timezone'], 'season': 2026, 'matches': [], 'source': {}}
        with patch('urllib.request.urlopen') as network:
            with self.assertRaises(futebol.FutebolError):
                futebol.render_preview(data, round_number=19)
        network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
