# Orion Football Alerts

Projeto independente do Orion para ler uma tabela de futebol, normalizar partidas e gerar previews e alertas determinísticos. O runtime não usa LLM.

## Funcionalidades atuais

- leitura offline da fixture e fonte real pelo PDF oficial da CBF;
- normalização de partidas, rodada, horário, local e transmissão;
- seleção de rodada e do time favorito;
- preview textual;
- fingerprint e idempotência genéricos em ledger local;
- interface de entrega abstrata: WhatsApp não vem configurado.

## Fonte CBF

O modo `real` acessa o artigo oficial configurado, procura nele um PDF cujo nome corresponda ao padrão configurado e, se a descoberta falhar, usa a URL direta oficial de fallback. Apenas `cbf.com.br`, `www.cbf.com.br` e o blob oficial da CBF são aceitos. O PDF é validado por HTTP, Content-Type/assinatura `%PDF`, timeout, limite de bytes e SHA-256; depois o `pypdf` extrai o texto de todas as páginas e o parser determinístico valida as partidas.

`fixture` continua sendo o padrão seguro, local e offline. A fixture textual `fixtures/cbf_tabela_detalhada_19_24_sample.txt` representa o formato do PDF; a fixture HTML legada permanece para compatibilidade dos testes existentes. O modo real baixa uma vez no `normalize` e grava JSON local; previews reais somente reutilizam esse JSON e não baixam novamente.

## Arquitetura

O pacote `src/orion_football` contém a lógica determinística. `config` traz somente exemplo, `fixtures` contém dados sintéticos de teste e `tests` usa exclusivamente arquivos locais.

## Requisitos e instalação

Python 3.11+ é recomendado. A dependência de extração é `pypdf==6.12.1`.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install .
```

O pacote instala o comando `orion-football`. Para o passo a passo no macOS, consulte [docs/INSTALL-MACOS.md](docs/INSTALL-MACOS.md).

## Configuração

Crie a configuração pessoal com `orion-football init --owner-team Flamengo --timezone America/Sao_Paulo --season 2026` e valide com `orion-football doctor`. O padrão é `~/Library/Application Support/Orion Football/config.json`; os dados ficam em `~/Library/Application Support/Orion Football/data/`. Não há token, telefone ou credencial necessária.

## CLI local

`fixture` é o padrão seguro, offline e determinístico. `real` acessa somente a URL HTTPS oficial configurada da CBF, aplica timeout, limite de download, validação HTTP/conteúdo e registra URL, captura, formato, tamanho e SHA-256. A estrutura da CBF pode mudar; nesse caso a execução falha sem gerar tabela parcial.

```bash
orion-football --help
orion-football normalize --source fixture
orion-football preview --source fixture --round 19
orion-football alerts --source fixture --round 19 --dry-run
python3 -m orion_football.futebol preview --source fixture --round 19
python3 -m unittest discover -s tests -p 'test_*.py'
```

## Limitações

Não há WhatsApp, OpenClaw, agendamento, retry automático, LaunchAgent ou instalador automático. Alertas permanecem exclusivamente em dry-run. O produto ainda não está pronto para o público. Campos ausentes aparecem vazios ou como “ainda não informado”; não são inventados.

## Segurança e privacidade

Nenhuma credencial, token, telefone, ledger operacional, estado, log ou documento interno é distribuído. Não há destino de WhatsApp configurado.

## Roadmap

1. acompanhar mudanças no formato oficial da CBF; 2. manter fixtures e validações offline; 3. definir posteriormente uma entrega, em missão separada.
