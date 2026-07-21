import copy
import io
import json
import types
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from orion_football import futebol

class FutebolTests(unittest.TestCase):
    def data(self):
        c=futebol.load_config(); return c, futebol.normalize_snapshot(c, futebol.fetch_fixture(c))
    def favorite_day_with_others(self):
        c,d=self.data(); d=copy.deepcopy(d)
        favorite=next(m for m in d["matches"] if "Flamengo" in (m["home_team"], m["away_team"]))
        early=copy.deepcopy(next(m for m in d["matches"] if m["home_team"]=="Botafogo"))
        late=copy.deepcopy(next(m for m in d["matches"] if m["home_team"]=="Mirassol"))
        favorite.update(home_team="Flamengo", away_team="Adversário", schedule_date="2026-07-23", schedule_time="20:00", broadcasters=["Globo", "Premiere"])
        early.update(home_team="Time A", away_team="Time B", schedule_date="2026-07-23", schedule_time="19:30", broadcasters=[])
        late.update(home_team="Time C", away_team="Time D", schedule_date="2026-07-23", schedule_time="21:30", broadcasters=[])
        d["matches"]=[late, favorite, early]
        return c,d
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
        with patch("orion_football.futebol.urlopen") as u: futebol.build_alerts(c,d,19); u.assert_not_called()
    def test_preview_data_com_multiplos_jogos_e_ordem(self):
        c,d=self.data(); p=futebol.render_daily_preview(c,d,"2026-07-16")
        self.assertEqual(p, "🏆 *BRASILEIRÃO 2026*\n\n*Jogos em 16/07/2026*\n\nBotafogo x Santos · 19h30\nVitória x Vasco da Gama · 19h30\nMirassol x Grêmio · 20h00")
        self.assertLess(p.index("Botafogo"),p.index("Vitória"))
        self.assertNotIn("Fonte: CBF",p)
        self.assertNotIn("Nilton Santos",p)
    def test_preview_destaca_favorito(self):
        c,d=self.favorite_day_with_others(); p=futebol.render_daily_preview(c,d,"2026-07-23",today=True)
        self.assertEqual(p, "🏆 *BRASILEIRÃO 2026*\n\n🔴⚫ *Hoje tem Flamengo*\n\nFlamengo x Adversário\n20h00\n\n📺 Globo e Premiere\n\n*Outros jogos de hoje*\n\nTime A x Time B · 19h30\nTime C x Time D · 21h30")
        self.assertEqual(p.count("Flamengo x Adversário"), 1)
        self.assertLess(p.index("Time A"), p.index("Time C")); self.assertNotIn("Local:", p); self.assertNotIn("Fonte:", p); self.assertNotIn("\n\n\n", p)
    def test_preview_data_sem_jogos(self):
        c,d=self.data(); self.assertEqual(futebol.render_daily_preview(c,d,"2026-07-22"),"⚽ Não há jogos no BRASILEIRÃO 2026 em 22/07/2026.")
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
        self.assertIn("*Hoje tem Flamengo*", p)
    def test_preview_today_sem_favorito(self):
        c,d=self.data(); p=futebol.render_daily_preview(c,d,"2026-07-16",today=True)
        self.assertIn("*Hoje no Brasileirão*", p)
    def test_favorito_sem_transmissao_e_sem_outros_jogos(self):
        c,d=self.data(); d=copy.deepcopy(d)
        matches=[m for m in d["matches"] if m["schedule_date"]=="2026-07-23"]
        for match in matches:
            if "Flamengo" in (match["home_team"], match["away_team"]): match["broadcasters"]=[]
        d["matches"]=[m for m in d["matches"] if m not in matches or "Flamengo" in (m["home_team"], m["away_team"])]
        p=futebol.render_daily_preview(c,d,"2026-07-23",today=True)
        self.assertNotIn("📺", p); self.assertNotIn("Outros jogos", p); self.assertNotIn("\n\n\n", p)
    def test_competicao_e_time_favorito_parametrizados(self):
        c,d=self.data(); c["owner_team"]="Botafogo"; d=copy.deepcopy(d); d["competition"]="copa_exemplo"; d["competition_display_name"]="Copa Exemplo"
        p=futebol.render_daily_preview(c,d,"2026-07-16",today=True)
        self.assertIn("🏆 *COPA EXEMPLO 2026*", p); self.assertIn("*Hoje tem Botafogo*", p); self.assertNotIn("Flamengo", p)
    def test_pregame_minutos_parametrizados(self):
        c,d=self.data(); match=futebol.select_owner_match_by_date(c,d,"2026-07-23")
        p=futebol.render_pregame_alert(match, 25)
        self.assertEqual(p, "⏰ *Faltam 25 minutos*\n\nFlamengo x Botafogo\n20h00\n\n📺 Globo e Premiere")
        self.assertNotIn("Começa às", p); self.assertNotIn("Maracanã", p); self.assertNotIn("Fonte", p)
    def test_pregame_sem_transmissao_e_minutos_invalidos(self):
        c,d=self.data(); match=copy.deepcopy(futebol.select_owner_match_by_date(c,d,"2026-07-23")); match["broadcasters"]=[]
        self.assertNotIn("📺", futebol.render_pregame_alert(match, 5))
        with self.assertRaises(futebol.FutebolError): futebol.render_pregame_alert(match, -1)
    def test_cli_date_usa_titulo_de_data(self):
        output=io.StringIO()
        with redirect_stdout(output): self.assertEqual(futebol.main(["preview", "--source", "fixture", "--date", "2026-07-16"]), 0)
        self.assertIn("*Jogos em 16/07/2026*", output.getvalue()); self.assertNotIn("*Hoje no", output.getvalue())
    def test_cli_today_usa_titulo_de_hoje(self):
        output=io.StringIO()
        with patch("orion_football.futebol.local_today", return_value=futebol.parse_schedule_date("2026-07-16")):
            with redirect_stdout(output): self.assertEqual(futebol.main(["preview", "--source", "fixture", "--today"]), 0)
        self.assertIn("*Hoje no Brasileirão*", output.getvalue()); self.assertNotIn("*Jogos em", output.getvalue())
    def test_cli_pregame(self):
        self.assertEqual(futebol.main(["pregame", "--source", "fixture", "--date", "2026-07-23", "--minutes", "15"]), 0)

    def real_config(self, directory):
        config = {"schema_version": 1, "competition": "campeonato_brasileiro_serie_a", "competition_display_name": "Brasileirão", "season": 2026, "owner_team": "Flamengo", "timezone": "America/Sao_Paulo", "data_dir": str(Path(directory) / "data"), "source": {"provider": "CBF", "mode": "real"}}
        path = Path(directory) / "config.json"; path.write_text(json.dumps(config), encoding="utf-8")
        data = futebol.normalize_snapshot(config, futebol.fetch_fixture(config)); data["data_mode"] = "real"
        normalized = futebol.normalized_path(config, "real"); normalized.parent.mkdir(parents=True); normalized.write_text(json.dumps(data), encoding="utf-8")
        return config, path, normalized

    def test_paths_use_configured_data_dir_without_globals(self):
        config = {"season": 2026, "data_dir": "/tmp/orion-football-paths"}
        self.assertEqual(futebol.normalized_path(config, "real"), Path("/tmp/orion-football-paths/normalized/brasileirao_serie_a_2026_real.json"))
        self.assertEqual(futebol.raw_path(config, "input.pdf"), Path("/tmp/orion-football-paths/raw/input.pdf"))
        self.assertFalse(hasattr(futebol, "NORMALIZED_DIR")); self.assertFalse(hasattr(futebol, "RAW_DIR"))

    def test_doctor_and_real_commands_are_local(self):
        with tempfile.TemporaryDirectory() as directory:
            _, config_path, _ = self.real_config(directory)
            output = io.StringIO()
            with patch("orion_football.futebol.urlopen") as network, patch.object(futebol.sys, "version_info", (3, 11, 0)), patch.dict("sys.modules", {"pypdf": types.ModuleType("pypdf")}), redirect_stdout(output):
                self.assertEqual(futebol.main(["--config", str(config_path), "doctor"]), 0)
                self.assertEqual(futebol.main(["--config", str(config_path), "preview", "--source", "real", "--date", "2026-07-16"]), 0)
                with patch("orion_football.futebol.local_today", return_value=futebol.parse_schedule_date("2026-07-16")):
                    self.assertEqual(futebol.main(["--config", str(config_path), "preview", "--source", "real", "--today"]), 0)
                self.assertEqual(futebol.main(["--config", str(config_path), "pregame", "--source", "real", "--date", "2026-07-23", "--minutes", "10"]), 0)
            network.assert_not_called(); self.assertIn("JSON real legível", output.getvalue())

    def test_doctor_errors_for_missing_config_json_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            with redirect_stdout(io.StringIO()): self.assertNotEqual(futebol.main(["--config", str(missing), "doctor"]), 0)
            _, config_path, normalized = self.real_config(directory)
            normalized.unlink()
            with redirect_stdout(io.StringIO()): self.assertNotEqual(futebol.main(["--config", str(config_path), "doctor"]), 0)
            normalized.parent.mkdir(parents=True, exist_ok=True); normalized.write_text("{invalid", encoding="utf-8")
            with redirect_stdout(io.StringIO()): self.assertNotEqual(futebol.main(["--config", str(config_path), "doctor"]), 0)

    def test_doctor_is_listed_in_help(self):
        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as exit_result: futebol.main(["--help"])
        self.assertEqual(exit_result.exception.code, 0)
        self.assertIn("doctor", output.getvalue())

if __name__ == "__main__": unittest.main()
