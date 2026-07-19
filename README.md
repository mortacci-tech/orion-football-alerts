# Orion Football Alerts

Projeto independente do Orion para ler uma tabela de futebol, normalizar partidas e gerar previews e alertas determinísticos. O runtime não usa LLM.

## Funcionalidades atuais

- leitura de fixture HTML local;
- normalização de partidas, rodada, horário, local e transmissão;
- seleção de rodada e do time favorito;
- preview textual;
- fingerprint e idempotência genéricos em ledger local;
- interface de entrega abstrata: WhatsApp não vem configurado.

## Arquitetura

O pacote `src/orion_football` contém a lógica determinística. `config` traz somente exemplo, `fixtures` contém dados sintéticos de teste e `tests` usa exclusivamente arquivos locais.

## Requisitos e instalação

Python 3.11+ é recomendado.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Configuração

Copie `config/futebol_config.example.json` para um arquivo local ignorado pelo Git e ajuste a fonte conforme os termos do provedor. A primeira versão pública usa fixture; nenhuma credencial é necessária.

## CLI local

Esta versão usa exclusivamente a fixture HTML sintética incluída no repositório. Ainda não acessa a CBF real, não envia WhatsApp e não integra OpenClaw. Os alertas são somente dados em dry-run.

```bash
PYTHONPATH=src python3 -m orion_football.futebol normalize
PYTHONPATH=src python3 -m orion_football.futebol preview --round 19
PYTHONPATH=src python3 -m orion_football.futebol preview --current
PYTHONPATH=src python3 -m orion_football.futebol preview --date 2026-07-16
PYTHONPATH=src python3 -m orion_football.futebol preview --today
PYTHONPATH=src python3 -m orion_football.futebol alerts --round 19 --dry-run
PYTHONPATH=src python3 -m orion_football.futebol alerts --current --dry-run
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
```

## Limitações

Não há fonte CBF real, envio de WhatsApp, OpenClaw, agendamento, retry ou instalação. A fixture é sintética e os alertas permanecem em dry-run.

## Segurança e privacidade

Nenhuma credencial, token, telefone, ledger operacional, estado, log ou documento interno é distribuído. Não há destino de WhatsApp configurado.

## Roadmap

1. adicionar adaptadores de fonte com contratos testáveis; 2. documentar uma interface de entrega abstrata; 3. ampliar fixtures e validações sem incluir dados pessoais.
