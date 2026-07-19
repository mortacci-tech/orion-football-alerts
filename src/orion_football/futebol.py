from __future__ import annotations
import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR.parent.parent / 'config' / 'futebol_config.example.json'
FIXTURE_PATH = BASE_DIR.parent.parent / 'fixtures' / 'cbf_tabela_detalhada_sample.html'
ALERT_LEDGER_PATH = BASE_DIR.parent.parent / 'state' / 'alerts.json'
ALERTS_PLAN_PATH = BASE_DIR.parent.parent / 'state' / 'alerts_plan.json'
ALERTS_PREVIEW_PATH = BASE_DIR.parent.parent / 'state' / 'alerts_preview.txt'
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

def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FutebolError(f'Configuração não encontrada: {CONFIG_PATH}')
    return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))

def ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)

def ensure_alert_dirs() -> None:
    ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

def now_iso(tz_name: str) -> str:
    return datetime.now(ZoneInfo(tz_name)).isoformat(timespec='seconds')

def fetch_fixture(config: dict[str, Any]) -> SourceSnapshot:
    if not FIXTURE_PATH.exists():
        raise FutebolError(f'Fixture não encontrada: {FIXTURE_PATH}')
    tz_name = config['timezone']
    return SourceSnapshot(provider='CBF', url=str(FIXTURE_PATH), status='fixture', fetched_at=now_iso(tz_name), html_text=FIXTURE_PATH.read_text(encoding='utf-8'), raw_path=None)

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
    return {'schema_version': 1, 'data_mode': 'fixture', 'competition': config['competition'], 'season': config['season'], 'timezone': config['timezone'], 'source': {'provider': source.provider, 'url': source.url, 'status': source.status, 'fetched_at': source.fetched_at, 'raw_path': str(source.raw_path) if source.raw_path else ''}, 'matches': deduped}

def build_summary(matches: list[dict[str, Any]]) -> dict[str, int]:
    return {'total_matches': len(matches), 'scheduled_matches': sum((1 for match in matches if match.get('status') == 'scheduled')), 'unscheduled_matches': sum((1 for match in matches if match.get('status') == 'unscheduled'))}

def validate_matches(matches: list[dict[str, Any]]) -> None:
    if not matches:
        raise FutebolError('Normalização não gerou partidas.')
    ids = [match['match_id'] for match in matches]
    if len(ids) != len(set(ids)):
        raise FutebolError('Partidas duplicadas detectadas por match_id.')
    for match in matches:
        for field in ['round', 'home_team', 'away_team', 'status']:
            if match.get(field) in (None, ''):
                raise FutebolError(f'Campo essencial ausente após normalização: {field}')
        if match['status'] == 'scheduled':
            if not match.get('kickoff'):
                raise FutebolError('Partida scheduled sem kickoff.')
            parsed = datetime.fromisoformat(match['kickoff'])
            if parsed.tzinfo is None:
                raise FutebolError(f"Data sem timezone: {match['kickoff']}")
            if not match.get('schedule_date') or not match.get('schedule_time'):
                raise FutebolError('Partida scheduled sem schedule_date/schedule_time.')
        elif match['status'] == 'unscheduled':
            if match.get('kickoff') is not None:
                raise FutebolError('Partida unscheduled não pode possuir kickoff.')
            if not match.get('schedule_note'):
                raise FutebolError('Partida unscheduled sem schedule_note.')
        else:
            raise FutebolError(f"Status de partida inválido: {match['status']}")

def match_sort_key(match: dict[str, Any]) -> tuple[Any, ...]:
    return (int(match['round']), match.get('kickoff') or '9999-12-31T23:59:59-03:00', match['home_team'], match['away_team'])

def normalized_path(config: dict[str, Any], source: str='fixture') -> Path:
    suffix = 'real' if source == 'real' else 'fixture'
    return NORMALIZED_DIR / f"brasileirao_serie_a_{config['season']}_{suffix}.json"

def write_normalized(config: dict[str, Any], data: dict[str, Any], source: str='fixture') -> Path:
    ensure_dirs()
    path = normalized_path(config, source)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path

def write_fixture_raw(snapshot: SourceSnapshot) -> Path:
    ensure_dirs()
    raw_path = RAW_DIR / 'cbf_tabela_detalhada_fixture.html'
    raw_path.write_text(snapshot.html_text, encoding='utf-8')
    return raw_path

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

def render_preview(data: dict[str, Any], round_number: int | None=None, current: bool=False) -> str:
    matches = data['matches']
    if current:
        round_number = choose_current_round(matches, data['timezone'])
    if round_number is None:
        round_number = min((int(match['round']) for match in matches))
    round_matches = [match for match in matches if int(match['round']) == round_number]
    if not round_matches:
        raise FutebolError(f'Rodada não encontrada: {round_number}')
    owner_team = load_config()['owner_team']
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
    if not matches:
        return f'⚽ NÃO HÁ JOGOS EM {target:%d/%m/%Y}'
    owner = config['owner_team']
    owner_matches = [match for match in matches if owner.casefold() in {match['home_team'].casefold(), match['away_team'].casefold()}]
    date_label = 'HOJE' if today else f'{target:%d/%m/%Y}'
    lines = [f'🔴⚫ {date_label} TEM {owner.upper()}' if owner_matches and today else f'🔴⚫ {owner.upper()} EM {target:%d/%m/%Y}' if owner_matches else f'⚽ JOGOS DE {date_label}', '']
    selected = owner_matches + [match for match in matches if match not in owner_matches]
    if owner_matches:
        selected_owner = owner_matches[0]
        lines.append(f"{selected_owner['schedule_time'].replace(':', 'h')} — {selected_owner['home_team']} x {selected_owner['away_team']}")
        location = render_location(selected_owner)
        if location:
            lines.append(f'📍 {location}')
        if selected_owner.get('broadcasters'):
            lines.append(f"📺 {', '.join(selected_owner['broadcasters'])}")
        others = [match for match in matches if match not in owner_matches]
        if others:
            lines.extend(['', '⚽ OUTROS JOGOS', ''])
            selected = others
        else:
            selected = []
    for match in selected:
        lines.append(f"{match['schedule_time'].replace(':', 'h')} — {match['home_team']} x {match['away_team']}")
    return '\n'.join(lines).strip()

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

def find_owner_team_match(config: dict[str, Any], data: dict[str, Any], round_number: int) -> dict[str, Any]:
    owner = config['owner_team'].casefold()
    matches = [match for match in data['matches'] if int(match['round']) == round_number and owner in {match['home_team'].casefold(), match['away_team'].casefold()}]
    if not matches:
        raise FutebolError(f"Nenhum jogo do {config['owner_team']} encontrado na rodada {round_number}.")
    return matches[0]

def render_whatsapp_owner_team_message(config: dict[str, Any], data: dict[str, Any], round_number: int) -> str:
    match = find_owner_team_match(config, data, round_number)
    if match.get('status') == 'scheduled':
        kickoff = datetime.fromisoformat(match['kickoff'])
        when = f'{capitalize_pt(WEEKDAYS_PT[kickoff.weekday()])}, {kickoff:%d/%m}, às {kickoff:%Hh%M}'
    else:
        when = 'Data e horário ainda não definidos pela CBF'
    location = render_location(match) or 'ainda não informado'
    broadcast = render_broadcast(match).replace('Transmissão: ', '')
    return '\n'.join(['🔴⚫ PRÓXIMO JOGO DO FLAMENGO', '', when, f"{match['home_team']} x {match['away_team']}", '', f'📍 {location}', f'📺 {broadcast}', '', f"Brasileirão {data['season']} — {round_number}ª rodada", 'Fonte: CBF']).strip()

def load_alert_ledger(path: Path=ALERT_LEDGER_PATH) -> dict[str, Any]:
    if not path.exists():
        return {'schema_version': 1, 'entries': []}
    try:
        ledger = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise FutebolError(f'Ledger de alertas inválido: {path}') from exc
    if ledger.get('schema_version') != 1 or not isinstance(ledger.get('entries'), list):
        raise FutebolError(f'Ledger de alertas inválido: {path}')
    return ledger

def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + '.tmp')
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp_path, path)

def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + '.tmp')
    tmp_path.write_text(text, encoding='utf-8')
    os.replace(tmp_path, path)

def update_alert_ledger(alerts: list[dict[str, Any]], observed_at: str, path: Path=ALERT_LEDGER_PATH) -> tuple[dict[str, Any], int, int]:
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
    config = load_config()
    if args.source == 'fixture':
        snapshot = fetch_fixture(config)
        write_fixture_raw(snapshot)
        data = normalize_snapshot(config, snapshot)
        path = write_normalized(config, data, 'fixture')
    else:
        pdf_source = extract_pdf_text(download_pdf_from_article(config))
        data = normalize_pdf_real(config, pdf_source)
        path = write_normalized(config, data, 'real')
    print(f'JSON normalizado salvo em: {path}')
    print(f"Partidas normalizadas: {len(data['matches'])}")
    return 0

def cmd_preview(args: argparse.Namespace) -> int:
    config = load_config()
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

def cmd_run(args: argparse.Namespace) -> int:
    if not args.dry_run:
        raise FutebolError('--dry-run é obrigatório nesta fase.')
    config = load_config()
    if args.source == 'fixture':
        snapshot = fetch_fixture(config)
        write_fixture_raw(snapshot)
        data = normalize_snapshot(config, snapshot)
        path = write_normalized(config, data, 'fixture')
    else:
        pdf_source = extract_pdf_text(download_pdf_from_article(config))
        data = normalize_pdf_real(config, pdf_source)
        path = write_normalized(config, data, 'real')
    print(f'DRY-RUN local concluído. JSON: {path}')
    print('')
    print(render_preview(data, current=True))
    return 0

def cmd_alerts(args: argparse.Namespace) -> int:
    if not args.dry_run:
        raise FutebolError('--dry-run é obrigatório para alertas nesta missão.')
    config = load_config()
    data = load_normalized(config, args.source)
    generated_at = now_iso(config['timezone'])
    alerts = build_alerts(config, data, round_number=args.round, current=args.current, generated_at=generated_at)
    if not alerts:
        raise FutebolError('Nenhum alerta habilitado na configuração.')
    ensure_alert_dirs()
    (_, new_count, existing_count) = update_alert_ledger(alerts, generated_at)
    plan = build_alerts_plan(config, data, alerts, new_count, existing_count)
    write_json_atomic(ALERTS_PLAN_PATH, plan)
    write_text_atomic(ALERTS_PREVIEW_PATH, render_alerts_preview(alerts))
    print(f'Plano salvo em: {ALERTS_PLAN_PATH}')
    print(f'Preview salvo em: {ALERTS_PREVIEW_PATH}')
    print(f'Ledger salvo em: {ALERT_LEDGER_PATH}')
    print(f'Alertas gerados: {len(alerts)}')
    print(f'Novos no ledger dry-run: {new_count}')
    print(f'Já existentes: {existing_count}')
    print('WhatsApp enviado: NÃO')
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Módulo Futebol Orion 2.0')
    subparsers = parser.add_subparsers(dest='command', required=True)
    fetch_parser = subparsers.add_parser('fetch')
    fetch_parser.add_argument('--source', choices=['fixture', 'real'], default='fixture')
    fetch_parser.set_defaults(func=lambda _args: (_ for _ in ()).throw(FutebolError('Download automático não está habilitado nesta missão; use a fixture local.')))
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
    send_parser = subparsers.add_parser('send')
    send_parser.add_argument('--source', choices=['real'], required=True)
    send_group = send_parser.add_mutually_exclusive_group(required=True)
    send_group.add_argument('--current', action='store_true')
    send_group.add_argument('--round', type=int)
    send_parser.add_argument('--alert-type', choices=['round_overview', 'owner_team_round'], required=True)
    send_parser.add_argument('--self-only', action='store_true', required=True)
    send_parser.add_argument('--confirm', required=True)
    send_parser.set_defaults(func=lambda _args: (_ for _ in ()).throw(FutebolError('Envio não está habilitado nesta missão.')))
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
