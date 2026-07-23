from __future__ import annotations
import argparse
import hashlib
import html
import io
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / 'resources' / 'futebol_config.example.json'
FIXTURE_PATH = BASE_DIR / 'resources' / 'cbf_tabela_detalhada_sample.html'
REAL_URL_DEFAULT = 'https://www.cbf.com.br/futebol-brasileiro/noticias/campeonato-brasileiro/campeonato-brasileiro-serie-a/cbf-divulga-tabela-detalhada-das-rodadas-19-a-24-do-brasileirao-serie-a'
REAL_DOCUMENT_DEFAULT = 'https://stcbfsiteprdimgbrs.blob.core.windows.net/img-site/cdn/Tabela_Detalhada_Brasileiro_Serie_A_2026_19_a_24_rodada_82505dee72.pdf'
REAL_TABLE_DEFAULT = 'https://www.cbf.com.br/futebol-brasileiro/tabelas/campeonato-brasileiro/serie-a/2026'
DEFAULT_CONFIG_PATH = Path.home() / '.config' / 'orion-football-alerts' / 'config.json'
DEFAULT_DATA_DIR = Path.home() / '.local' / 'share' / 'orion-football-alerts'
BROADCASTERS_BY_COLUMN = {'1': 'Globo', '2': 'Record', '3': 'Sportv', '4': 'Amazon', '5': 'Youtube / Cazé TV', '6': 'GE TV', '7': 'Premiere'}
MONTHS_PT = {1: 'JANEIRO', 2: 'FEVEREIRO', 3: 'MARCO', 4: 'ABRIL', 5: 'MAIO', 6: 'JUNHO', 7: 'JULHO', 8: 'AGOSTO', 9: 'SETEMBRO', 10: 'OUTUBRO', 11: 'NOVEMBRO', 12: 'DEZEMBRO'}
WEEKDAYS_PT = {0: 'SEGUNDA-FEIRA', 1: 'TERCA-FEIRA', 2: 'QUARTA-FEIRA', 3: 'QUINTA-FEIRA', 4: 'SEXTA-FEIRA', 5: 'SABADO', 6: 'DOMINGO'}

class FutebolError(Exception):
    pass

@dataclass(frozen=True)
class SourceSnapshot:
    provider: str
    url: str
    status: str
    fetched_at: str
    html_text: str
    raw_path: Path | None

@dataclass(frozen=True)
class PdfDownload:
    requested_url: str
    final_url: str
    http_status: int
    content_type: str
    body: bytes
    pdf_sha256: str
    article_url: str

@dataclass(frozen=True)
class PdfExtraction:
    text: str
    pages: tuple[str, ...]
    page_count: int

def resolve_config_path(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    if os.environ.get('ORION_FOOTBALL_CONFIG'):
        return Path(os.environ['ORION_FOOTBALL_CONFIG']).expanduser()
    return DEFAULT_CONFIG_PATH

def data_dir(config: dict[str, Any]) -> Path:
    return Path(config.get('data_dir') or DEFAULT_DATA_DIR).expanduser()

def raw_path(config: dict[str, Any], name: str) -> Path:
    return data_dir(config) / 'raw' / name

def normalized_path(config: dict[str, Any], source: str='fixture') -> Path:
    suffix = 'real' if source == 'real' else 'fixture'
    return data_dir(config) / 'normalized' / f"brasileirao_serie_a_{config['season']}_{suffix}.json"

def alert_paths(config: dict[str, Any]) -> tuple[Path, Path, Path]:
    state_dir = data_dir(config) / 'state'
    return state_dir / 'alerts.json', state_dir / 'alerts_plan.json', state_dir / 'alerts_preview.txt'

def validate_config(config: dict[str, Any]) -> None:
    if config.get('schema_version', 1) != 1:
        raise FutebolError('schema_version deve ser 1.')
    if not str(config.get('owner_team', '')).strip():
        raise FutebolError('owner_team não pode ser vazio.')
    try:
        season = int(config.get('season'))
    except (TypeError, ValueError) as exc:
        raise FutebolError('season deve ser um ano válido.') from exc
    if not 1900 <= season <= 2100:
        raise FutebolError('season deve estar entre 1900 e 2100.')
    try:
        ZoneInfo(str(config.get('timezone', '')))
    except Exception as exc:
        raise FutebolError(f'timezone inválido: {config.get("timezone")}') from exc
    source = config.get('source')
    if not isinstance(source, dict):
        raise FutebolError('source deve ser um objeto de configuração.')
    mode = source.get('mode', 'fixture')
    if mode not in {'fixture', 'real'}:
        raise FutebolError('source.mode deve ser fixture ou real.')

def load_config(path: str | Path | None = None, *, require: bool = False) -> dict[str, Any]:
    config_path = resolve_config_path(path)
    if not config_path.exists():
        if require:
            raise FutebolError(f'Configuração não encontrada: {config_path}')
        if not CONFIG_PATH.exists():
            raise FutebolError(f'Configuração não encontrada: {config_path}')
        config = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
        config.setdefault('schema_version', 1)
        config.setdefault('data_dir', str(DEFAULT_DATA_DIR))
        config['source'] = {**config.get('source', {}), 'mode': 'fixture'}
    else:
        try:
            config = json.loads(config_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise FutebolError(f'Configuração inválida: {config_path}') from exc
    validate_config(config)
    return config

def ensure_dirs(config: dict[str, Any]) -> None:
    (data_dir(config) / 'raw').mkdir(parents=True, exist_ok=True)
    (data_dir(config) / 'normalized').mkdir(parents=True, exist_ok=True)

def ensure_alert_dirs(config: dict[str, Any]) -> None:
    (data_dir(config) / 'state').mkdir(parents=True, exist_ok=True)

def now_iso(tz_name: str) -> str:
    return datetime.now(ZoneInfo(tz_name)).isoformat(timespec='seconds')

def fetch_fixture(config: dict[str, Any]) -> SourceSnapshot:
    if not FIXTURE_PATH.exists():
        raise FutebolError(f'Fixture não encontrada: {FIXTURE_PATH}')
    tz_name = config['timezone']
    return SourceSnapshot(provider='CBF', url=str(FIXTURE_PATH), status='fixture', fetched_at=now_iso(tz_name), html_text=FIXTURE_PATH.read_text(encoding='utf-8'), raw_path=None)

ALLOWED_CBF_HOSTS = {'cbf.com.br', 'www.cbf.com.br', 'stcbfsiteprdimgbrs.blob.core.windows.net'}

def source_config(config: dict[str, Any]) -> dict[str, Any]:
    return config.get('source', {})

def approved_url(value: str, *, document: bool = False) -> str:
    parsed = urlparse(value)
    if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_CBF_HOSTS:
        raise FutebolError(f'URL não pertence à infraestrutura oficial aprovada da CBF: {value}')
    if document and not parsed.path.lower().endswith('.pdf'):
        raise FutebolError(f'URL de documento CBF não é PDF: {value}')
    return value

def _download(url: str, config: dict[str, Any], accept: str) -> tuple[bytes, Any, int]:
    settings = source_config(config)
    max_bytes = int(settings.get('max_download_bytes', 5_000_000))
    request = Request(approved_url(url), headers={
        'User-Agent': settings.get('user_agent', 'orion-football-alerts/0.1'),
        'Accept': accept,
    })
    try:
        with urlopen(request, timeout=float(settings.get('timeout_seconds', 20))) as response:
            status = int(getattr(response, 'status', None) or response.getcode())
            if not 200 <= status < 300:
                raise FutebolError(f'Fonte CBF respondeu HTTP {status}.')
            content_main = response.headers.get_content_type().lower()
            if accept == 'text/html' and content_main not in {'text/html', 'application/xhtml+xml'}:
                raise FutebolError(f'Tipo de conteúdo inesperado no artigo CBF: {content_main}.')
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(min(65_536, max_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise FutebolError(f'Download da CBF excede o limite de {max_bytes} bytes.')
                chunks.append(chunk)
            return b''.join(chunks), response, status
    except HTTPError as exc:
        raise FutebolError(f'Fonte CBF respondeu HTTP {exc.code}.') from exc
    except (TimeoutError, URLError, OSError) as exc:
        reason = getattr(exc, 'reason', exc)
        raise FutebolError(f'Falha ao acessar a fonte CBF: {reason}.') from exc

def discover_document_url(article_html: str, config: dict[str, Any], base_url: str = REAL_URL_DEFAULT) -> str:
    pattern = source_config(config).get('document_name_pattern', r'Tabela_Detalhada.*\.pdf')
    candidates = re.findall(r'(?:href|src)=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', article_html, flags=re.I)
    candidates += re.findall(r'https?://[^\s"\'<>]+\.pdf(?:\?[^\s"\'<>]*)?', article_html, flags=re.I)
    for raw in candidates:
        candidate = urljoin(base_url, html.unescape(raw))
        if re.search(pattern, candidate, flags=re.I):
            return approved_url(candidate, document=True)
    raise FutebolError('Artigo oficial não contém link PDF de tabela detalhada aprovado.')

def download_pdf_from_article(config: dict[str, Any]) -> PdfDownload:
    settings = source_config(config)
    article_url = approved_url(settings.get('article_url') or REAL_URL_DEFAULT)
    try:
        article_body, _, _ = _download(article_url, config, 'text/html')
        document_url = discover_document_url(article_body.decode('utf-8', errors='replace'), config, article_url)
    except FutebolError:
        document_url = approved_url(settings.get('document_url') or REAL_DOCUMENT_DEFAULT, document=True)
    body, response, status = _download(document_url, config, 'application/pdf')
    content_type = response.headers.get('Content-Type', '')
    content_main = response.headers.get_content_type().lower()
    if not body:
        raise FutebolError('Resposta vazia: PDF da CBF vazio.')
    if content_main != 'application/pdf':
        raise FutebolError(f'Resposta da CBF não é PDF (Content-Type: {content_type or "ausente"}).')
    if not body.startswith(b'%PDF'):
        raise FutebolError('Resposta declarada como PDF, mas não possui assinatura %PDF.')
    final_url = response.geturl() if hasattr(response, 'geturl') else document_url
    approved_url(final_url, document=True)
    return PdfDownload(document_url, final_url, status, content_type, body, hashlib.sha256(body).hexdigest(), article_url)

def extract_pdf_text(pdf: bytes | bytearray | Path | str) -> PdfExtraction:
    if isinstance(pdf, (str, Path)):
        path = Path(pdf).expanduser()
        try:
            body = path.read_bytes()
        except OSError as exc:
            raise FutebolError(f'Não foi possível ler o PDF: {path}: {exc}') from exc
    elif isinstance(pdf, (bytes, bytearray)):
        body = bytes(pdf)
    else:
        raise FutebolError('PDF deve ser informado como bytes ou caminho explícito.')
    if not body.startswith(b'%PDF'):
        raise FutebolError('PDF inválido: assinatura %PDF ausente.')
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(body))
        pages = tuple((page.extract_text() or '') for page in reader.pages)
    except Exception as exc:
        raise FutebolError(f'PDF da CBF corrompido ou ilegível: {exc}') from exc
    if not pages or not any(page.strip() for page in pages):
        raise FutebolError('PDF da CBF não possui camada textual utilizável.')
    return PdfExtraction('\n'.join(pages), pages, len(pages))

def clean_text(value: str) -> str:
    value = html.unescape(re.sub('<[^>]+>', ' ', value))
    return re.sub('\\s+', ' ', value).strip()

def extract_rows(html_text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for row_html in re.findall('<tr\\b[^>]*>(.*?)</tr>', html_text, flags=re.I | re.S):
        cells = re.findall('<t[dh]\\b[^>]*>(.*?)</t[dh]>', row_html, flags=re.I | re.S)
        cleaned = [clean_text(cell) for cell in cells]
        if cleaned and any(('Ref:' in cell or 'Rodada:' in cell for cell in cleaned)):
            rows.append(cleaned)
    if not rows:
        raise FutebolError('Nenhuma linha de partida encontrada na estrutura HTML esperada da CBF.')
    return rows

def parse_match(row: list[str], config: dict[str, Any], source: SourceSnapshot) -> dict[str, Any]:
    if len(row) < 4:
        raise FutebolError(f'Linha incompleta na tabela CBF: {row}')
    reference_cell = row[0]
    teams_cell = row[2]
    date_cell = row[3]
    broadcast_cell = row[4] if len(row) > 4 else ''
    ref_match = re.search('Ref:\\s*([0-9A-Za-z.-]+)', reference_cell)
    round_match = re.search('Rodada:\\s*(\\d+)', reference_cell)
    teams_match = re.match('(.+?)\\s+x\\s+(.+)', teams_cell)
    date_match = re.search('Data:\\s*(\\d{2}/\\d{2}/\\d{4}).*?às\\s*(\\d{1,2})h(\\d{2})', date_cell, flags=re.I)
    local_match = re.search('Local:\\s*(.+)$', date_cell, flags=re.I)
    missing = []
    if not round_match:
        missing.append('rodada')
    if not teams_match:
        missing.append('mandante/visitante')
    if not date_match:
        missing.append('data/horário')
    if missing:
        raise FutebolError(f"Campos essenciais ausentes ({', '.join(missing)}) na linha: {row}")
    reference = ref_match.group(1) if ref_match else deterministic_reference(row)
    round_number = int(round_match.group(1))
    home_team = clean_text(teams_match.group(1))
    away_team = clean_text(teams_match.group(2))
    date_part = date_match.group(1)
    hour = int(date_match.group(2))
    minute = int(date_match.group(3))
    (day, month, year) = [int(part) for part in date_part.split('/')]
    kickoff = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(config['timezone']))
    venue = ''
    city = ''
    state = ''
    if local_match:
        (venue, city, state) = parse_location(local_match.group(1))
    broadcasters = parse_broadcasters(broadcast_cell)
    identity = f"{config['competition']}|{config['season']}|{reference}|{round_number}|{home_team}|{away_team}"
    match_id = stable_match_id('CBF', config['competition'], config['season'], reference, home_team, away_team)
    return {'match_id': match_id, 'reference': reference, 'round': round_number, 'home_team': home_team, 'away_team': away_team, 'kickoff': kickoff.isoformat(timespec='seconds'), 'schedule_date': kickoff.date().isoformat(), 'schedule_time': f'{hour:02d}:{minute:02d}', 'schedule_note': None, 'venue': venue, 'city': city, 'state': state, 'broadcasters': broadcasters, 'status': 'scheduled'}

def deterministic_reference(row: list[str]) -> str:
    return hashlib.sha256('|'.join(row).encode('utf-8')).hexdigest()[:12]

def stable_match_id(provider: str, competition: str, season: int, reference: str, home_team: str='', away_team: str='') -> str:
    official_reference = str(reference or '').strip()
    if official_reference:
        identity = f'{provider}|{competition}|{season}|{official_reference}'
    else:
        identity = f'{provider}|{competition}|{season}|{home_team}|{away_team}'
    return 'cbf-' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]

def parse_location(raw: str) -> tuple[str, str, str]:
    raw = clean_text(raw)
    parts = [part.strip() for part in raw.split(' - ')]
    if len(parts) >= 3:
        return (parts[0], parts[1], parts[2])
    if len(parts) == 2:
        return (parts[0], parts[1], '')
    return (raw, '', '')

def parse_broadcasters(raw: str) -> list[str]:
    raw = re.sub('^Transmissão:\\s*', '', clean_text(raw), flags=re.I)
    if not raw:
        return []
    parts = re.split('\\s*/\\s*|,\\s*|;\\s*', raw)
    return [part.strip() for part in parts if part.strip()]

CITY_NAMES = ('Bragança Paulista', 'Belo Horizonte', 'Rio de Janeiro', 'São Paulo', 'Porto Alegre', 'Chapecó', 'Curitiba', 'Salvador', 'Mirassol', 'Santos', 'Belém')
STATE_CODES = r'AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO'

def _pdf_location_and_broadcast(rest: str) -> tuple[str, str, str, list[str]]:
    broadcast_numbers = re.findall(r'(?<!\d)[1-7](?!\d)', rest)
    rest = re.sub(r'\s+[1-7](?:\s+[1-7])*$', '', rest).strip()
    state_match = re.search(rf'\s+({STATE_CODES})$', rest)
    state = state_match.group(1) if state_match else ''
    before = rest[:state_match.start()].strip() if state_match else ''
    city = next((name for name in sorted(CITY_NAMES, key=len, reverse=True) if before.endswith(name)), '')
    venue = before[:-len(city)].strip() if city else ''
    return venue, city, state, [BROADCASTERS_BY_COLUMN[number] for number in broadcast_numbers]

def parse_pdf_line(line: str, config: dict[str, Any], current_round: int | None = None) -> dict[str, Any] | None:
    line = re.sub(r'^A definir(?=\d)', '', line, flags=re.I).strip()
    pending = re.match(rf'^(\d+)\s+(\d+)[ªaº]?\s+A\s+(?:def\.?|definir)\.?\s+(.+?)\s+({STATE_CODES})\s+x\s+(.+?)\s+({STATE_CODES})\s+(.*)$', line, flags=re.I)
    if pending:
        reference, round_text, home, _home_uf, away, _away_uf, rest = pending.groups()
        venue, city, state, broadcasters = _pdf_location_and_broadcast(rest)
        return {'match_id': stable_match_id('CBF', config['competition'], config['season'], reference, home.strip(), away.strip()), 'reference': reference, 'round': int(round_text), 'home_team': home.strip(), 'away_team': away.strip(), 'kickoff': None, 'schedule_date': None, 'schedule_time': None, 'schedule_note': 'Data e horário a definir pela CBF', 'venue': venue, 'city': city, 'state': state, 'broadcasters': broadcasters, 'status': 'unscheduled'}
    pattern = rf'^(\d+)\s+(?:(\d+)[ªaº]?\s+)?(\d{{2}}/\d{{2}})\s+\S+\s+(?:(\d{{1,2}}:\d{{2}})\s+)?(.+?)\s+({STATE_CODES})\s+x\s+(.+?)\s+({STATE_CODES})\s+(.*)$'
    match = re.match(pattern, line, flags=re.I)
    if not match:
        return None
    reference, round_text, date_text, time_text, home, _home_uf, away, _away_uf, rest = match.groups()
    round_number = int(round_text) if round_text else current_round
    if round_number is None:
        return None
    if not time_text:
        return {'match_id': stable_match_id('CBF', config['competition'], config['season'], reference, home.strip(), away.strip()), 'reference': reference, 'round': round_number, 'home_team': home.strip(), 'away_team': away.strip(), 'kickoff': None, 'schedule_date': None, 'schedule_time': None, 'schedule_note': 'Data e horário a definir pela CBF', 'venue': '', 'city': '', 'state': '', 'broadcasters': [], 'status': 'unscheduled'}
    day, month = map(int, date_text.split('/'))
    hour, minute = map(int, time_text.split(':'))
    kickoff = datetime(int(config['season']), month, day, hour, minute, tzinfo=ZoneInfo(config['timezone']))
    venue, city, state, broadcasters = _pdf_location_and_broadcast(rest)
    return {'match_id': stable_match_id('CBF', config['competition'], config['season'], reference, home.strip(), away.strip()), 'reference': reference, 'round': round_number, 'home_team': home.strip(), 'away_team': away.strip(), 'kickoff': kickoff.isoformat(timespec='seconds'), 'schedule_date': kickoff.date().isoformat(), 'schedule_time': f'{hour:02d}:{minute:02d}', 'schedule_note': None, 'venue': venue, 'city': city, 'state': state, 'broadcasters': broadcasters, 'status': 'scheduled'}


def discover_competition_id(table_html: str) -> str:
    patterns = [
        r'\\"competitionId\\"\s*:\s*\\"?(\d+)',
        r'"competitionId"\s*:\s*"?(\d+)',
        r'competitionId[^0-9]{0,30}(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, table_html, flags=re.I)
        if match:
            return match.group(1)
    raise FutebolError('Tabela online da CBF não informou competitionId.')


def normalize_api_game(game: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    reference = str(game.get('id_jogo') or game.get('num_jogo') or '').strip()
    round_number = int(str(game.get('rodada') or '0').strip())

    home_data = game.get('mandante') if isinstance(game.get('mandante'), dict) else {}
    away_data = game.get('visitante') if isinstance(game.get('visitante'), dict) else {}

    home_team = str(home_data.get('nome') or '').strip()
    away_team = str(away_data.get('nome') or '').strip()

    if not reference or round_number <= 0 or not home_team or not away_team:
        raise FutebolError(f'Jogo incompleto retornado pela API oficial: {reference or "sem referência"}')

    raw_date = str(game.get('data') or '').strip()
    raw_time = str(game.get('hora') or '').strip()
    venue, city, state = parse_location(str(game.get('local') or '').strip())

    base = {
        'match_id': stable_match_id(
            'CBF',
            config['competition'],
            config['season'],
            reference,
            home_team,
            away_team,
        ),
        'reference': reference,
        'round': round_number,
        'home_team': home_team,
        'away_team': away_team,
        'venue': venue,
        'city': city,
        'state': state,
        'broadcasters': [],
        'official_game_id': reference,
        'source_fields': {
            'schedule': 'cbf_table_api',
            'teams': 'cbf_table_api',
            'location': 'cbf_table_api',
        },
    }

    date_match = re.fullmatch(r'(\d{2})/(\d{2})/(\d{4})', raw_date)
    time_match = re.fullmatch(r'(\d{1,2}):(\d{2})', raw_time)

    if not date_match or not time_match:
        return {
            **base,
            'kickoff': None,
            'schedule_date': None,
            'schedule_time': None,
            'schedule_note': 'Data e horário a definir pela CBF',
            'status': 'unscheduled',
        }

    day, month, year = map(int, date_match.groups())
    hour, minute = map(int, time_match.groups())
    kickoff = datetime(
        year,
        month,
        day,
        hour,
        minute,
        tzinfo=ZoneInfo(config['timezone']),
    )

    return {
        **base,
        'kickoff': kickoff.isoformat(timespec='seconds'),
        'schedule_date': kickoff.date().isoformat(),
        'schedule_time': f'{hour:02d}:{minute:02d}',
        'schedule_note': None,
        'status': 'scheduled',
    }


def download_and_normalize_table_api(
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    settings = source_config(config)
    table_url = approved_url(settings.get('table_url') or REAL_TABLE_DEFAULT)

    table_body, table_response, _ = _download(
        table_url,
        config,
        'text/html',
    )
    table_html = table_body.decode('utf-8', errors='replace')
    competition_id = str(
        settings.get('competition_id') or discover_competition_id(table_html)
    ).strip()

    matches_by_id: dict[str, dict[str, Any]] = {}
    round_urls: list[str] = []
    raw_rounds: dict[str, Any] = {}

    for round_number in range(1, 39):
        api_url = (
            'https://www.cbf.com.br/api/cbf/jogos/campeonato/'
            f'{competition_id}/rodada/{round_number}/fase'
        )
        round_urls.append(api_url)

        body, _, _ = _download(api_url, config, 'application/json')

        try:
            payload = json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FutebolError(
                f'API oficial retornou JSON inválido na rodada {round_number}.'
            ) from exc

        if not isinstance(payload, dict):
            raise FutebolError(
                f'API oficial retornou estrutura inválida na rodada {round_number}.'
            )

        raw_rounds[str(round_number)] = payload

        groups = payload.get('jogos')
        if not isinstance(groups, list):
            raise FutebolError(
                f'API oficial não retornou jogos na rodada {round_number}.'
            )

        for group in groups:
            if not isinstance(group, dict):
                continue

            games = group.get('jogo')
            if not isinstance(games, list):
                continue

            for game in games:
                if not isinstance(game, dict):
                    continue
                normalized = normalize_api_game(game, config)
                matches_by_id[normalized['match_id']] = normalized

    matches = sorted(matches_by_id.values(), key=match_sort_key)

    if not matches:
        raise FutebolError('API oficial da CBF não retornou partidas.')

    source = {
        'provider': 'CBF',
        'source_type': 'cbf_table_api',
        'url': table_url,
        'final_url': (
            table_response.geturl()
            if hasattr(table_response, 'geturl')
            else table_url
        ),
        'status': 'real',
        'fetched_at': now_iso(config['timezone']),
        'document_sha256': hashlib.sha256(
            json.dumps(
                raw_rounds,
                ensure_ascii=False,
                sort_keys=True,
                separators=(',', ':'),
            ).encode('utf-8')
        ).hexdigest(),
        'content_length': sum(
            len(json.dumps(value, ensure_ascii=False).encode('utf-8'))
            for value in raw_rounds.values()
        ),
        'content_type': 'application/json',
        'competition_id': competition_id,
        'rounds_consulted': 38,
        'api_urls': round_urls,
        'fallback_used': False,
    }

    candidate = {
        'schema_version': 1,
        'data_mode': 'real',
        'competition': config['competition'],
        'competition_display_name': config.get(
            'competition_display_name',
            '',
        ),
        'season': int(config['season']),
        'timezone': config['timezone'],
        'source': source,
        'matches': matches,
    }

    raw_payload = json.dumps(
        {
            'table_url': table_url,
            'competition_id': competition_id,
            'rounds': raw_rounds,
        },
        ensure_ascii=False,
        indent=2,
    ).encode('utf-8')

    return candidate, source, raw_payload

def normalize_pdf_real(config: dict[str, Any], extraction: PdfExtraction, download: PdfDownload | None = None) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    current_round: int | None = None
    for line in extraction.text.splitlines():
        parsed = parse_pdf_line(line, config, current_round)
        if parsed:
            current_round = int(parsed['round'])
            matches.append(parsed)
    if not matches:
        raise FutebolError('Nenhuma partida encontrada no texto extraído do PDF da CBF.')
    matches.sort(key=match_sort_key)
    source = {
        'provider': 'CBF',
        'url': download.requested_url if download else '',
        'final_url': download.final_url if download else '',
        'status': 'real',
        'fetched_at': now_iso(config['timezone']),
        'document_sha256': download.pdf_sha256 if download else '',
        'content_length': len(download.body) if download else 0,
        'content_type': download.content_type if download else '',
        'page_count': extraction.page_count,
    }
    return {'schema_version': 1, 'data_mode': 'real', 'competition': config['competition'], 'competition_display_name': config.get('competition_display_name', ''), 'season': int(config['season']), 'timezone': config['timezone'], 'source': source, 'matches': matches}

def normalize_snapshot(config: dict[str, Any], source: SourceSnapshot) -> dict[str, Any]:
    matches = [parse_match(row, config, source) for row in extract_rows(source.html_text)]
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for match in matches:
        key = '|'.join([str(match['reference']), str(match['round']), match['home_team'], match['away_team'], match['kickoff']])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(match)
    deduped.sort(key=lambda item: (item['round'], item['kickoff'], item['home_team'], item['away_team']))
    validate_matches(deduped)
    return {'schema_version': 1, 'data_mode': 'fixture', 'competition': config['competition'], 'competition_display_name': config.get('competition_display_name', ''), 'season': config['season'], 'timezone': config['timezone'], 'source': {'provider': source.provider, 'url': source.url, 'status': source.status, 'fetched_at': source.fetched_at, 'raw_path': str(source.raw_path) if source.raw_path else ''}, 'matches': deduped}

def build_summary(matches: list[dict[str, Any]]) -> dict[str, int]:
    return {'total_matches': len(matches), 'scheduled_matches': sum((1 for match in matches if match.get('status') == 'scheduled')), 'unscheduled_matches': sum((1 for match in matches if match.get('status') == 'unscheduled'))}

def validate_matches(matches: list[dict[str, Any]], *, min_count: int = 1, max_count: int = 1_000) -> None:
    if not matches:
        raise FutebolError('Normalização não gerou partidas.')
    if not min_count <= len(matches) <= max_count:
        raise FutebolError(f'Quantidade anormal de partidas: {len(matches)}; esperado entre {min_count} e {max_count}.')
    ids = [match.get('match_id') for match in matches]
    if any(not isinstance(match_id, str) or not match_id.strip() for match_id in ids):
        raise FutebolError('Partida sem match_id válido.')
    if len(ids) != len(set(ids)):
        raise FutebolError('Partidas duplicadas detectadas por match_id.')
    for match in matches:
        for field in ['round', 'home_team', 'away_team', 'status']:
            if match.get(field) in (None, ''):
                raise FutebolError(f'Campo essencial ausente após normalização: {field}')
        try:
            if int(match['round']) <= 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise FutebolError(f"Rodada inválida: {match.get('round')}") from exc
        if not str(match['home_team']).strip() or not str(match['away_team']).strip():
            raise FutebolError('Mandante e visitante devem estar preenchidos.')
        if match['home_team'].casefold() == match['away_team'].casefold():
            raise FutebolError('Mandante e visitante não podem ser iguais.')
        if match['status'] == 'scheduled':
            if not match.get('kickoff'):
                raise FutebolError('Partida scheduled sem kickoff.')
            parsed = datetime.fromisoformat(match['kickoff'])
            if parsed.tzinfo is None:
                raise FutebolError(f"Data sem timezone: {match['kickoff']}")
            if not match.get('schedule_date') or not match.get('schedule_time'):
                raise FutebolError('Partida scheduled sem schedule_date/schedule_time.')
            if date.fromisoformat(match['schedule_date']) != parsed.date():
                raise FutebolError('schedule_date incoerente com kickoff.')
            if not re.fullmatch(r'\d{2}:\d{2}', str(match['schedule_time'])):
                raise FutebolError('schedule_time inválido.')
        elif match['status'] == 'unscheduled':
            if match.get('kickoff') is not None:
                raise FutebolError('Partida unscheduled não pode possuir kickoff.')
            if not match.get('schedule_note'):
                raise FutebolError('Partida unscheduled sem schedule_note.')
        else:
            raise FutebolError(f"Status de partida inválido: {match['status']}")

def match_sort_key(match: dict[str, Any]) -> tuple[Any, ...]:
    return (int(match['round']), match.get('kickoff') or '9999-12-31T23:59:59-03:00', match['home_team'], match['away_team'])

def write_normalized(config: dict[str, Any], data: dict[str, Any], source: str='fixture') -> Path:
    ensure_dirs(config)
    path = normalized_path(config, source)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path

def manifest_path(config: dict[str, Any]) -> Path:
    return data_dir(config) / 'state' / f'brasileirao_serie_a_{config["season"]}_real_source_manifest.json'

def canonical_sports_json(data: dict[str, Any]) -> bytes:
    payload = {
        'schema_version': data.get('schema_version'),
        'data_mode': data.get('data_mode'),
        'competition': data.get('competition'),
        'competition_display_name': data.get('competition_display_name', ''),
        'season': data.get('season'),
        'timezone': data.get('timezone'),
        'matches': data.get('matches'),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

def canonical_sha256(data: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_sports_json(data)).hexdigest()

def validate_real_candidate(config: dict[str, Any], data: dict[str, Any]) -> None:
    if data.get('schema_version') != 1:
        raise FutebolError('Candidato real possui schema_version inválido.')
    if data.get('data_mode') != 'real':
        raise FutebolError('Candidato real possui data_mode inválido.')
    if data.get('competition') != config.get('competition'):
        raise FutebolError('Competition do candidato diverge da configuração.')
    if int(data.get('season', 0)) != int(config.get('season', 0)):
        raise FutebolError('Season do candidato diverge da configuração.')
    if not isinstance(data.get('matches'), list):
        raise FutebolError('Candidato real não possui lista de partidas.')
    settings = source_config(config)
    validate_matches(data['matches'], min_count=int(settings.get('min_match_count', 10)), max_count=int(settings.get('max_match_count', 1_000)))

def read_valid_previous(config: dict[str, Any], path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return None, ''
    try:
        previous = json.loads(path.read_text(encoding='utf-8'))
        validate_real_candidate(config, previous)
    except (OSError, json.JSONDecodeError, FutebolError) as exc:
        raise FutebolError(f'JSON real anterior existe, mas não é válido: {path}: {exc}') from exc
    return previous, canonical_sha256(previous)

def write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f'.{path.name}.', suffix='.tmp', delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise

def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    write_bytes_atomic(path, (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))

def _manifest(config: dict[str, Any], *, result: str, active_path: Path, previous_sha: str = '', candidate_sha: str = '', download: PdfDownload | None = None, page_count: int = 0, match_count: int = 0, error: str = '') -> dict[str, Any]:
    return {
        'schema_version': 1,
        'timestamp': now_iso(config['timezone']),
        'requested_url': download.requested_url if download else source_config(config).get('article_url', REAL_URL_DEFAULT),
        'final_url': download.final_url if download else '',
        'http_status': download.http_status if download else None,
        'content_type': download.content_type if download else '',
        'size_bytes': len(download.body) if download else 0,
        'pdf_sha256': download.pdf_sha256 if download else '',
        'page_count': page_count,
        'match_count': match_count,
        'candidate_json_sha256': candidate_sha,
        'previous_json_sha256': previous_sha,
        'result': result,
        'error': re.sub(r'\s+', ' ', error).strip()[:500],
        'active_json_path': str(active_path),
    }

def refresh_real(config: dict[str, Any]) -> tuple[str, Path, dict[str, Any]]:
    active_path = normalized_path(config, 'real')
    previous: dict[str, Any] | None = None
    previous_sha = ''
    candidate: dict[str, Any] | None = None
    candidate_sha = ''
    download: PdfDownload | None = None
    extraction: PdfExtraction | None = None
    primary_error = ''
    source_type = 'pdf_fallback'
    raw_api_payload: bytes | None = None

    try:
        previous, previous_sha = read_valid_previous(config, active_path)

        if bool(source_config(config).get('table_api_enabled', False)):
            try:
                candidate, _, raw_api_payload = (
                    download_and_normalize_table_api(config)
                )
                source_type = 'cbf_table_api'
            except Exception as exc:
                primary_error = str(exc)
                candidate = None

        if candidate is None:
            download = download_pdf_from_article(config)
            extraction = extract_pdf_text(download.body)
            candidate = normalize_pdf_real(config, extraction, download)
            source_type = 'pdf_fallback'

        validate_real_candidate(config, candidate)

        if source_type == 'pdf_fallback':
            candidate['source']['source_type'] = 'pdf_fallback'
            candidate['source']['fallback_used'] = True
            candidate['source']['primary_error'] = primary_error

        candidate_sha = canonical_sha256(candidate)

        result = (
            'UNCHANGED'
            if previous_sha and previous_sha == candidate_sha
            else 'UPDATED'
        )

        if source_type == 'cbf_table_api' and raw_api_payload is not None:
            write_bytes_atomic(
                raw_path(config, f'cbf_{config["season"]}_table_api.json'),
                raw_api_payload,
            )
        elif download is not None:
            write_bytes_atomic(
                raw_path(config, f'cbf_{config["season"]}_real.pdf'),
                download.body,
            )

        manifest = _manifest(
            config,
            result=result,
            active_path=active_path,
            previous_sha=previous_sha,
            candidate_sha=candidate_sha,
            download=download,
            page_count=extraction.page_count if extraction else 0,
            match_count=len(candidate['matches']),
        )

        source = candidate.get('source', {})
        manifest.update({
            'primary_source': source_type,
            'table_url': source.get('url', ''),
            'competition_id': source.get('competition_id', ''),
            'rounds_consulted': source.get('rounds_consulted', 0),
            'fallback_used': bool(source.get('fallback_used', False)),
            'primary_error': primary_error,
            'source_document_sha256': source.get(
                'document_sha256',
                '',
            ),
        })

        write_json_atomic(manifest_path(config), manifest)

        if result == 'UPDATED':
            write_json_atomic(active_path, candidate)

        return result, active_path, manifest

    except Exception as exc:
        error = (
            exc
            if isinstance(exc, FutebolError)
            else FutebolError(f'Falha na atualização real: {exc}')
        )
        result = (
            'FAILED_PRESERVED'
            if previous is not None
            else 'NO_PREVIOUS_DATA'
        )
        candidate_matches = (
            candidate.get('matches')
            if isinstance(candidate, dict)
            else None
        )

        manifest = _manifest(
            config,
            result=result,
            active_path=active_path,
            previous_sha=previous_sha,
            candidate_sha=candidate_sha,
            download=download,
            page_count=extraction.page_count if extraction else 0,
            match_count=(
                len(candidate_matches)
                if isinstance(candidate_matches, list)
                else 0
            ),
            error=str(error),
        )
        manifest.update({
            'primary_source': source_type,
            'primary_error': primary_error,
        })

        try:
            write_json_atomic(manifest_path(config), manifest)
        except Exception as manifest_exc:
            raise FutebolError(
                f'{result}: {error}; '
                f'falha ao registrar manifesto: {manifest_exc}'
            ) from exc

        preservation = (
            'snapshot anterior preservado'
            if previous is not None
            else 'não existe snapshot anterior válido'
        )
        raise FutebolError(
            f'{result}: {error}; {preservation}.'
        ) from exc

def write_fixture_raw(config: dict[str, Any], snapshot: SourceSnapshot) -> Path:
    ensure_dirs(config)
    path = raw_path(config, 'cbf_tabela_detalhada_fixture.html')
    path.write_text(snapshot.html_text, encoding='utf-8')
    return path

def load_normalized(config: dict[str, Any], source: str='fixture') -> dict[str, Any]:
    path = normalized_path(config, source)
    if not path.exists():
        raise FutebolError(f'JSON normalizado não encontrado: {path}')
    return json.loads(path.read_text(encoding='utf-8'))

def choose_current_round(matches: list[dict[str, Any]], tz_name: str, now: datetime | None=None) -> int:
    tz = ZoneInfo(tz_name)
    current = now.astimezone(tz) if now else datetime.now(tz)
    rounds = sorted({int(match['round']) for match in matches})
    for round_number in rounds:
        round_matches = [match for match in matches if int(match['round']) == round_number]
        scheduled = [match for match in round_matches if match.get('status') == 'scheduled' and match.get('kickoff')]
        if any((datetime.fromisoformat(match['kickoff']) >= current for match in scheduled)):
            return round_number
    return rounds[-1]

def render_preview(data: dict[str, Any], round_number: int | None=None, current: bool=False, config: dict[str, Any] | None=None) -> str:
    matches = data['matches']
    if current:
        round_number = choose_current_round(matches, data['timezone'])
    if round_number is None:
        round_number = min((int(match['round']) for match in matches))
    round_matches = [match for match in matches if int(match['round']) == round_number]
    if not round_matches:
        raise FutebolError(f'Rodada não encontrada: {round_number}')
    owner_team = (config or load_config())['owner_team']
    if data.get('data_mode') == 'real':
        source = data.get('source', {})
        lines = ['FONTE REAL VALIDADA — CBF', f'Fonte: CBF', f"Última atualização da fonte: {source.get('fetched_at', 'não informada')}", '', f"BRASILEIRÃO {data['season']} — RODADA {round_number}", '']
    else:
        lines = ['⚠️ FIXTURE — DADOS DE TESTE, NÃO USAR COMO INFORMAÇÃO REAL', '', f"BRASILEIRÃO {data['season']} — RODADA {round_number}", '']
    scheduled_matches = [match for match in round_matches if match.get('status') == 'scheduled']
    unscheduled_matches = [match for match in round_matches if match.get('status') == 'unscheduled']
    last_day = ''
    for match in scheduled_matches:
        kickoff = datetime.fromisoformat(match['kickoff'])
        day_label = f'{WEEKDAYS_PT[kickoff.weekday()]}, {kickoff:%d/%m}'
        if day_label != last_day:
            if last_day:
                lines.append('')
            lines.append(day_label)
            lines.append('')
            last_day = day_label
        lines.append(f"{kickoff:%Hh%M} — {match['home_team']} x {match['away_team']}")
        location = render_location(match)
        if data.get('data_mode') == 'real' and location:
            lines.append(f'Local: {location}')
        elif data.get('data_mode') == 'real':
            lines.append('Local: ainda não informado')
        lines.append(render_broadcast(match))
    if unscheduled_matches:
        if last_day:
            lines.append('')
        lines.append('DATA E HORÁRIO A DEFINIR')
        lines.append('')
        for (index, match) in enumerate(unscheduled_matches):
            if index:
                lines.append('')
            lines.append(f"{match['home_team']} x {match['away_team']}")
            location = render_location(match)
            lines.append(f'Local: {location}' if location else 'Local: ainda não informado')
            lines.append(render_broadcast(match))
    owner_matches = [match for match in round_matches if owner_team.casefold() in {match['home_team'].casefold(), match['away_team'].casefold()}]
    lines.extend(['', f'JOGO DO {owner_team.upper()} NA RODADA', ''])
    if not owner_matches:
        lines.append(f'Nenhum jogo do {owner_team} encontrado nesta rodada.')
    else:
        match = owner_matches[0]
        if match.get('status') == 'scheduled':
            kickoff = datetime.fromisoformat(match['kickoff'])
            lines.append(f'{capitalize_pt(WEEKDAYS_PT[kickoff.weekday()])}, {kickoff:%d/%m}, às {kickoff:%Hh%M}')
        else:
            lines.append('Data e horário ainda não definidos pela CBF')
        lines.append(f"{match['home_team']} x {match['away_team']}")
        location = render_location(match)
        if location:
            lines.append(f'Local: {location}')
        elif match.get('status') == 'unscheduled':
            lines.append('Local: ainda não informado')
        lines.append(render_broadcast(match))
    return '\n'.join(lines).strip()

def parse_schedule_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise FutebolError(f'Data inválida: {value}. Use o formato YYYY-MM-DD.') from exc
    if parsed.isoformat() != value:
        raise FutebolError(f'Data inválida: {value}. Use o formato YYYY-MM-DD.')
    return parsed

def select_matches_by_date(data: dict[str, Any], selected_date: date | str) -> list[dict[str, Any]]:
    target = parse_schedule_date(selected_date) if isinstance(selected_date, str) else selected_date
    matches = [match for match in data['matches'] if match.get('status') == 'scheduled' and match.get('schedule_date') == target.isoformat()]
    return sorted(matches, key=lambda match: (match.get('schedule_time', ''), match['home_team'], match['away_team']))

def local_today(config: dict[str, Any], now: datetime | None = None) -> date:
    timezone = ZoneInfo(config['timezone'])
    current = now.astimezone(timezone) if now else datetime.now(timezone)
    return current.date()

def render_daily_preview(config: dict[str, Any], data: dict[str, Any], selected_date: date | str, today: bool = False) -> str:
    target = parse_schedule_date(selected_date) if isinstance(selected_date, str) else selected_date
    matches = select_matches_by_date(data, target)
    competition = display_competition(data)
    if not matches:
        when = 'hoje' if today else f'em {target:%d/%m/%Y}'
        return f'⚽ Não há jogos no {competition} {when}.'
    owner = config['owner_team']
    owner_matches = [match for match in matches if owner.casefold() in {match['home_team'].casefold(), match['away_team'].casefold()}]
    lines = [f'🏆 *{competition}*', '']
    if owner_matches:
        selected_owner = owner_matches[0]
        owner_heading = f'Hoje tem {owner}' if today else f'{owner} joga em {target:%d/%m/%Y}'
        lines.extend([f"{config.get('owner_marker', '🔴⚫')} *{owner_heading}*", '', render_match_pair(selected_owner), render_match_time(selected_owner)])
        if selected_owner.get('broadcasters'):
            lines.extend(['', f"📺 {format_broadcasters(selected_owner['broadcasters'])}"])
        others = [match for match in matches if match not in owner_matches]
        if others:
            lines.extend(['', '*Outros jogos de hoje*' if today else f'*Outros jogos em {target:%d/%m/%Y}*', ''])
            lines.extend(render_match_line(match) for match in others)
    else:
        heading = '*Hoje no ' + display_competition_name(data) + '*' if today else f'*Jogos em {target:%d/%m/%Y}*'
        lines.extend([heading, ''])
        lines.extend(render_match_line(match) for match in matches)
    return '\n'.join(lines).strip()

def display_competition(data: dict[str, Any]) -> str:
    return f'{display_competition_name(data).upper()} {data["season"]}'

def display_competition_name(data: dict[str, Any]) -> str:
    configured_name = str(data.get('competition_display_name') or '').strip()
    if configured_name:
        return configured_name
    if data['competition'] == 'campeonato_brasileiro_serie_a':
        return 'Brasileirão'
    return str(data['competition']).replace('_', ' ').strip().title()

def render_match_pair(match: dict[str, Any]) -> str:
    return f"{match['home_team']} x {match['away_team']}"

def render_match_time(match: dict[str, Any]) -> str:
    return match['schedule_time'].replace(':', 'h')

def render_match_line(match: dict[str, Any]) -> str:
    return f'{render_match_pair(match)} · {render_match_time(match)}'

def format_broadcasters(broadcasters: list[str]) -> str:
    if len(broadcasters) == 1:
        return broadcasters[0]
    return ', '.join(broadcasters[:-1]) + ' e ' + broadcasters[-1]

def select_owner_match_by_date(config: dict[str, Any], data: dict[str, Any], selected_date: date | str) -> dict[str, Any]:
    matches = select_matches_by_date(data, selected_date)
    owner = config['owner_team'].casefold()
    owner_matches = [match for match in matches if owner in {match['home_team'].casefold(), match['away_team'].casefold()}]
    if not owner_matches:
        target = parse_schedule_date(selected_date) if isinstance(selected_date, str) else selected_date
        raise FutebolError(f"Nenhum jogo do {config['owner_team']} em {target:%d/%m/%Y}.")
    return owner_matches[0]

def render_pregame_alert(match: dict[str, Any], minutes: int) -> str:
    if minutes < 0:
        raise FutebolError('Minutos para o pré-jogo não podem ser negativos.')
    lines = [f'⏰ *Faltam {minutes} minutos*', '', render_match_pair(match), render_match_time(match)]
    if match.get('broadcasters'):
        lines.extend(['', f"📺 {format_broadcasters(match['broadcasters'])}"])
    return '\n'.join(lines)

def select_round(data: dict[str, Any], round_number: int | None=None, current: bool=False) -> int:
    if current:
        return choose_current_round(data['matches'], data['timezone'])
    if round_number is not None:
        return round_number
    return min((int(match['round']) for match in data['matches']))

def enabled_alert_types(config: dict[str, Any]) -> list[str]:
    alert_config = config.get('alerts', {})
    allowed = ['round_overview', 'owner_team_round']
    return [alert_type for alert_type in allowed if alert_config.get(alert_type, {}).get('enabled', False)]

def build_alerts(config: dict[str, Any], data: dict[str, Any], round_number: int | None=None, current: bool=False, generated_at: str | None=None) -> list[dict[str, Any]]:
    selected_round = select_round(data, round_number, current)
    round_matches = [match for match in data['matches'] if int(match['round']) == selected_round]
    if not round_matches:
        raise FutebolError(f'Rodada não encontrada: {selected_round}')
    source = data.get('source', {})
    generated = generated_at or now_iso(config['timezone'])
    alerts = []
    for alert_type in enabled_alert_types(config):
        logical_key = build_logical_key(data, selected_round, alert_type)
        fingerprint = build_content_fingerprint(config, data, selected_round, alert_type)
        alert_id = build_alert_id(logical_key, fingerprint)
        alerts.append({'schema_version': 1, 'alert_id': alert_id, 'logical_key': logical_key, 'content_fingerprint': fingerprint, 'alert_type': alert_type, 'competition': data['competition'], 'season': data['season'], 'round': selected_round, 'owner_team': config['owner_team'], 'data_mode': data.get('data_mode', 'fixture'), 'source_provider': source.get('provider', 'CBF'), 'source_document_sha256': source.get('document_sha256', ''), 'generated_at': generated, 'execution_mode': 'dry_run', 'delivery_status': 'not_sent', 'text': render_alert_text(config, data, selected_round, alert_type)})
    return alerts

def build_logical_key(data: dict[str, Any], round_number: int, alert_type: str) -> str:
    data_mode = data.get('data_mode', 'fixture')
    return f"{data_mode}:{data['competition']}:{data['season']}:{round_number}:{alert_type}"

def build_content_fingerprint(config: dict[str, Any], data: dict[str, Any], round_number: int, alert_type: str) -> str:
    matches = [match for match in data['matches'] if int(match['round']) == round_number]
    if alert_type == 'owner_team_round':
        owner = config['owner_team'].casefold()
        matches = [match for match in matches if owner in {match['home_team'].casefold(), match['away_team'].casefold()}]
    payload = {'alert_type': alert_type, 'competition': data['competition'], 'season': data['season'], 'round': round_number, 'owner_team': config['owner_team'] if alert_type == 'owner_team_round' else '', 'data_mode': data.get('data_mode', 'fixture'), 'matches': [{'reference': match.get('reference', ''), 'home_team': match['home_team'], 'away_team': match['away_team'], 'status': match.get('status'), 'kickoff': match.get('kickoff'), 'schedule_date': match.get('schedule_date'), 'schedule_time': match.get('schedule_time'), 'schedule_note': match.get('schedule_note'), 'venue': match.get('venue', ''), 'city': match.get('city', ''), 'state': match.get('state', ''), 'broadcasters': match.get('broadcasters', [])} for match in sorted(matches, key=match_sort_key)]}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()

def build_alert_id(logical_key: str, content_fingerprint: str) -> str:
    raw = f'{logical_key}:{content_fingerprint}'
    return 'futebol-alert-' + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]

def render_alert_text(config: dict[str, Any], data: dict[str, Any], round_number: int, alert_type: str) -> str:
    if alert_type == 'round_overview':
        return render_round_alert_text(data, round_number)
    if alert_type == 'owner_team_round':
        return render_owner_team_alert_text(config, data, round_number)
    raise FutebolError(f'Tipo de alerta não permitido: {alert_type}')

def render_round_alert_text(data: dict[str, Any], round_number: int) -> str:
    lines = render_preview(data, round_number=round_number).splitlines()
    lines.extend(['', 'Status: DRY-RUN — NÃO ENVIADO'])
    return '\n'.join(lines).strip()

def render_owner_team_alert_text(config: dict[str, Any], data: dict[str, Any], round_number: int) -> str:
    owner_team = config['owner_team']
    round_matches = [match for match in data['matches'] if int(match['round']) == round_number]
    owner_matches = [match for match in round_matches if owner_team.casefold() in {match['home_team'].casefold(), match['away_team'].casefold()}]
    source = data.get('source', {})
    lines = [f'JOGO DO {owner_team.upper()} NA RODADA', '']
    if not owner_matches:
        lines.append(f'Nenhum jogo do {owner_team} encontrado nesta rodada.')
    else:
        match = owner_matches[0]
        if match.get('status') == 'scheduled':
            kickoff = datetime.fromisoformat(match['kickoff'])
            lines.append(f'{capitalize_pt(WEEKDAYS_PT[kickoff.weekday()])}, {kickoff:%d/%m}, às {kickoff:%Hh%M}')
            lines.append(f"{match['home_team']} x {match['away_team']}")
        else:
            lines.append(f"{match['home_team']} x {match['away_team']}")
            lines.append('Data e horário ainda não definidos pela CBF')
        location = render_location(match)
        lines.append(f'Local: {location}' if location else 'Local: ainda não informado')
        lines.append(render_broadcast(match))
    lines.extend(['', f"Fonte: {source.get('provider', 'CBF')}", 'Status: DRY-RUN — NÃO ENVIADO'])
    return '\n'.join(lines).strip()

def load_alert_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {'schema_version': 1, 'entries': []}
    try:
        ledger = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise FutebolError(f'Ledger de alertas inválido: {path}') from exc
    if ledger.get('schema_version') != 1 or not isinstance(ledger.get('entries'), list):
        raise FutebolError(f'Ledger de alertas inválido: {path}')
    return ledger

def write_text_atomic(path: Path, text: str) -> None:
    write_bytes_atomic(path, text.encode('utf-8'))

def update_alert_ledger(alerts: list[dict[str, Any]], observed_at: str, path: Path) -> tuple[dict[str, Any], int, int]:
    ledger = load_alert_ledger(path)
    by_key = {(entry['alert_id'], entry['execution_mode']): entry for entry in ledger['entries']}
    new_count = 0
    existing_count = 0
    for alert in alerts:
        key = (alert['alert_id'], alert['execution_mode'])
        if key in by_key:
            entry = by_key[key]
            entry['last_seen_at'] = observed_at
            entry['occurrences'] = int(entry.get('occurrences', 0)) + 1
            existing_count += 1
            continue
        entry = {'alert_id': alert['alert_id'], 'logical_key': alert['logical_key'], 'content_fingerprint': alert['content_fingerprint'], 'alert_type': alert['alert_type'], 'data_mode': alert['data_mode'], 'season': alert['season'], 'round': alert['round'], 'execution_mode': alert['execution_mode'], 'status': 'dry_run_previewed', 'first_seen_at': observed_at, 'last_seen_at': observed_at, 'occurrences': 1}
        ledger['entries'].append(entry)
        by_key[key] = entry
        new_count += 1
    write_json_atomic(path, ledger)
    return (ledger, new_count, existing_count)

def build_alerts_plan(config: dict[str, Any], data: dict[str, Any], alerts: list[dict[str, Any]], new_count: int, existing_count: int) -> dict[str, Any]:
    selected_round = alerts[0]['round'] if alerts else None
    source = data.get('source', {})
    return {'schema_version': 1, 'data_mode': data.get('data_mode', 'fixture'), 'execution_mode': 'dry_run', 'source': {'provider': source.get('provider', 'CBF'), 'document_sha256': source.get('document_sha256', '')}, 'selection': {'season': data['season'], 'round': selected_round, 'owner_team': config['owner_team']}, 'summary': {'generated': len(alerts), 'new_in_ledger': new_count, 'existing_in_ledger': existing_count, 'sent': 0}, 'alerts': alerts}

def render_alerts_preview(alerts: list[dict[str, Any]]) -> str:
    blocks = []
    for alert in alerts:
        block = [alert['text'], '', f"Alert ID: {alert['alert_id']}", f"Logical key: {alert['logical_key']}", f"Content fingerprint: {alert['content_fingerprint']}"]
        blocks.append('\n'.join(block))
    return '\n\n---\n\n'.join(blocks).strip() + '\n'

def render_broadcast(match: dict[str, Any]) -> str:
    broadcasters = match.get('broadcasters') or []
    if not broadcasters:
        return 'Transmissão ainda não informada'
    if len(broadcasters) == 1:
        return f'Transmissão: {broadcasters[0]}'
    return 'Transmissão: ' + ', '.join(broadcasters[:-1]) + ' e ' + broadcasters[-1]

def render_location(match: dict[str, Any]) -> str:
    venue = match.get('venue') or ''
    city = match.get('city') or ''
    state = match.get('state') or ''
    if venue == 'A Definir' and city == 'A Definir':
        return ''
    if venue and city and state:
        return f'{venue} — {city}/{state}'
    if venue and city:
        return f'{venue} — {city}'
    return venue

def capitalize_pt(value: str) -> str:
    return value[:1].upper() + value[1:].lower()

def cmd_normalize(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.source == 'fixture':
        snapshot = fetch_fixture(config)
        write_fixture_raw(config, snapshot)
        data = normalize_snapshot(config, snapshot)
        path = write_normalized(config, data, 'fixture')
    else:
        result, path, manifest = refresh_real(config)
        data = load_normalized(config, 'real')
        print(f'RESULT: {result}')
        print(f'Manifesto: {manifest_path(config)}')
        print(f'PDF SHA-256: {manifest["pdf_sha256"]}')
        print(f'Páginas: {manifest["page_count"]}')
    print(f'JSON normalizado salvo em: {path}')
    print(f"Partidas normalizadas: {len(data['matches'])}")
    return 0

def cmd_fetch(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.source != 'fixture':
        raise FutebolError('fetch real não é suportado; use normalize --source real.')
    path = write_fixture_raw(config, fetch_fixture(config))
    print(f'Fixture salva em: {path}')
    return 0

def cmd_preview(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.source == 'fixture':
        data = normalize_snapshot(config, fetch_fixture(config))
    else:
        data = load_normalized(config, args.source)
    if args.date or args.today:
        selected_date = local_today(config) if args.today else args.date
        print(render_daily_preview(config, data, selected_date, today=args.today))
    else:
        print(render_preview(data, round_number=args.round, current=args.current))
    return 0

def cmd_pregame(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.source == 'fixture':
        data = normalize_snapshot(config, fetch_fixture(config))
    else:
        data = load_normalized(config, args.source)
    match = select_owner_match_by_date(config, data, args.date)
    minutes = args.minutes if args.minutes is not None else int(config.get('pregame_minutes', 15))
    print(render_pregame_alert(match, minutes))
    return 0

def cmd_run(args: argparse.Namespace) -> int:
    if not args.dry_run:
        raise FutebolError('--dry-run é obrigatório nesta fase.')
    config = load_config(args.config)
    if args.source == 'fixture':
        snapshot = fetch_fixture(config)
        write_fixture_raw(config, snapshot)
        data = normalize_snapshot(config, snapshot)
        path = write_normalized(config, data, 'fixture')
    else:
        result, path, _ = refresh_real(config)
        data = load_normalized(config, 'real')
        print(f'RESULT: {result}')
    print(f'DRY-RUN local concluído. JSON: {path}')
    print('')
    print(render_preview(data, current=True))
    return 0

def cmd_alerts(args: argparse.Namespace) -> int:
    if not args.dry_run:
        raise FutebolError('--dry-run é obrigatório para alertas nesta missão.')
    config = load_config(args.config)
    data = load_normalized(config, args.source)
    generated_at = now_iso(config['timezone'])
    alerts = build_alerts(config, data, round_number=args.round, current=args.current, generated_at=generated_at)
    if not alerts:
        raise FutebolError('Nenhum alerta habilitado na configuração.')
    ensure_alert_dirs(config)
    ledger_path, plan_path, preview_path = alert_paths(config)
    (_, new_count, existing_count) = update_alert_ledger(alerts, generated_at, ledger_path)
    plan = build_alerts_plan(config, data, alerts, new_count, existing_count)
    write_json_atomic(plan_path, plan)
    write_text_atomic(preview_path, render_alerts_preview(alerts))
    print(f'Plano salvo em: {plan_path}')
    print(f'Preview salvo em: {preview_path}')
    print(f'Ledger salvo em: {ledger_path}')
    print(f'Alertas gerados: {len(alerts)}')
    print(f'Novos no ledger dry-run: {new_count}')
    print(f'Já existentes: {existing_count}')
    print('Mensagens enviadas: 0')
    return 0

def validate_normalized_data(data: dict[str, Any]) -> None:
    if data.get('schema_version') != 1 or not isinstance(data.get('matches'), list):
        raise FutebolError('JSON normalizado possui schema mínimo inválido.')
    validate_matches(data['matches'])

def cmd_doctor(args: argparse.Namespace) -> int:
    errors = 0
    def result(status: str, message: str) -> None:
        print(f'{status}: {message}')
    result('OK' if sys.version_info >= (3, 11) else 'ERRO', f'Python {sys.version_info[0]}.{sys.version_info[1]}')
    errors += int(sys.version_info < (3, 11))
    try:
        import orion_football  # noqa: F401
        result('OK', 'pacote orion_football carregado')
    except ImportError:
        result('ERRO', 'pacote orion_football não pôde ser carregado'); errors += 1
    try:
        import pypdf  # noqa: F401
        result('OK', 'pypdf importado')
    except ImportError:
        result('ERRO', 'pypdf não está instalado'); errors += 1
    try:
        config_path = resolve_config_path(args.config)
        config = load_config(config_path, require=True)
        result('OK', f'configuração legível: {config_path}')
        result('OK', f'owner_team: {config["owner_team"]}')
        result('OK', f'timezone: {config["timezone"]}')
        result('OK', f'season: {config["season"]}')
        source_mode = config['source'].get('mode', 'fixture')
        result('OK', f'modo da fonte: {source_mode}')
        result('OK', f'diretório de dados: {data_dir(config)}')
        path = normalized_path(config, source_mode)
        result('OK', f'JSON normalizado: {path}')
        if source_mode == 'real':
            if not path.is_file():
                raise FutebolError(f'JSON normalizado não encontrado: {path}')
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError) as exc:
                raise FutebolError(f'JSON normalizado inválido: {path}') from exc
            validate_normalized_data(data)
            result('OK', f'JSON real legível: {len(data["matches"])} partidas')
        result('OK', 'sem integração de entrega no runtime')
        result('OK', 'diagnóstico offline; nenhuma rede acessada')
    except FutebolError as exc:
        result('ERRO', str(exc)); errors += 1
    return 1 if errors else 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Orion Football Alerts')
    parser.add_argument('--config', help='caminho da configuração local')
    subparsers = parser.add_subparsers(dest='command', required=True)
    fetch_parser = subparsers.add_parser('fetch')
    fetch_parser.add_argument('--source', choices=['fixture', 'real'], default='fixture')
    fetch_parser.set_defaults(func=cmd_fetch)
    doctor_parser = subparsers.add_parser('doctor', help='valida a instalação e os dados locais sem acessar rede')
    doctor_parser.set_defaults(func=cmd_doctor)
    normalize_parser = subparsers.add_parser('normalize')
    normalize_parser.add_argument('--source', choices=['fixture', 'real'], default='fixture')
    normalize_parser.set_defaults(func=cmd_normalize)
    preview_parser = subparsers.add_parser('preview')
    preview_parser.add_argument('--source', choices=['fixture', 'real'], default='fixture')
    preview_group = preview_parser.add_mutually_exclusive_group()
    preview_group.add_argument('--round', type=int)
    preview_group.add_argument('--current', action='store_true')
    preview_group.add_argument('--date', type=parse_schedule_date)
    preview_group.add_argument('--today', action='store_true')
    preview_parser.set_defaults(func=cmd_preview)
    pregame_parser = subparsers.add_parser('pregame', help='gera um alerta local pré-jogo do time favorito')
    pregame_parser.add_argument('--source', choices=['fixture', 'real'], default='fixture')
    pregame_parser.add_argument('--date', type=parse_schedule_date, required=True)
    pregame_parser.add_argument('--minutes', type=int, help='antecedência; usa pregame_minutes da configuração quando omitido')
    pregame_parser.set_defaults(func=cmd_pregame)
    run_parser = subparsers.add_parser('run')
    run_parser.add_argument('--source', choices=['fixture', 'real'], required=True)
    run_parser.add_argument('--dry-run', action='store_true', required=True)
    run_parser.set_defaults(func=cmd_run)
    alerts_parser = subparsers.add_parser('alerts')
    alerts_parser.add_argument('--source', choices=['fixture', 'real'], required=True)
    alerts_group = alerts_parser.add_mutually_exclusive_group(required=True)
    alerts_group.add_argument('--round', type=int)
    alerts_group.add_argument('--current', action='store_true')
    alerts_parser.add_argument('--dry-run', action='store_true', required=True)
    alerts_parser.set_defaults(func=cmd_alerts)
    return parser

def main(argv: list[str] | None=None) -> int:
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        return args.func(args)
    except (FutebolError, ValueError) as exc:
        print(f'ERRO: {exc}', file=sys.stderr)
        return 2
if __name__ == '__main__':
    raise SystemExit(main())
