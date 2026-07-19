# Orion Football Alerts

Projeto independente do Orion para ler uma tabela de futebol, normalizar partidas e gerar previews e alertas determinísticos. O runtime não usa LLM.

## Funcionalidades atuais

- leitura de fixture HTML local e fonte oficial CBF em modo `real`;
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

`fixture` é o padrão seguro, offline e determinístico. `real` acessa somente a URL HTTPS oficial configurada da CBF, aplica timeout, limite de download, validação HTTP/conteúdo e registra URL, captura, formato, tamanho e SHA-256. A estrutura da CBF pode mudar; nesse caso a execução falha sem gerar tabela parcial.

```bash
PYTHONPATH=src python3 -m orion_football.futebol normalize --source fixture
PYTHONPATH=src python3 -m orion_football.futebol preview --source fixture --round 19
PYTHONPATH=src python3 -m orion_football.futebol preview --source fixture --date 2026-07-16
PYTHONPATH=src python3 -m orion_football.futebol preview --source fixture --today
PYTHONPATH=src python3 -m orion_football.futebol alerts --source fixture --round 19 --dry-run
PYTHONPATH=src python3 -m orion_football.futebol normalize --source real
PYTHONPATH=src python3 -m orion_football.futebol preview --source real --current
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
```

## Limitações

Não há envio de WhatsApp, OpenClaw, agendamento, retry automático ou instalador. Alertas permanecem exclusivamente em dry-run. Campos ausentes na fonte aparecem vazios ou como “ainda não informado”; não são inventados. A fonte real depende do contrato público atual da CBF e pode exigir atualização do parser.

## Segurança e privacidade

Nenhuma credencial, token, telefone, ledger operacional, estado, log ou documento interno é distribuído. Não há destino de WhatsApp configurado.

## Roadmap

1. acompanhar mudanças no formato oficial da CBF; 2. manter fixtures e validações offline; 3. definir posteriormente uma entrega, em missão separada.
