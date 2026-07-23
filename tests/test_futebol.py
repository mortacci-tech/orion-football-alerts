import copy
import hashlib
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

    def test_cli_pregame_usa_minutos_da_configuracao(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(futebol.main(["pregame", "--source", "fixture", "--date", "2026-07-23"]), 0)
        self.assertIn("Faltam 15 minutos", output.getvalue())

    def test_recursos_publicos_estao_no_pacote(self):
        self.assertTrue(futebol.CONFIG_PATH.is_file())
        self.assertTrue(futebol.FIXTURE_PATH.is_file())

    def real_config(self, directory):
        config = {"schema_version": 1, "competition": "campeonato_brasileiro_serie_a", "competition_display_name": "Brasileirão", "season": 2026, "owner_team": "Flamengo", "timezone": "America/Sao_Paulo", "data_dir": str(Path(directory) / "data"), "source": {"provider": "CBF", "mode": "real", "min_match_count": 1}}
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

    def fake_pdf_modules(self, texts):
        pages = [types.SimpleNamespace(extract_text=lambda text=text: text) for text in texts]
        module = types.ModuleType("pypdf")
        module.PdfReader = lambda stream: types.SimpleNamespace(pages=pages)
        return {"pypdf": module}

    def candidate(self, config, *, changed=False):
        data = futebol.normalize_snapshot(config, futebol.fetch_fixture(config))
        data["data_mode"] = "real"
        data["source"] = {"provider": "CBF", "fetched_at": "2026-07-20T12:00:00-03:00"}
        if changed:
            data["matches"][0]["venue"] = "Estádio Atualizado"
        return data

    def download(self):
        body = b"%PDF-fake"
        return futebol.PdfDownload("https://cbf.com.br/tabela.pdf", "https://cbf.com.br/tabela.pdf", 200, "application/pdf", body, hashlib.sha256(body).hexdigest(), futebol.REAL_URL_DEFAULT)

    def test_extract_pdf_text_multiplas_paginas_e_pagina_vazia(self):
        with patch.dict("sys.modules", self.fake_pdf_modules(["página um", None, "página três"])):
            extracted = futebol.extract_pdf_text(b"%PDF-fake")
        self.assertEqual(extracted.pages, ("página um", "", "página três"))
        self.assertEqual(extracted.page_count, 3)
        self.assertLess(extracted.text.index("página um"), extracted.text.index("página três"))

    def test_extract_pdf_text_rejeita_sem_texto_e_pdf_invalido(self):
        with patch.dict("sys.modules", self.fake_pdf_modules([None, "  "])):
            with self.assertRaisesRegex(futebol.FutebolError, "camada textual"):
                futebol.extract_pdf_text(b"%PDF-fake")
        with self.assertRaisesRegex(futebol.FutebolError, "assinatura"):
            futebol.extract_pdf_text("não é pdf".encode())

    def test_download_pdf_rejeita_content_type_e_assinatura(self):
        config = futebol.load_config()
        headers = types.SimpleNamespace(get=lambda key, default='': 'text/plain', get_content_type=lambda: 'text/plain')
        response = types.SimpleNamespace(headers=headers, geturl=lambda: futebol.REAL_DOCUMENT_DEFAULT)
        with patch("orion_football.futebol._download", side_effect=[(b"<html>sem link</html>", response, 200), (b"%PDF-fake", response, 200)]):
            with self.assertRaisesRegex(futebol.FutebolError, "Content-Type"):
                futebol.download_pdf_from_article(config)
        pdf_headers = types.SimpleNamespace(get=lambda key, default='': 'application/pdf', get_content_type=lambda: 'application/pdf')
        pdf_response = types.SimpleNamespace(headers=pdf_headers, geturl=lambda: futebol.REAL_DOCUMENT_DEFAULT)
        with patch("orion_football.futebol._download", side_effect=[(b"<html>sem link</html>", response, 200), (b"not-pdf", pdf_response, 200)]):
            with self.assertRaisesRegex(futebol.FutebolError, "assinatura"):
                futebol.download_pdf_from_article(config)

    def test_download_pdf_usa_fallback_oficial_quando_artigo_falha(self):
        config = futebol.load_config()
        configured = config["source"]["document_url"]
        pdf_headers = types.SimpleNamespace(get=lambda key, default='': 'application/pdf', get_content_type=lambda: 'application/pdf')
        pdf_response = types.SimpleNamespace(headers=pdf_headers, geturl=lambda: configured)
        with patch("orion_football.futebol._download", side_effect=[futebol.FutebolError("falha TLS"), (b"%PDF-fake", pdf_response, 200)]) as download:
            result = futebol.download_pdf_from_article(config)
        self.assertEqual(result.requested_url, configured)
        self.assertEqual(download.call_args_list[1].args, (configured, config, "application/pdf"))

    def test_download_pdf_rejeita_fallback_fora_dos_hosts_aprovados(self):
        config = futebol.load_config()
        config["source"]["document_url"] = "https://example.com/tabela.pdf"
        with patch("orion_football.futebol._download", side_effect=futebol.FutebolError("offline")) as download:
            with self.assertRaisesRegex(futebol.FutebolError, "infraestrutura oficial"):
                futebol.download_pdf_from_article(config)
        self.assertEqual(download.call_count, 1)

    def test_normalize_real_entrega_texto_extraido_ao_parser(self):
        config = futebol.load_config(); config["source"]["min_match_count"] = 1
        extraction = futebol.PdfExtraction("linha um\nlinha dois", ("linha um", "linha dois"), 2)
        match = self.candidate(config)["matches"][0]
        with patch("orion_football.futebol.parse_pdf_line", side_effect=[match, None]) as parser:
            data = futebol.normalize_pdf_real(config, extraction, self.download())
        self.assertEqual(parser.call_args_list[0].args[0], "linha um")
        self.assertEqual(len(data["matches"]), 1)

    def test_refresh_updated_e_manifesto(self):
        with tempfile.TemporaryDirectory() as directory:
            config, _, active = self.real_config(directory)
            before = active.read_bytes()
            candidate = self.candidate(config, changed=True)
            extraction = futebol.PdfExtraction("texto", ("texto",), 1)
            with patch("orion_football.futebol.download_pdf_from_article", return_value=self.download()), patch("orion_football.futebol.extract_pdf_text", return_value=extraction), patch("orion_football.futebol.normalize_pdf_real", return_value=candidate):
                result, path, manifest = futebol.refresh_real(config)
            self.assertEqual(result, "UPDATED")
            self.assertEqual(path, active)
            self.assertNotEqual(active.read_bytes(), before)
            self.assertEqual(manifest["result"], "UPDATED")
            self.assertEqual((manifest["http_status"], manifest["page_count"], manifest["match_count"]), (200, 1, len(candidate["matches"])))
            self.assertEqual(json.loads(futebol.manifest_path(config).read_text())["pdf_sha256"], self.download().pdf_sha256)

    def test_refresh_unchanged_nao_regrava_json(self):
        with tempfile.TemporaryDirectory() as directory:
            config, _, active = self.real_config(directory)
            previous = json.loads(active.read_text())
            before = (active.stat().st_mtime_ns, hashlib.sha256(active.read_bytes()).hexdigest())
            extraction = futebol.PdfExtraction("texto", ("texto",), 1)
            with patch("orion_football.futebol.download_pdf_from_article", return_value=self.download()), patch("orion_football.futebol.extract_pdf_text", return_value=extraction), patch("orion_football.futebol.normalize_pdf_real", return_value=previous):
                result, _, _ = futebol.refresh_real(config)
            after = (active.stat().st_mtime_ns, hashlib.sha256(active.read_bytes()).hexdigest())
            self.assertEqual(result, "UNCHANGED")
            self.assertEqual(after, before)

    def assert_refresh_preserved(self, failure_patch, expected):
        with tempfile.TemporaryDirectory() as directory:
            config, _, active = self.real_config(directory)
            before = (active.stat().st_mtime_ns, hashlib.sha256(active.read_bytes()).hexdigest())
            with failure_patch:
                with self.assertRaisesRegex(futebol.FutebolError, "FAILED_PRESERVED") as raised:
                    futebol.refresh_real(config)
            after = (active.stat().st_mtime_ns, hashlib.sha256(active.read_bytes()).hexdigest())
            self.assertEqual(after, before)
            self.assertIn(expected, str(raised.exception))
            manifest = json.loads(futebol.manifest_path(config).read_text())
            self.assertEqual(manifest["result"], "FAILED_PRESERVED")

    def test_falha_rede_preserva_snapshot(self):
        self.assert_refresh_preserved(patch("orion_football.futebol.download_pdf_from_article", side_effect=futebol.FutebolError("Falha de rede")), "Falha de rede")

    def test_falha_http_preserva_snapshot(self):
        self.assert_refresh_preserved(patch("orion_football.futebol.download_pdf_from_article", side_effect=futebol.FutebolError("HTTP 503")), "HTTP 503")

    def test_falha_extracao_preserva_snapshot(self):
        with patch("orion_football.futebol.download_pdf_from_article", return_value=self.download()):
            self.assert_refresh_preserved(patch("orion_football.futebol.extract_pdf_text", side_effect=futebol.FutebolError("extração falhou")), "extração falhou")

    def test_falha_parser_preserva_snapshot(self):
        extraction = futebol.PdfExtraction("texto", ("texto",), 1)
        with patch("orion_football.futebol.download_pdf_from_article", return_value=self.download()), patch("orion_football.futebol.extract_pdf_text", return_value=extraction):
            self.assert_refresh_preserved(patch("orion_football.futebol.normalize_pdf_real", side_effect=futebol.FutebolError("parser falhou")), "parser falhou")

    def test_falha_schema_preserva_snapshot(self):
        extraction = futebol.PdfExtraction("texto", ("texto",), 1)
        with patch("orion_football.futebol.download_pdf_from_article", return_value=self.download()), patch("orion_football.futebol.extract_pdf_text", return_value=extraction):
            self.assert_refresh_preserved(patch("orion_football.futebol.normalize_pdf_real", return_value={"schema_version": 999}), "schema_version")

    def test_falha_escrita_preserva_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            config, _, active = self.real_config(directory)
            candidate = self.candidate(config, changed=True)
            extraction = futebol.PdfExtraction("texto", ("texto",), 1)
            original_write = futebol.write_json_atomic
            def fail_active(path, data):
                if path == active:
                    raise OSError("disco indisponível")
                return original_write(path, data)
            before = hashlib.sha256(active.read_bytes()).hexdigest()
            with patch("orion_football.futebol.download_pdf_from_article", return_value=self.download()), patch("orion_football.futebol.extract_pdf_text", return_value=extraction), patch("orion_football.futebol.normalize_pdf_real", return_value=candidate), patch("orion_football.futebol.write_json_atomic", side_effect=fail_active):
                with self.assertRaisesRegex(futebol.FutebolError, "FAILED_PRESERVED"):
                    futebol.refresh_real(config)
            self.assertEqual(hashlib.sha256(active.read_bytes()).hexdigest(), before)

    def test_sem_snapshot_anterior_falha_clara(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {"schema_version": 1, "competition": "campeonato_brasileiro_serie_a", "competition_display_name": "Brasileirão", "season": 2026, "owner_team": "Flamengo", "timezone": "America/Sao_Paulo", "data_dir": str(Path(directory) / "data"), "source": {"provider": "CBF", "mode": "real", "min_match_count": 1}}
            with patch("orion_football.futebol.download_pdf_from_article", side_effect=futebol.FutebolError("offline")):
                with self.assertRaisesRegex(futebol.FutebolError, "NO_PREVIOUS_DATA"):
                    futebol.refresh_real(config)
            self.assertFalse(futebol.normalized_path(config, "real").exists())
            self.assertEqual(json.loads(futebol.manifest_path(config).read_text())["result"], "NO_PREVIOUS_DATA")

    def test_candidato_rejeita_duplicada_incompleta_e_aceita_unscheduled(self):
        config = futebol.load_config(); config["source"]["min_match_count"] = 1
        valid = self.candidate(config)
        unscheduled = copy.deepcopy(valid)
        match = unscheduled["matches"][0]
        match.update(status="unscheduled", kickoff=None, schedule_date=None, schedule_time=None, schedule_note="A definir pela CBF")
        futebol.validate_real_candidate(config, unscheduled)
        duplicate = copy.deepcopy(valid); duplicate["matches"].append(copy.deepcopy(duplicate["matches"][0]))
        with self.assertRaisesRegex(futebol.FutebolError, "duplicadas"):
            futebol.validate_real_candidate(config, duplicate)
        incomplete = copy.deepcopy(valid); incomplete["matches"][0]["home_team"] = ""
        with self.assertRaisesRegex(futebol.FutebolError, "Campo essencial"):
            futebol.validate_real_candidate(config, incomplete)

    def test_cli_normalize_real_publica_resultado(self):
        with tempfile.TemporaryDirectory() as directory:
            _, config_path, active = self.real_config(directory)
            manifest = {"pdf_sha256": "a" * 64, "page_count": 2}
            output = io.StringIO()
            with patch("orion_football.futebol.refresh_real", return_value=("UNCHANGED", active, manifest)), redirect_stdout(output):
                self.assertEqual(futebol.main(["--config", str(config_path), "normalize", "--source", "real"]), 0)
            self.assertIn("RESULT: UNCHANGED", output.getvalue())

    def test_preview_e_pregame_reais_apos_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            config, config_path, active = self.real_config(directory)
            candidate = self.candidate(config, changed=True)
            futebol.write_json_atomic(active, candidate)
            with patch("orion_football.futebol.urlopen") as network, redirect_stdout(io.StringIO()):
                self.assertEqual(futebol.main(["--config", str(config_path), "preview", "--source", "real", "--date", "2026-07-16"]), 0)
                self.assertEqual(futebol.main(["--config", str(config_path), "pregame", "--source", "real", "--date", "2026-07-23", "--minutes", "10"]), 0)
            network.assert_not_called()


    def test_normalize_api_game_scheduled(self):
        config = {
            "competition": "campeonato_brasileiro_serie_a",
            "season": 2026,
            "timezone": "America/Sao_Paulo",
        }
        game = {
            "id_jogo": "832073",
            "num_jogo": "184",
            "rodada": "19",
            "mandante": {"nome": "Corinthians"},
            "visitante": {"nome": "Remo"},
            "local": "Neo Química Arena - Sao Paulo - SP",
            "data": " 23/07/2026",
            "hora": "19:30",
        }

        result = futebol.normalize_api_game(game, config)

        self.assertEqual(result["reference"], "832073")
        self.assertEqual(result["round"], 19)
        self.assertEqual(result["home_team"], "Corinthians")
        self.assertEqual(result["away_team"], "Remo")
        self.assertEqual(result["schedule_date"], "2026-07-23")
        self.assertEqual(result["schedule_time"], "19:30")
        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(result["venue"], "Neo Química Arena")
        self.assertEqual(result["city"], "Sao Paulo")
        self.assertEqual(result["state"], "SP")
        self.assertEqual(
            result["source_fields"]["schedule"],
            "cbf_table_api",
        )

    def test_normalize_api_game_unscheduled(self):
        config = {
            "competition": "campeonato_brasileiro_serie_a",
            "season": 2026,
            "timezone": "America/Sao_Paulo",
        }
        game = {
            "id_jogo": "999999",
            "rodada": "20",
            "mandante": {"nome": "Flamengo"},
            "visitante": {"nome": "Palmeiras"},
            "local": "",
            "data": "",
            "hora": "",
        }

        result = futebol.normalize_api_game(game, config)

        self.assertEqual(result["status"], "unscheduled")
        self.assertIsNone(result["kickoff"])
        self.assertIsNone(result["schedule_date"])
        self.assertIsNone(result["schedule_time"])
        self.assertIn("definir", result["schedule_note"])

    def test_discover_competition_id(self):
        html = r'self.__next_f.push([1,"competitionId\":1260611"])'

        self.assertEqual(
            futebol.discover_competition_id(html),
            "1260611",
        )

    def test_discover_competition_id_ausente(self):
        with self.assertRaisesRegex(
            futebol.FutebolError,
            "competitionId",
        ):
            futebol.discover_competition_id("<html></html>")



    def test_certificate_verify_failure(self):
        error = futebol.URLError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] "
            "unable to get local issuer certificate"
        )
        self.assertTrue(
            futebol._certificate_verify_failure(error)
        )
        self.assertFalse(
            futebol._certificate_verify_failure(
                futebol.URLError("conexão recusada")
            )
        )

    def test_download_usa_curl_somente_em_falha_de_certificado(self):
        config = {
            "owner_team": "Flamengo",
            "season": 2026,
            "timezone": "America/Sao_Paulo",
            "source": {
                "curl_tls_fallback_enabled": True,
            },
        }

        expected = (
            b"<html>ok</html>",
            futebol.DownloadResponse(
                final_url="https://www.cbf.com.br/teste",
                status=200,
                content_type="text/html; charset=utf-8",
            ),
            200,
        )

        certificate_error = futebol.URLError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] "
            "unable to get local issuer certificate"
        )

        with patch(
            "orion_football.futebol.urlopen",
            side_effect=certificate_error,
        ), patch(
            "orion_football.futebol._download_with_curl",
            return_value=expected,
        ) as curl:
            result = futebol._download(
                "https://www.cbf.com.br/teste",
                config,
                "text/html",
            )

        self.assertEqual(result, expected)
        curl.assert_called_once()

    def test_download_nao_usa_curl_em_erro_comum(self):
        config = {
            "owner_team": "Flamengo",
            "season": 2026,
            "timezone": "America/Sao_Paulo",
            "source": {
                "curl_tls_fallback_enabled": True,
            },
        }

        with patch(
            "orion_football.futebol.urlopen",
            side_effect=futebol.URLError("conexão recusada"),
        ), patch(
            "orion_football.futebol._download_with_curl",
        ) as curl:
            with self.assertRaisesRegex(
                futebol.FutebolError,
                "conexão recusada",
            ):
                futebol._download(
                    "https://www.cbf.com.br/teste",
                    config,
                    "text/html",
                )

        curl.assert_not_called()

if __name__ == "__main__": unittest.main()
