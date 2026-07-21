# Orion Football Alerts

Projeto independente do Orion para ler uma tabela de futebol, normalizar partidas e gerar previews e alertas determinísticos. O runtime não usa LLM.

## Funcionalidades atuais

- leitura de fixture HTML local e atualização pelo PDF oficial da CBF;
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

Copie `config/futebol_config.example.json` para um arquivo local ignorado pelo Git e ajuste a fonte e `competition_display_name` conforme os termos do provedor. A primeira versão pública usa fixture; nenhuma credencial é necessária.

O comando instalado é `orion-football`. Por padrão ele lê
`~/Library/Application Support/Orion Football/config.json`; use `--config` ou
`ORION_FOOTBALL_CONFIG` para outra configuração. Os JSONs normalizados ficam em
`data_dir/normalized/`. `orion-football doctor` é estritamente offline: valida
a configuração e, no modo `real`, apenas lê o JSON local já normalizado.

## Atualização real protegida

`orion-football normalize --source real` baixa o artigo oficial uma vez, localiza
o PDF configurado, valida HTTP, tipo de conteúdo, assinatura e tamanho, extrai
todas as páginas com `pypdf` e executa o parser determinístico. O candidato é
validado integralmente antes de qualquer publicação. A troca usa arquivo
temporário no mesmo filesystem, `flush`, `fsync` e `os.replace`.

O conteúdo esportivo é comparado por SHA-256 canônico, sem metadados voláteis:

- `UPDATED`: houve mudança e o snapshot foi substituído atomicamente;
- `UNCHANGED`: não houve mudança e o JSON ativo, inclusive seu `mtime`, não é regravado;
- `FAILED_PRESERVED`: houve falha e o último snapshot válido permanece intacto;
- `NO_PREVIOUS_DATA`: houve falha e não existia snapshot válido anterior.

Falhas preservadas e ausência de dados retornam erro operacional; não são
mascaradas como sucesso. O manifesto fica em
`data_dir/state/brasileirao_serie_a_<ano>_real_source_manifest.json` e registra
URLs, HTTP, Content-Type, tamanho, SHA-256 do PDF e dos JSONs canônicos, páginas,
partidas, resultado, erro resumido e caminho ativo. Nenhum telefone ou segredo é
registrado.

Comando manual:

```bash
orion-football normalize --source real
orion-football doctor
```

Sem rede, o refresh falha de forma observável e preserva o snapshot anterior.
Se o formato da CBF mudar, examine o manifesto, congele uma amostra sem dados
sensíveis, ajuste o parser e valide offline antes de tentar novamente. Não há
garantia de compatibilidade automática com formatos futuros; a garantia é falha
fechada, snapshot anterior preservado e nenhuma tabela parcial publicada.

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

Não há sender real, retry automático ou integração de runtime com o Orion. A
extração depende de camada textual no PDF e o parser pode precisar de adaptação
quando a CBF mudar o documento. Fontes externas podem mudar; o usuário deve
respeitar os termos de uso da fonte.

## Segurança e privacidade

Nenhuma credencial, token, telefone, ledger operacional, estado, log ou documento interno é distribuído. Não há destino de WhatsApp configurado.

## Roadmap

1. adicionar adaptadores de fonte com contratos testáveis; 2. documentar uma interface de entrega abstrata; 3. ampliar fixtures e validações sem incluir dados pessoais.
