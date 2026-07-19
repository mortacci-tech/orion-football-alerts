import copy
import io
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
from orion_football import futebol

class FutebolTests(unittest.TestCase):
    def data(self):
        c=futebol.load_config(); return c, futebol.normalize_snapshot(c, futebol.fetch_fixture(c))
    def test_fixture_normalizada(self):
        _,d=self.data(); self.assertEqual(d["data_mode"],"fixture"); self.assertEqual({m["round"] for m in d["matches"]},{19,20})
    def test_time_e_timezone(self):
        _,d=self.data(); self.assertTrue(datetime.fromisoformat(d["matches"][0]["kickoff"]).tzinfo)
    def test_duplicidade_falha(self):
        c,d=self.data(); html=futebol.FIXTURE_PATH.read_text(); row='<tr><td>Ref: 181 Rodada: 19</td><td>x</td><td>Botafogo x Santos</td><td>Data: 16/07/2026 - quinta-feira às 19h30 Local: Nilton Santos - Rio de Janeiro - RJ</td><td>Transmissão: SporTV / Premiere</td></tr>'; s=futebol.SourceSnapshot("CBF","fixture","fixture",futebol.now_iso(c["timezone"]),html.replace("</tbody>",row+"</tbody>"),None)
        with self.assertRaisesRegex(futebol.FutebolError, 'duplicada'):
            futebol.normalize_snapshot(c,s)
    def test_preview_owner(self):
        c,d=self.data(); p=futebol.render_preview(d,round_number=19); self.assertIn("JOGO DO FLAMENGO",p); self.assertIn("São Paulo x Flamengo",p)
    def test_alerta_idempotente(self):
        c,d=self.data(); c["alerts"]={"round_overview":{"enabled":True},"owner_team_round":{"enabled":True}}; a=futebol.build_alerts(c,d,19,generated_at="2026-07-17T00:00:00-03:00");
        with tempfile.TemporaryDirectory() as x:
            p=Path(x)/"ledger.json"; _,n,e=futebol.update_alert_ledger(a,"2026-07-17T00:00:00-03:00",p); _,n2,e2=futebol.update_alert_ledger(a,"2026-07-17T01:00:00-03:00",p); self.assertEqual((n,e,n2,e2),(2,0,0,2))
    def test_sem_internet(self):
        c,d=self.data();
        with patch("urllib.request.urlopen") as u: futebol.build_alerts(c,d,19); u.assert_not_called()
    def test_preview_data_com_multiplos_jogos_e_ordem(self):
        c,d=self.data(); p=futebol.render_daily_preview(c,d,"2026-07-16")
        self.assertIn("⚽ JOGOS DE 16/07/2026",p)
        self.assertNotIn("HOJE",p)
        self.assertIn("19h30 — Botafogo x Santos",p)
        self.assertIn("19h30 — Vitória x Vasco da Gama",p)
        self.assertLess(p.index("Botafogo"),p.index("Vitória"))
        self.assertNotIn("Fonte: CBF",p)
    def test_preview_destaca_favorito(self):
        c,d=self.data(); p=futebol.render_daily_preview(c,d,"2026-07-23")
        self.assertTrue(p.startswith("🔴⚫ FLAMENGO EM 23/07/2026"))
        self.assertIn("20h00 — Flamengo x Botafogo",p)
        self.assertIn("📍 Maracanã — Rio de Janeiro/RJ",p)
        self.assertIn("📺 Globo, Premiere",p)
    def test_preview_data_sem_jogos(self):
        c,d=self.data(); self.assertEqual(futebol.render_daily_preview(c,d,"2026-07-22"),"⚽ NÃO HÁ JOGOS EM 22/07/2026")
    def test_data_invalida(self):
        with self.assertRaises(futebol.FutebolError): futebol.parse_schedule_date("22/07/2026")
    def test_today_com_relogio_injetado(self):
        c,d=self.data(); now=datetime.fromisoformat("2026-07-23T01:00:00+00:00")
        self.assertEqual(futebol.local_today(c, now), datetime.fromisoformat("2026-07-22T22:00:00-03:00").date())
    def test_preview_sem_local_ou_transmissao(self):
        c,d=self.data(); d=copy.deepcopy(d); match=d["matches"][0]; match["venue"]=""; match["city"]=""; match["state"]=""; match["broadcasters"]=[]
        p=futebol.render_daily_preview(c,d,"2026-07-16")
        self.assertNotIn("📍",p); self.assertNotIn("📺",p)
    def test_preview_today_usa_hoje(self):
        c,d=self.data(); p=futebol.render_daily_preview(c,d,"2026-07-23",today=True)
        self.assertTrue(p.startswith("🔴⚫ HOJE TEM FLAMENGO"))

    def run_cli(self, *argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = futebol.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, stdout.getvalue(), stderr.getvalue()

    def test_parser_cria_cli_sem_erro(self):
        parser = futebol.build_parser()
        self.assertIsNotNone(parser)
        self.assertEqual(parser.parse_args(["normalize"]).command, "normalize")

    def test_comando_fetch_nao_existe(self):
        code, _, error = self.run_cli("fetch")
        self.assertNotEqual(code, 0)
        self.assertIn("invalid choice", error)

    def test_comando_send_nao_existe(self):
        code, _, error = self.run_cli("send")
        self.assertNotEqual(code, 0)
        self.assertIn("invalid choice", error)

    def test_source_real_aceito(self):
        self.assertEqual(futebol.build_parser().parse_args(["normalize", "--source", "real"]).source, "real")

    def test_fixture_eh_padrao(self):
        self.assertEqual(futebol.build_parser().parse_args(["normalize"]).source, "fixture")

    def test_hash_e_metadados_fixture(self):
        c, d = self.data()
        self.assertEqual(d['source']['provider'], 'CBF')
        self.assertTrue(d['source']['source_url'])
        self.assertEqual(len(d['source']['document_sha256']), 64)
        self.assertTrue(d['source']['captured_at'])

    def test_parser_amostra_oficial_congelada(self):
        c = futebol.load_config()
        sample = Path(futebol.BASE_DIR.parent.parent / 'fixtures' / 'cbf_tabela_oficial_sample.html').read_text()
        source = futebol.SourceSnapshot('CBF', futebol.REAL_URL_DEFAULT, 'real', futebol.now_iso(c['timezone']), sample, None)
        data = futebol.normalize_snapshot(c, source)
        self.assertEqual(data['data_mode'], 'real')
        self.assertEqual(len(data['matches']), 2)

    def test_tabela_completa_extrai_campos_e_ignora_imagens(self):
        c = futebol.load_config()
        sample = '<table><tr><td>Ref: 901 Rodada: 2</td><td>1 x 0</td><td><img alt="escudo mandante">Botafogo x <img alt="escudo visitante">Santos</td><td>Data: 28/01/2026 - quarta-feira às 19h00 Local: Beira-Rio - Porto Alegre - RS</td><td>Transmissão: Globo, Premiere</td></tr></table>'
        source = futebol.SourceSnapshot('CBF', futebol.REAL_URL_DEFAULT, 'real', futebol.now_iso(c['timezone']), sample, None)
        match = futebol.normalize_snapshot(c, source)['matches'][0]
        self.assertEqual((match['reference'], match['round']), ('901', 2))
        self.assertEqual((match['home_team'], match['away_team']), ('Botafogo', 'Santos'))
        self.assertEqual((match['schedule_date'], match['schedule_time']), ('2026-01-28', '19:00'))
        self.assertEqual((match['venue'], match['city'], match['state']), ('Beira-Rio', 'Porto Alegre', 'RS'))
        self.assertEqual(match['broadcasters'], ['Globo', 'Premiere'])

    def test_tabela_completa_rejeita_zero_partidas(self):
        c = futebol.load_config()
        source = futebol.SourceSnapshot('CBF', futebol.REAL_URL_DEFAULT, 'real', futebol.now_iso(c['timezone']), '<table><tr><td>Jogo</td></tr></table>', None)
        with self.assertRaisesRegex(futebol.FutebolError, 'Nenhuma linha'):
            futebol.normalize_snapshot(c, source)

    def test_estrutura_real_nao_reconhecida_falha(self):
        c = futebol.load_config()
        source = futebol.SourceSnapshot('CBF', futebol.REAL_URL_DEFAULT, 'real', futebol.now_iso(c['timezone']), '<html>sem tabela</html>', None)
        with self.assertRaises(futebol.FutebolError): futebol.normalize_snapshot(c, source)

    def test_download_rejeita_http_e_vazio(self):
        c = futebol.load_config(); c['source']['official_url'] = futebol.REAL_URL_DEFAULT
        with patch('urllib.request.urlopen', side_effect=futebol.urllib.error.HTTPError(futebol.REAL_URL_DEFAULT, 503, 'down', {}, io.BytesIO())):
            with self.assertRaisesRegex(futebol.FutebolError, 'HTTP 503'): futebol.fetch_real(c)

    def test_download_usa_timeout_e_rejeita_vazio(self):
        c = futebol.load_config()
        response = type('Response', (), {'status': 200, 'headers': type('Headers', (), {'get_content_type': lambda self: 'text/html'})(), 'read': lambda self, n: b'', 'getcode': lambda self: 200, '__enter__': lambda self: self, '__exit__': lambda *args: None})()
        with patch('urllib.request.urlopen', return_value=response) as mocked:
            with self.assertRaisesRegex(futebol.FutebolError, 'vazia'): futebol.fetch_real(c)
        self.assertEqual(mocked.call_args.kwargs['timeout'], 20.0)

    def real_source(self):
        c = futebol.load_config()
        sample = Path(futebol.BASE_DIR.parent.parent / 'fixtures' / 'cbf_tabela_oficial_sample.html').read_text()
        return c, futebol.SourceSnapshot('CBF', futebol.REAL_URL_DEFAULT, 'real', futebol.now_iso(c['timezone']), sample, None)

    def test_download_rejeita_tipo_inesperado(self):
        c = futebol.load_config()
        response = type('Response', (), {'status': 200, 'headers': type('Headers', (), {'get_content_type': lambda self: 'application/pdf'})(), '__enter__': lambda self: self, '__exit__': lambda *args: None})()
        with patch('urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(futebol.FutebolError, 'Tipo de conteúdo'): futebol.fetch_real(c)

    def test_download_rejeita_tamanho_maximo(self):
        c = futebol.load_config(); c['source']['max_download_bytes'] = 3
        response = type('Response', (), {'status': 200, 'headers': type('Headers', (), {'get_content_type': lambda self: 'text/html'})(), 'read': lambda self, n: b'abcd', '__enter__': lambda self: self, '__exit__': lambda *args: None})()
        with patch('urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(futebol.FutebolError, 'limite'): futebol.fetch_real(c)

    def test_preview_real_por_rodada_data_e_today_offline(self):
        c, source = self.real_source()
        data = futebol.normalize_snapshot(c, source)
        with tempfile.TemporaryDirectory() as directory, patch.object(futebol, 'NORMALIZED_DIR', Path(directory)):
            c['_data_mode'] = 'real'
            futebol.write_normalized(c, data)
            for args in [('preview', '--source', 'real', '--current'), ('preview', '--source', 'real', '--date', '2026-07-16'), ('preview', '--source', 'real', '--today')]:
                with self.subTest(args=args):
                    code, output, error = self.run_cli(*args)
                    self.assertEqual((code, error), (0, ''))
                    self.assertTrue(output)

    def test_real_nao_chama_rede_no_parser(self):
        c, source = self.real_source()
        with patch('urllib.request.urlopen') as network:
            data = futebol.normalize_snapshot(c, source)
        network.assert_not_called()
        self.assertEqual(data['data_mode'], 'real')

    def test_real_preview_mantem_campos_ausentes(self):
        c, source = self.real_source(); data = futebol.normalize_snapshot(c, source)
        data['matches'][0]['venue'] = ''; data['matches'][0]['city'] = ''; data['matches'][0]['state'] = ''
        self.assertIn('Local: ainda não informado', futebol.render_preview(data, round_number=19))

    def test_json_real_normaliza(self):
        c = futebol.load_config()
        payload = '{"jogos":[{"id":"x1","rodada":19,"mandante":"A","visitante":"B","data":"2026-07-16","horario":"19:30"}]}'
        source = futebol.SourceSnapshot('CBF', futebol.REAL_URL_DEFAULT, 'real', futebol.now_iso(c['timezone']), payload, None, 'json')
        self.assertEqual(len(futebol.normalize_snapshot(c, source)['matches']), 1)

    def test_cli_normalize_funciona(self):
        code, output, error = self.run_cli("normalize")
        self.assertEqual((code, error), (0, ""))
        self.assertIn("JSON normalizado salvo em:", output)

    def test_cli_preview_round_funciona(self):
        code, output, error = self.run_cli("preview", "--round", "19")
        self.assertEqual((code, error), (0, ""))
        self.assertIn("RODADA 19", output)

    def test_cli_preview_current_funciona(self):
        code, output, error = self.run_cli("preview", "--current")
        self.assertEqual((code, error), (0, ""))
        self.assertIn("RODADA", output)

    def test_cli_preview_date_funciona(self):
        code, output, error = self.run_cli("preview", "--date", "2026-07-16")
        self.assertEqual((code, error), (0, ""))
        self.assertIn("JOGOS DE 16/07/2026", output)

    def test_cli_preview_today_funciona_com_relogio_controlado(self):
        c, d = self.data()
        with patch.object(futebol, "local_today", return_value=datetime.fromisoformat("2026-07-23T00:00:00-03:00").date()):
            code, output, error = self.run_cli("preview", "--today")
        self.assertEqual((code, error), (0, ""))
        self.assertIn("HOJE TEM FLAMENGO", output)

    def test_cli_alerts_round_dry_run_funciona(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(futebol, "ALERT_LEDGER_PATH", root / "alerts.json"), patch.object(futebol, "ALERTS_PLAN_PATH", root / "plan.json"), patch.object(futebol, "ALERTS_PREVIEW_PATH", root / "preview.txt"):
                code, output, error = self.run_cli("alerts", "--round", "19", "--dry-run")
        self.assertEqual((code, error), (0, ""))
        self.assertIn("Alertas gerados: 2", output)

    def test_cli_alerts_current_dry_run_funciona(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(futebol, "ALERT_LEDGER_PATH", root / "alerts.json"), patch.object(futebol, "ALERTS_PLAN_PATH", root / "plan.json"), patch.object(futebol, "ALERTS_PREVIEW_PATH", root / "preview.txt"):
                code, output, error = self.run_cli("alerts", "--current", "--dry-run")
        self.assertEqual((code, error), (0, ""))
        self.assertIn("Alertas gerados: 2", output)

    def test_execucao_local_nao_chama_rede_nem_subprocesso(self):
        with patch("urllib.request.urlopen") as urlopen, patch("subprocess.run") as run, patch("subprocess.Popen") as popen:
            code, _, error = self.run_cli("preview", "--round", "19")
        self.assertEqual((code, error), (0, ""))
        urlopen.assert_not_called()
        run.assert_not_called()
        popen.assert_not_called()

    def test_time_favorito_nao_fica_fixo_em_flamengo(self):
        c, d = self.data()
        c["owner_team"] = "Botafogo"
        message = futebol.render_whatsapp_owner_team_message(c, d, 19)
        self.assertIn("PRÓXIMO JOGO DO BOTAFOGO", message)
        self.assertNotIn("PRÓXIMO JOGO DO FLAMENGO", message)

    def test_fixture_textual_pdf_normaliza_campos(self):
        c = futebol.load_config()
        source = futebol.SourceSnapshot('CBF', 'fixture-text', 'fixture', futebol.now_iso(c['timezone']), futebol.TEXT_FIXTURE_PATH.read_text(), None, 'text')
        data = futebol.normalize_snapshot(c, source)
        self.assertEqual(len(data['matches']), 12)
        self.assertEqual(data['matches'][0]['broadcasters'], ['Record', 'Youtube / Cazé TV', 'Premiere'])
        self.assertEqual((data['matches'][0]['venue'], data['matches'][0]['city'], data['matches'][0]['state']), ('Nilton Santos', 'Rio de Janeiro', 'RJ'))

    def test_descoberta_pdf_e_fallback(self):
        c = futebol.load_config()
        html = '<a href="https://stcbfsiteprdimgbrs.blob.core.windows.net/x/Tabela_Detalhada_2026.pdf">PDF</a>'
        self.assertTrue(futebol.discover_document_url(html, c).endswith('.pdf'))
        self.assertEqual(futebol.locate_document_url(c, '<html>sem link</html>'), c['source']['document_url'])

    def test_host_nao_aprovado_rejeitado(self):
        with self.assertRaises(futebol.FutebolError):
            futebol.approved_url('https://example.com/tabela.pdf', document=True)

    def test_comandos_invalidos_retornam_erro_claro(self):
        for argv in (("preview", "--round"), ("preview", "--date", "16/07/2026"), ("alerts", "--round", "19")):
            with self.subTest(argv=argv):
                code, _, error = self.run_cli(*argv)
                self.assertNotEqual(code, 0)
                self.assertTrue(error.startswith("usage:") or "obrigatório" in error or "invalid" in error or "Data inválida" in error)

if __name__ == "__main__": unittest.main()
