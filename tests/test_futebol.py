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
    def test_deduplicacao(self):
        c,d=self.data(); html=futebol.FIXTURE_PATH.read_text(); row='<tr><td>Ref: 181 Rodada: 19</td><td>x</td><td>Botafogo x Santos</td><td>Data: 16/07/2026 - quinta-feira às 19h30 Local: Nilton Santos - Rio de Janeiro - RJ</td><td>Transmissão: SporTV / Premiere</td></tr>'; s=futebol.SourceSnapshot("CBF","fixture","fixture",futebol.now_iso(c["timezone"]),html.replace("</tbody>",row+"</tbody>"),None); self.assertEqual(sum(m["reference"]=="181" for m in futebol.normalize_snapshot(c,s)["matches"]),1)
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

    def test_source_real_nao_aceito(self):
        code, _, error = self.run_cli("normalize", "--source", "real")
        self.assertNotEqual(code, 0)
        self.assertIn("unrecognized arguments", error)

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

    def test_comandos_invalidos_retornam_erro_claro(self):
        for argv in (("preview", "--round"), ("preview", "--date", "16/07/2026"), ("alerts", "--round", "19")):
            with self.subTest(argv=argv):
                code, _, error = self.run_cli(*argv)
                self.assertNotEqual(code, 0)
                self.assertTrue(error.startswith("usage:") or "obrigatório" in error or "invalid" in error or "Data inválida" in error)

if __name__ == "__main__": unittest.main()
