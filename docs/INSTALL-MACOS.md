# Instalação manual no macOS

## Requisitos

É necessário macOS, Python 3.11 ou superior e acesso à internet somente para instalar o pacote e, quando desejado, baixar a fonte oficial da CBF. O projeto não instala OpenClaw, WhatsApp ou agendamento.

Abra o Terminal e clone o repositório:

```bash
git clone https://github.com/mortacci-tech/orion-football-alerts.git
cd orion-football-alerts
python3 -m venv .venv
. .venv/bin/activate
pip install .
```

## Configuração e diagnóstico

Crie sua configuração local (sem telefone, token ou segredo):

```bash
orion-football init --owner-team Flamengo --timezone America/Sao_Paulo --season 2026
orion-football doctor
```

O arquivo fica em `~/Library/Application Support/Orion Football/config.json`. Os dados ficam em `~/Library/Application Support/Orion Football/data/`, separados em `raw/`, `normalized/`, `state/` e `backups/`. Use `--config /caminho/config.json` ou `ORION_FOOTBALL_CONFIG` quando quiser outro arquivo; o argumento tem prioridade.

`init` começa em modo `fixture`, não acessa a internet e não substitui um arquivo existente. Para substituir conscientemente, use `--force`; um backup com timestamp será criado antes.

## Teste e fonte real

```bash
orion-football normalize --source fixture
orion-football preview --source fixture --round 19
orion-football normalize --source real
orion-football preview --source real --round 19
orion-football preview --source real --date 2026-07-16
orion-football preview --source real --today
orion-football alerts --source fixture --round 19 --dry-run
```

Fixture, `init`, `doctor` e previews não acessam a rede. Apenas `normalize --source real` baixa e valida o PDF oficial da CBF. O parser falha quando a fonte não pode ser validada e não inventa data, horário, local ou transmissão.

## Atualizar e remover

Para atualizar manualmente, entre na pasta do projeto, ative o ambiente virtual e execute `git pull` seguido de `pip install .`.

Para remover somente o pacote:

```bash
pip uninstall orion-football-alerts
```

Os dados ficam separados e não são removidos pelo `pip uninstall`. Para removê-los, confirme o caminho exato e apague manualmente apenas `~/Library/Application Support/Orion Football/`; essa ação remove configuração, PDFs, JSONs, ledger e backups locais. Não há desinstalador automático.

## Limitações atuais

Não há OpenClaw, WhatsApp, envio real, agendamento, LaunchAgent, alerta temporal, fallback GE, licença definitiva, publicação pública ou release. Alertas são exclusivamente dry-run e o repositório continua sendo a forma de instalação desta missão.
