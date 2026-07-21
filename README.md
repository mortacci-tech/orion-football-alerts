# Orion Football Alerts

CLI e biblioteca Python independentes para obter a tabela oficial da CBF, normalizar partidas e gerar previews e alertas locais de forma determinística. O runtime não usa modelos de linguagem e não inclui entrega por mensageria.

## O que o projeto faz

- localiza e baixa o PDF oficial divulgado pela CBF;
- valida resposta HTTP, tipo de conteúdo, assinatura e tamanho do PDF;
- extrai a camada textual com `pypdf` e normaliza partidas sem inferência probabilística;
- destaca um time favorito configurável em previews diários;
- gera alertas pré-jogo e planos de alerta locais;
- mantém ledger e fingerprints para idempotência;
- publica snapshots apenas depois de validação integral e escrita atômica.

O projeto não agenda execuções, não envia mensagens, não escolhe destinatários e não inventa data, horário, estádio ou transmissão. Entrega por mensageria deve ser integrada externamente por quem usa a biblioteca ou a CLI.

## Requisitos

- Python 3.11 ou superior;
- acesso à internet somente para instalação de dependências e `normalize --source real`;
- um PDF da CBF com camada textual extraível para atualização real.

O `doctor`, os previews sobre dados já normalizados e toda a fixture pública funcionam offline.

## Instalação

```bash
git clone https://github.com/mortacci-tech/orion-football-alerts.git
cd orion-football-alerts
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
```

O entrypoint instalado é `orion-football`. `requirements.txt` espelha apenas a dependência de runtime para fluxos que exigem esse formato; a instalação normal é `pip install .`.

## Início rápido

Crie uma configuração local a partir do exemplo seguro:

```bash
mkdir -p ~/.config/orion-football-alerts
cp config/futebol_config.example.json ~/.config/orion-football-alerts/config.json
orion-football doctor
orion-football preview --source fixture --date 2026-07-16
orion-football pregame --source fixture --date 2026-07-23
```

Também é possível indicar outro arquivo com `--config /caminho/config.json` ou com a variável `ORION_FOOTBALL_CONFIG`.

## Configuração

O arquivo [config/futebol_config.example.json](config/futebol_config.example.json) documenta:

- `competition` e `competition_display_name`: identificador e nome exibido;
- `season`: temporada consultada;
- `owner_team`: time favorito destacado;
- `timezone`: timezone IANA usado para datas e horários;
- `pregame_minutes`: antecedência padrão do alerta pré-jogo;
- `data_dir`: diretório local de snapshots, estado e manifesto;
- `alerts`: tipos de alertas locais habilitados;
- `source`: modo, URLs oficiais, timeout, limite de download e faixa plausível de partidas.

Os horários são preservados no timezone configurado. Campos ausentes na fonte continuam ausentes ou são marcados como não definidos; o programa não completa informações por conta própria.

## Comandos

Todos os comandos aceitam `--config` antes do subcomando.

### `doctor`

Valida offline o Python, imports, configuração e, no modo `real`, o snapshot local existente.

```bash
orion-football doctor
```

### `fetch`

Materializa a fixture pública no diretório de dados. O download real é deliberadamente concentrado em `normalize --source real` para que a validação e a publicação sejam uma única operação protegida.

```bash
orion-football fetch --source fixture
```

### `normalize`

Normaliza a fixture ou atualiza os dados a partir da fonte oficial.

```bash
orion-football normalize --source fixture
orion-football normalize --source real
```

Uma atualização real termina em um destes estados:

- `UPDATED`: conteúdo esportivo mudou e o snapshot foi substituído;
- `UNCHANGED`: conteúdo idêntico; o arquivo ativo não é regravado;
- `FAILED_PRESERVED`: falha com snapshot anterior preservado;
- `NO_PREVIOUS_DATA`: falha sem snapshot válido anterior.

Não há retry automático. Em caso de falha, nenhuma tabela parcial é publicada.

### `preview`

Gera resumo por rodada, rodada atual, data ou dia local atual. O time definido em `owner_team` recebe destaque quando joga.

```bash
orion-football preview --source fixture --round 19
orion-football preview --source fixture --date 2026-07-16
orion-football preview --source fixture --today
orion-football preview --source real --current
```

### `pregame`

Gera texto local para o jogo do time favorito na data indicada. `--minutes` sobrescreve `pregame_minutes`.

```bash
orion-football pregame --source fixture --date 2026-07-23
orion-football pregame --source fixture --date 2026-07-23 --minutes 10
```

### `run`

Executa normalização e preview local. O modo dry-run é obrigatório.

```bash
orion-football run --source fixture --dry-run
orion-football run --source real --dry-run
```

### `alerts`

Gera plano, preview e ledger locais a partir de um snapshot já normalizado. O ledger usa chave lógica e fingerprint de conteúdo para tornar repetições observáveis e idempotentes.

```bash
orion-football normalize --source fixture
orion-football alerts --source fixture --round 19 --dry-run
orion-football alerts --source fixture --current --dry-run
```

## Fonte oficial e atualização segura

A fonte primária é a Confederação Brasileira de Futebol (CBF). No modo real, o programa acessa apenas hosts CBF aprovados, localiza o PDF configurado, valida o download e extrai todas as páginas com `pypdf`. O candidato completo passa por validações de schema, duplicidade, campos essenciais e quantidade plausível antes da publicação.

A comparação usa SHA-256 canônico sem metadados voláteis. A escrita do snapshot e do manifesto usa arquivo temporário no mesmo filesystem, `flush`, `fsync` e `os.replace`. O manifesto `brasileirao_serie_a_<ano>_real_source_manifest.json` registra URLs, HTTP, tipo de conteúdo, tamanho, hashes, páginas, quantidade de partidas, resultado e erro resumido.

## Arquitetura

- `src/orion_football/`: pacote, CLI e recursos públicos instaláveis;
- `config/`: configuração de exemplo;
- `fixtures/`: amostra pública usada em testes offline;
- `tests/`: suíte `unittest` determinística;
- `docs/ARCHITECTURE.md`: fluxo de dados e limites do runtime.

O pacote é independente: configuração, dados, estado e ledger ficam no diretório escolhido pelo usuário. Veja [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) para o fluxo resumido.

## Testes

```bash
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall -q src tests
python -m build
```

A CI executa instalação normal, testes, compilação e build nas versões de Python suportadas, sem downloads da CBF e sem serviços externos.

## Limitações

- A extração requer camada textual no PDF.
- Mudanças futuras no formato da CBF podem exigir atualização do parser.
- A fixture cobre cenários de teste e não representa uma temporada completa.
- O projeto gera conteúdo e estado locais; agendamento e entrega são responsabilidades de integrações externas.
- Os nomes e direitos sobre competições, clubes e fontes pertencem aos respectivos titulares.

Quando o formato da fonte muda, a falha é fechada: o candidato inválido não substitui o último snapshot válido.

## Privacidade e segurança

O repositório não distribui credenciais, contatos, destinatários, dados pessoais, documentos baixados, logs, estado ou ledgers de produção. Configurações locais, manifestos de runtime, PDFs e JSONs reais são ignorados pelo Git. Consulte [SECURITY.md](SECURITY.md) para relatar uma vulnerabilidade.

## Licença, contribuição e suporte

Distribuído sob a [licença MIT](LICENSE). A versão atual é `0.1.0`, uma versão inicial alpha; consulte [CHANGELOG.md](CHANGELOG.md).

Contribuições devem preservar determinismo, privacidade e testes offline. Leia [CONTRIBUTING.md](CONTRIBUTING.md). Para suporte, bugs ou propostas, abra uma [issue no GitHub](https://github.com/mortacci-tech/orion-football-alerts/issues).
