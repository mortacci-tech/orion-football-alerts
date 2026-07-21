# Integração com um agente

Este projeto fornece o motor determinístico de futebol. Ele consulta e normaliza a tabela oficial da CBF e gera textos de preview e pré-jogo. O envio por WhatsApp, o agendamento e a escolha do destinatário ficam sob responsabilidade do agente que integrar o módulo.

## 1. Instale o módulo no mesmo ambiente do agente

```bash
git clone https://github.com/mortacci-tech/orion-football-alerts.git
cd orion-football-alerts
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
```

Confirme a instalação:

```bash
orion-football doctor
```

## 2. Crie a configuração local

```bash
mkdir -p ~/.config/orion-football-alerts
cp config/futebol_config.example.json ~/.config/orion-football-alerts/config.json
```

Edite somente a cópia local e ajuste, no mínimo:

- `season`: temporada;
- `owner_team`: time acompanhado;
- `timezone`: normalmente `America/Sao_Paulo`;
- `pregame_minutes`: antecedência do alerta;
- `source.mode`: use `real` para a fonte oficial e `fixture` apenas para testes.

A configuração local não deve ser adicionada ao Git.

## 3. Atualize a tabela oficial

```bash
orion-football normalize --source real
```

Resultados possíveis:

- `UPDATED`: novos dados foram publicados;
- `UNCHANGED`: os dados oficiais não mudaram;
- `FAILED_PRESERVED`: houve falha e o último snapshot válido foi mantido;
- `NO_PREVIOUS_DATA`: houve falha e ainda não existe snapshot válido.

O agente deve tratar os dois últimos resultados como falha e não enviar conteúdo parcial.

## 4. Gere conteúdo para o agente entregar

Resumo do dia:

```bash
orion-football preview --source real --today
```

Rodada atual:

```bash
orion-football preview --source real --current
```

Alerta pré-jogo:

```bash
orion-football pregame --source real --date AAAA-MM-DD --minutes 10
```

O texto é escrito em `stdout`. O agente deve capturar essa saída e encaminhá-la pelo canal configurado. Quando o comando não produzir mensagem útil, não envie mensagem vazia.

## 5. Contrato recomendado para qualquer agente

A integração deve:

1. executar o comando como processo local;
2. verificar o código de saída;
3. capturar `stdout` e `stderr` separadamente;
4. enviar somente quando o código de saída indicar sucesso e `stdout` contiver texto;
5. registrar a falha localmente sem inventar dados;
6. manter destinatários, credenciais e tokens fora deste repositório;
7. usar uma trava ou ledger para impedir duplicidade de envio.

Exemplo em Python:

```python
import subprocess

result = subprocess.run(
    ["orion-football", "preview", "--source", "real", "--today"],
    text=True,
    capture_output=True,
    check=False,
)

if result.returncode != 0:
    raise RuntimeError(result.stderr.strip() or "Falha no módulo de futebol")

message = result.stdout.strip()
if message:
    # Substitua pela função de envio do seu agente.
    send_message(message)
```

## 6. Agendamento sugerido

Um fluxo comum é:

- atualizar a fonte oficial antes do resumo diário;
- gerar o resumo uma vez por dia;
- verificar o alerta pré-jogo periodicamente;
- manter idempotência para que a mesma partida não gere mensagens duplicadas.

O mecanismo de agendamento depende do ambiente do agente. No macOS, pode ser `launchd`; no Linux, `systemd` ou `cron`; em outros agentes, use o agendador nativo.

## 7. Teste antes de ativar a entrega

Use primeiro a fixture pública:

```bash
orion-football doctor
orion-football normalize --source fixture
orion-football preview --source fixture --date 2026-07-16
orion-football pregame --source fixture --date 2026-07-23 --minutes 10
python -m unittest discover -s tests -p 'test_*.py'
```

Somente depois troque para `--source real` e conecte a saída ao canal do agente.

## Limite do projeto

Este repositório não inclui conexão pronta com WhatsApp, OpenClaw ou outro mensageiro. Isso evita distribuir credenciais, contatos e regras privadas de entrega. Ele entrega uma interface local estável para que cada agente faça essa integração com segurança.
