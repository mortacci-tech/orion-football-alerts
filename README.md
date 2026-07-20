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

## Comandos usando fixture

```bash
PYTHONPATH=src python3 -c 'from orion_football import futebol; c=futebol.load_config(); d=futebol.normalize_snapshot(c, futebol.fetch_fixture(c)); print(futebol.render_preview(d, round_number=19))'
PYTHONPATH=src python3 -m orion_football.futebol preview --source fixture --date 2026-07-16
PYTHONPATH=src python3 -m orion_football.futebol pregame --source fixture --date 2026-07-23 --minutes 10
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
```

`preview --date` e `preview --today` geram o resumo diário. Quando o time
favorito configurado joga, ele aparece em destaque. `pregame` seleciona esse
jogo pela data e gera uma mensagem curta com os minutos informados. Todos os
comandos são locais, determinísticos e não enviam mensagens.

## Limitações

Não há download automático, sender real, agendamento, retry ou integração com o Orion. Fontes externas podem mudar; o usuário deve respeitar os termos de uso da fonte.

## Segurança e privacidade

Nenhuma credencial, token, telefone, ledger operacional, estado, log ou documento interno é distribuído. Não há destino de WhatsApp configurado.

## Roadmap

1. adicionar adaptadores de fonte com contratos testáveis; 2. documentar uma interface de entrega abstrata; 3. ampliar fixtures e validações sem incluir dados pessoais.
