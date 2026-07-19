import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orion_football import futebol


class PublicSetupTests(unittest.TestCase):
    def run_cli(self, *args):
        try:
            return futebol.main(list(args))
        except SystemExit as exc:
            return exc.code

    def test_entry_point_and_help_contract(self):
        pyproject = Path(__file__).parents[1] / 'pyproject.toml'
        self.assertIn('orion-football = "orion_football.futebol:main"', pyproject.read_text())
        self.assertEqual(self.run_cli('--help'), 0)

    def test_default_macos_paths_follow_home(self):
        with tempfile.TemporaryDirectory() as home:
            with patch.dict('os.environ', {}, clear=True), patch('pathlib.Path.home', return_value=Path(home)):
                self.assertEqual(futebol.resolve_config_path(), Path(home) / 'Library/Application Support/Orion Football/config.json')
                config = futebol.config_template('Flamengo', 'America/Sao_Paulo', 2026)
                futebol.configure_paths(config)
                self.assertEqual(futebol.DATA_DIR, Path(home) / 'Library/Application Support/Orion Football/data')

    def test_config_argument_has_priority_over_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            explicit = Path(directory) / 'explicit.json'
            env = Path(directory) / 'env.json'
            with patch.dict('os.environ', {'ORION_FOOTBALL_CONFIG': str(env)}):
                self.assertEqual(futebol.resolve_config_path(explicit), explicit)

    def test_init_creates_and_force_backs_up(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / 'config.json'
            with patch('pathlib.Path.home', return_value=Path(directory) / 'home'):
                self.assertEqual(self.run_cli('--config', str(config_path), 'init', '--owner-team', 'Flamengo', '--timezone', 'America/Sao_Paulo', '--season', '2026'), 0)
                first = config_path.read_text()
                self.assertNotEqual(self.run_cli('--config', str(config_path), 'init'), 0)
                self.assertEqual(self.run_cli('--config', str(config_path), 'init', '--owner-team', 'Botafogo', '--force'), 0)
            self.assertTrue(list(config_path.parent.glob('config.json.*.bak')))
            self.assertIn('Botafogo', config_path.read_text())
            self.assertNotEqual(first, config_path.read_text())

    def test_init_rejects_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'config.json')
            with patch('pathlib.Path.home', return_value=Path(directory) / 'home'):
                self.assertNotEqual(self.run_cli('--config', path, 'init', '--timezone', 'Invalid/Zone'), 0)
                self.assertNotEqual(self.run_cli('--config', path, 'init', '--owner-team', '   '), 0)
                self.assertNotEqual(self.run_cli('--config', path, 'init', '--season', '1800'), 0)

    def test_doctor_invalid_json_does_not_use_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text('{invalid')
            with patch('urllib.request.urlopen') as network:
                self.assertNotEqual(self.run_cli('--config', str(path), 'doctor'), 0)
            network.assert_not_called()

    def test_installed_fixture_resolution_is_package_based(self):
        path = futebol.fixture_path('cbf_tabela_detalhada_sample.html')
        self.assertTrue(path.is_file())
        self.assertIn('cbf_tabela_detalhada_sample.html', path.name)

    def test_normalize_fixture_uses_configured_data_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            config = futebol.config_template('Flamengo', 'America/Sao_Paulo', 2026)
            config['data_dir'] = str(Path(directory) / 'data')
            config_path = Path(directory) / 'config.json'
            config_path.write_text(json.dumps(config))
            self.assertEqual(self.run_cli('--config', str(config_path), 'normalize', '--source', 'fixture'), 0)
            self.assertTrue((Path(directory) / 'data/normalized/brasileirao_serie_a_2026_fixture.json').is_file())


if __name__ == '__main__':
    unittest.main()
