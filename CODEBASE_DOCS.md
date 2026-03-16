# DataManager — Documentação Técnica do Codebase

> **Versão:** v1.2.0  
> **Python:** 3.12  
> **Propósito:** Ferramenta de download, armazenamento e gestão de dados OHLCV (Open, High, Low, Close, Volume) de ativos financeiros, com suporte a múltiplas fontes de dados, resampling de timeframes e API de rede.

---

## Índice

1. [Visão Geral da Arquitetura](#1-visão-geral-da-arquitetura)
2. [Estrutura de Diretórios](#2-estrutura-de-diretórios)
3. [Módulos e Arquivos](#3-módulos-e-arquivos)
   - [main.py](#31-mainpy--ponto-de-entrada)
   - [cli.py](#32-clipy--interface-de-linha-de-comando)
   - [core/server.py](#33-coreserverpy--controlador-central)
   - [data_management/storage.py](#34-data_managementstoragepy--camada-de-persistência)
   - [data_management/processor.py](#35-data_managementprocessorpy--resampling-de-timeframes)
   - [fetchers/base.py](#36-fetchersbasepy--interface-abstrata)
   - [fetchers/dukascopy_fetcher.py](#37-fetchersdukascopy_fetcherpy)
   - [fetchers/openbb_fetcher.py](#38-fetchersopenbb_fetcherpy)
   - [network_server.py](#39-network_serverpy--api-rest-fastapi)
   - [client.py](#310-clientpy--cliente-python-para-a-api)
4. [Fluxo de Dados](#4-fluxo-de-dados)
5. [Sistema de Armazenamento](#5-sistema-de-armazenamento)
6. [Catálogo de Metadados](#6-catálogo-de-metadados)
7. [Fontes de Dados Suportadas](#7-fontes-de-dados-suportadas)
8. [Timeframes Suportados](#8-timeframes-suportados)
9. [Segurança da API](#9-segurança-da-api)
10. [Deploy com Docker](#10-deploy-com-docker)
11. [Dependências Principais](#11-dependências-principais)
12. [Referência de Comandos CLI](#12-referência-de-comandos-cli)
13. [Referência da API REST](#13-referência-da-api-rest)

---

## 1. Visão Geral da Arquitetura

O DataManager tem **dois modos de operação** independentes mas que compartilham o mesmo núcleo (`core/server.py`):

```
┌─────────────────────────────────────────────────────────────┐
│                        MODOS DE USO                         │
│                                                             │
│  ┌──────────────────┐          ┌──────────────────────────┐ │
│  │   CLI Local       │          │  API REST (FastAPI)       │ │
│  │   main.py         │          │  network_server.py        │ │
│  │   cli.py          │          │  client.py                │ │
│  └────────┬─────────┘          └──────────┬───────────────┘ │
│           │                               │                  │
│           └──────────────┬────────────────┘                  │
│                          ▼                                   │
│               ┌─────────────────────┐                        │
│               │  core/server.py     │                        │
│               │  DataManager        │                        │
│               └────────┬────────────┘                        │
│                        │                                     │
│         ┌──────────────┼──────────────┐                     │
│         ▼              ▼              ▼                      │
│  ┌─────────────┐ ┌──────────┐ ┌────────────┐               │
│  │  Fetchers   │ │ Storage  │ │ Processor  │               │
│  │ (Dukascopy) │ │ Manager  │ │ (Resample) │               │
│  │ (OpenBB)    │ │          │ │            │               │
│  └─────────────┘ └──────────┘ └────────────┘               │
└─────────────────────────────────────────────────────────────┘
```

**Princípio fundamental:** Todo dado é sempre baixado e armazenado em **M1 (1 minuto)** primeiro. Timeframes maiores (H1, D1, etc.) são gerados por **resampling** a partir do M1 base.

---

## 2. Estrutura de Diretórios

```
DataManager/
│
├── main.py                    # Ponto de entrada da aplicação (CLI)
├── cli.py                     # Interface interativa de comandos (cmd.Cmd)
├── network_server.py          # Servidor HTTP FastAPI (modo API)
├── client.py                  # Cliente Python para consumir a API
├── requirements.txt           # Dependências Python fixadas por versão
├── Dockerfile                 # Imagem Docker da aplicação
├── docker-compose.yml         # Configuração de deploy (modo API)
├── .env.example               # Exemplo de variáveis de ambiente
│
├── core/
│   └── server.py              # DataManager: controlador central da lógica
│
├── data_management/
│   ├── storage.py             # StorageManager: leitura/escrita de Parquet + catálogo
│   └── processor.py          # DataProcessor: resampling de OHLCV
│
├── fetchers/
│   ├── base.py                # BaseFetcher: interface abstrata (ABC)
│   ├── dukascopy_fetcher.py   # Integração com dukascopy-python
│   └── openbb_fetcher.py      # Integração com OpenBB (yfinance como backend)
│
├── metadata/
│   ├── catalog.json           # Índice JSON de todos os databases salvos
│   └── dukas_assets.csv       # Lista de ~3.000 ativos válidos do Dukascopy
│
└── database/
    └── {source}/
        └── {ASSET}/
            └── {TIMEFRAME}/
                └── data.parquet   # Arquivo de dados OHLCV
```

---

## 3. Módulos e Arquivos

### 3.1 `main.py` — Ponto de Entrada

**Responsabilidade:** Parseia argumentos de linha de comando e decide o modo de execução.

**Lógica:**
- `python main.py -i` → Abre o shell interativo (`cli.cmdloop()`)
- `python main.py download DUKASCOPY EURUSD` → Executa um comando diretamente (`cli.onecmd()`)
- `python main.py` (sem argumentos) → Exibe o help do argparse

```python
# Estrutura simplificada:
parser.add_argument('-i', '--interactive', action='store_true')
parser.add_argument('command', nargs=argparse.REMAINDER)

if args.interactive:
    cli.cmdloop()
elif args.command:
    cli.onecmd(" ".join(args.command))
else:
    parser.print_help()
```

**Tratamento especial:** `KeyboardInterrupt` (Ctrl+C) é capturado globalmente e encerra com `sys.exit(0)`.

---

### 3.2 `cli.py` — Interface de Linha de Comando

**Responsabilidade:** Define todos os comandos disponíveis ao usuário usando `cmd.Cmd` do stdlib Python.

**Classe:** `DataManagerCLI(cmd.Cmd)`

**Instancia internamente:** `DataManager` (de `core/server.py`)

#### Comandos disponíveis:

| Método | Comando | Descrição |
|--------|---------|-----------|
| `do_download` | `download` | Baixa dados novos para um ou mais ativos |
| `do_update` | `update` | Atualiza databases existentes com dados recentes |
| `do_delete` | `delete` | Remove databases do disco |
| `do_info` | `info` | Exibe metadados de um database específico |
| `do_list` | `list` | Lista todos os databases salvos em tabela formatada |
| `do_rebuild` | `rebuild` | Reconstrói o catálogo `catalog.json` escaneando o disco |
| `do_search` | `search` | Busca ativos disponíveis nas fontes (OpenBB ou Dukascopy) |
| `do_resample` | `resample` | Converte M1 para outros timeframes |
| `do_quality` | `quality` | Relatório de integridade dos dados |
| `do_exit` / `do_quit` | `exit` / `quit` | Encerra o programa |

#### Detalhes de parsing por comando:

**`download`:**
```
download <fonte> <ativo1,ativo2,...> [start_date] [end_date] [-timeframe tf1,tf2,...]
```
- Suporta **múltiplos ativos** via vírgula.
- Flag `-timeframe` opcional: após download do M1, faz resample automático para os TFs especificados.
- Se `start_date` omitido → usa `2000-01-01` (histórico completo).
- Se `end_date` omitido → usa `datetime.now()`.
- Protege cada ativo com `try/except` individual para não abortar os demais.

**`update`:**
```
update <fonte> <ativo1,ativo2,...> [timeframe=M1]
update all
```
- `update all` → chama `DataManager.update_all_databases()` que atualiza todos os M1s e faz resample dos TFs derivados.

**`search`:**
- Usa `argparse` interno com `shlex.split` para suportar queries com espaço e aspas.
- Parâmetros: `--source`, `--query`, `--exchange`.

---

### 3.3 `core/server.py` — Controlador Central

**Responsabilidade:** Orquestra todas as operações de negócio, coordenando Fetchers, Storage e Processor.

**Classe:** `DataManager`

#### Inicialização:
```python
self.storage = StorageManager()
self.processor = DataProcessor()
self._fetchers = {
    "DUKASCOPY": DukascopyFetcher(),
    "OPENBB": OpenBBFetcher()
}
```
O mapeamento de fontes é um dicionário; adicionar uma nova fonte requer apenas inserir um novo par chave→fetcher.

#### Métodos principais:

**`download_data(source, asset, start_date, end_date)`**
- Verifica se o database M1 já existe (evita duplicatas).
- Chama `fetcher.fetch_data()`.
- Salva via `storage.save_data()` sempre em timeframe `M1`.

**`update_data(source, asset, timeframe="M1")`**
- Lê a última data do database existente via `storage.get_database_info()`.
- Verifica se está atualizado (margem de 1 hora).
- Baixa apenas os dados novos (do `last_date` até `now`).
- Se o `timeframe` for diferente de M1, converte os novos dados antes de appendar.
- Usa `storage.append_data()` para concatenar sem duplicatas.

**`update_all_databases()`**
- Separa databases em dois grupos: M1 e higher TFs.
- Primeiro atualiza todos os M1s.
- Depois reconstrói todos os TFs derivados usando `resample_database()`.

**`resample_database(source, asset, target_timeframe)`**
- Carrega o M1 completo do disco.
- Usa `DataProcessor.resample_ohlc()` para converter.
- Salva o resultado (sobrescreve o TF de destino).

**`check_quality(source, asset, timeframe="M1")`**
Executa 4 verificações e reporta erros encontrados:
1. **Relações OHLC:** `High >= Low`, `High >= Open/Close`, `Low <= Open/Close`
2. **Duplicatas:** Timestamps duplicados no índice
3. **Ordenação temporal:** Índice deve ser crescentemente monotônico
4. **Gaps:** Detecta ausências maiores que 5x a frequência mediana esperada

**`search_assets(source, query, exchange)`**
- **OpenBB:** Chama `obb.equity.search()` e exibe os 20 primeiros resultados.
- **Dukascopy:** Filtra o CSV local `metadata/dukas_assets.csv` nos campos `ticker`, `alias` e `nome_do_ativo`.

---

### 3.4 `data_management/storage.py` — Camada de Persistência

**Responsabilidade:** Toda operação de leitura e escrita de dados no disco, e manutenção do catálogo JSON.

**Classe:** `StorageManager`

#### Estrutura de paths:
```python
# Caminho de um arquivo de dados:
database/{source_lower}/{ASSET_UPPER}/{TIMEFRAME_UPPER}/data.parquet

# Exemplo:
database/dukascopy/EURUSD/M1/data.parquet
database/openbb/AAPL/H1/data.parquet
```

#### Formato de armazenamento:
- **Parquet** via `fastparquet` (padrão). O índice é sempre um `DatetimeIndex` sem timezone (naive).
- O arquivo único por combinação source/asset/timeframe é sempre `data.parquet`.

#### Métodos principais:

**`save_data(df, source, asset, timeframe)`**
- Garante que o índice seja `DatetimeIndex`.
- Remove timezone do índice se presente (`tz_convert(None)`).
- Ordena o índice antes de salvar.
- Atualiza o `catalog.json` após salvar.

**`append_data(df, source, asset, timeframe)`**
- Carrega o DataFrame existente.
- Concatena com `pd.concat`.
- Remove duplicatas de índice (`keep='last'`).
- Chama `save_data()` para persistir.

**`load_data(source, asset, timeframe) → pd.DataFrame`**
- Lê o `.parquet` via `fastparquet`.
- Lança `FileNotFoundError` se não existir.

**`get_database_info(source, asset, timeframe) → dict`**
Retorna:
```python
{
    "source": str,
    "asset": str,
    "timeframe": str,
    "rows": int,
    "start_date": str,   # "YYYY-MM-DD HH:MM:SS"
    "end_date": str,     # "YYYY-MM-DD HH:MM:SS"
    "file_size_kb": float
}
```
Ou `{"status": "Not Found"}` se o arquivo não existir.

**`rebuild_catalog() → dict`**
- Varre todo o diretório `database/` recursivamente.
- Reconstrói o `catalog.json` do zero.
- Útil quando arquivos são movidos/deletados manualmente.

**`list_databases() → list`**
- Primeiro limpa diretórios vazios (`_cleanup_empty_dirs`).
- Retorna o conteúdo do `catalog.json` (leitura rápida, sem I/O de Parquet).

**`delete_database(source, asset, timeframe=None) → bool`**
- Se `timeframe` fornecido: deleta apenas aquele arquivo `.parquet`.
- Se `timeframe=None`: deleta o diretório completo do ativo (todos os TFs).
- Atualiza o catálogo após deleção.

---

### 3.5 `data_management/processor.py` — Resampling de Timeframes

**Responsabilidade:** Converter DataFrames OHLCV de um timeframe menor para um maior.

**Classe:** `DataProcessor`

#### Mapeamento de timeframes para regras do pandas:

```python
TF_MAPPING = {
    'M1':  '1min',   'M2': '2min',   'M5':  '5min',
    'M10': '10min',  'M15': '15min', 'M30': '30min',
    'H1':  '1h',     'H2':  '2h',    'H3':  '3h',
    'H4':  '4h',     'H6':  '6h',
    'D1':  'D',      'W1':  'W',
}
```

**`resample_ohlc(df, target_timeframe) → pd.DataFrame`** (classmethod)
- Detecta automaticamente os nomes das colunas (case-insensitive: `open`, `Open`, `OPEN` → todos funcionam).
- Regras de agregação:
  - `Open` → `first`
  - `High` → `max`
  - `Low` → `min`
  - `Close` → `last`
  - `Volume` → `sum`
- Usa `df.resample(rule).agg(agg_dict).dropna()`.
- Lança `ValueError` para TF não suportado ou DataFrame sem colunas OHLC.

---

### 3.6 `fetchers/base.py` — Interface Abstrata

**Responsabilidade:** Define o contrato que todos os fetchers devem implementar.

**Classe:** `BaseFetcher(ABC)`

```python
@property
@abstractmethod
def source_name(self) -> str:
    """Nome legível da fonte (ex: 'Dukascopy')"""

@abstractmethod
def fetch_data(self, asset: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
    """
    Retorna DataFrame com:
    - Index: DatetimeIndex timezone-naive
    - Colunas: Open, High, Low, Close, Volume (capitalizadas)
    """
```

**Contrato de retorno garantido por todos os fetchers:**
- Índice: `DatetimeIndex` sem timezone, nome `"datetime"`
- Colunas: `Open`, `High`, `Low`, `Close`, `Volume` (primeira letra maiúscula)
- Dados ordenados cronologicamente
- Sem duplicatas de índice

---

### 3.7 `fetchers/dukascopy_fetcher.py`

**Responsabilidade:** Download de dados M1 via biblioteca `dukascopy-python`.

**Classe:** `DukascopyFetcher(BaseFetcher)`

#### Lógica de download em chunks:
- Divide o período total em **chunks de 7 dias**.
- Para cada chunk, chama `dukascopy_python.fetch()` com `INTERVAL_MIN_1` e `OFFER_SIDE_BID`.
- Exibe **barra de progresso colorida** no terminal (usando `colorama`).
- Erros individuais de chunk são silenciados (fins de semana retornam vazio, o que é esperado).

#### Validação de ticker:
- Antes de baixar, verifica se o ticker existe no arquivo `metadata/dukas_assets.csv`.
- Suporta busca tanto pelo campo `ticker` quanto pelo campo `alias` (case-insensitive).
- Lança `ValueError` com mensagem orientativa se o ticker não for encontrado.

#### Pós-processamento:
```python
# Remove duplicatas (mantém o último)
df = df[~df.index.duplicated(keep='last')]

# Remove timezone
df.index = df.index.tz_convert(None)

# Padroniza nomes das colunas: open → Open, high → High, etc.
col_map = {c.lower(): c.capitalize() for c in df.columns}
df.rename(columns=col_map, inplace=True)

df.index.name = "datetime"
df.sort_index(inplace=True)
```

---

### 3.8 `fetchers/openbb_fetcher.py`

**Responsabilidade:** Download de dados M1 via OpenBB (usando YFinance como provider).

**Classe:** `OpenBBFetcher(BaseFetcher)`

#### Lógica principal:
```python
kwargs = {
    "symbol": asset,
    "interval": "1m",
    "provider": "yfinance"
}
# Datas são incluídas apenas se o usuário especificou (start_date.year > 2000)
res = obb.equity.price.historical(**kwargs)
df = res.to_df()
```

**Nota importante:** Se `start_date.year <= 2000` (valor default da CLI para histórico completo), as datas são omitidas do request para que o YFinance retorne o máximo disponível.

#### Limitação conhecida:
O YFinance limita dados intraday (M1) a aproximadamente os últimos 30 dias. Para históricos maiores, use Dukascopy.

#### Pós-processamento: idêntico ao Dukascopy (padronização de timezone e nomes de colunas).

---

### 3.9 `network_server.py` — API REST (FastAPI)

**Responsabilidade:** Expõe as funcionalidades do `DataManager` como uma API HTTP protegida por API Key.

**Framework:** FastAPI v0.128  
**Porta padrão:** `8686`  
**Instância global:** `manager = DataManager()` (singleton)

#### Segurança (3 camadas):

1. **Autenticação por API Key** via header `X-API-Key`
   - Chave lida de `DATAMANAGER_API_KEY` env var (fallback: `"YOUR_API_KEY_HERE"`)
   - Retorna HTTP 403 se a chave for inválida

2. **Validação de entrada** via Pydantic com regex patterns
   - `source`: `^[a-zA-Z0-9_]+$`
   - `asset`: `^[a-zA-Z0-9_,\s\-]+$`
   - `timeframe`: `^[a-zA-Z0-9_]+$`

3. **Proteção contra Path Traversal** via `re.match()` nos parâmetros de URL

#### Endpoints:

| Método | Rota | Descrição | Async |
|--------|------|-----------|-------|
| `POST` | `/download` | Baixa novo ativo (background task) | ✅ |
| `POST` | `/update` | Atualiza database (background task) | ✅ |
| `POST` | `/delete` | Deleta database(s) | ❌ |
| `POST` | `/resample` | Gera timeframe derivado (background task) | ✅ |
| `GET` | `/list` | Lista todos os databases | ❌ |
| `GET` | `/info/{source}/{asset}/{timeframe}` | Metadados de um database | ❌ |
| `GET` | `/search` | Busca ativos disponíveis | ❌ |
| `GET` | `/data/{source}/{asset}/{timeframe}` | Baixa o arquivo `.parquet` bruto | ❌ |

**Operações longas** (`download`, `update`, `resample`) são executadas em **BackgroundTasks** do FastAPI para não bloquear o servidor. O endpoint retorna imediatamente com `{"status": "success", "message": "...started in background"}`.

**`GET /data/{source}/{asset}/{timeframe}`:** Retorna o arquivo `.parquet` como stream binário (`application/octet-stream`) para download direto.

#### Execução direta:
```bash
python network_server.py
# ou
uvicorn network_server:app --host 0.0.0.0 --port 8686
```

---

### 3.10 `client.py` — Cliente Python para a API

**Responsabilidade:** Wrapper Python para consumir a API REST do DataManager de forma programática.

**Classe:** `DataManagerClient`

#### Inicialização:
```python
client = DataManagerClient(
    base_url="http://127.0.0.1:8686",
    api_key="YOUR_API_KEY_HERE"
)
```
Usa `requests.Session` para enviar automaticamente o header `X-API-Key` em todas as requisições.

#### Métodos:

| Método | HTTP | Descrição | Retorno |
|--------|------|-----------|---------|
| `download(source, asset, start_date, end_date)` | POST | Aciona download no servidor | `dict` |
| `update(source, asset, timeframe)` | POST | Aciona atualização | `dict` |
| `delete(source, asset, timeframe)` | POST | Deleta database | `dict` |
| `resample(source, asset, target_timeframe)` | POST | Aciona resample | `dict` |
| `list_databases()` | GET | Lista databases | `list[dict]` |
| `info(source, asset, timeframe)` | GET | Metadados | `dict` |
| `search(source, query, exchange)` | GET | Busca ativos | `pd.DataFrame` |
| `get_data(source, asset, timeframe, save_path, save_format)` | GET | Baixa dados | `pd.DataFrame` ou `str` |

**`get_data()`** é o método mais importante para uso programático:
- Sem `save_path`: carrega o Parquet em memória e retorna `pd.DataFrame`.
- Com `save_path` e `save_format="parquet"`: salva o arquivo `.parquet` diretamente no disco.
- Com `save_path` e `save_format="csv"`: converte para CSV e salva no disco.

---

## 4. Fluxo de Dados

### 4.1 Fluxo de Download Completo

```
Usuário: download DUKASCOPY EURUSD 2020-01-01 2024-01-01
  │
  ▼
CLI.do_download()
  │ → Parseia source, asset, datas
  │ → Chama DataManager.download_data()
  │
  ▼
DataManager.download_data()
  │ → Verifica: storage.get_database_info() → "Not Found" (ok, continua)
  │ → _get_fetcher("DUKASCOPY") → DukascopyFetcher()
  │ → fetcher.fetch_data(asset, start, end)
  │
  ▼
DukascopyFetcher.fetch_data()
  │ → Valida ticker no dukas_assets.csv
  │ → Loop em chunks de 7 dias com barra de progresso
  │ → pd.concat(dfs)
  │ → Remove duplicatas, remove timezone, padroniza colunas
  │ → Retorna DataFrame M1
  │
  ▼
DataManager.download_data() (continua)
  │ → storage.save_data(df_m1, "DUKASCOPY", "EURUSD", "M1")
  │
  ▼
StorageManager.save_data()
  │ → _get_path() → "database/dukascopy/EURUSD/M1/data.parquet"
  │ → Garante index DatetimeIndex, remove tz, ordena
  │ → df.to_parquet(file_path, engine='fastparquet')
  │ → _update_catalog_entry() → atualiza catalog.json
  │
  ▼
Saída: "✓ Database EURUSD (M1) saved successfully! (X rows)"
```

### 4.2 Fluxo de Resample

```
Usuário: resample DUKASCOPY EURUSD H4
  │
  ▼
DataManager.resample_database("DUKASCOPY", "EURUSD", "H4")
  │ → storage.load_data("DUKASCOPY", "EURUSD", "M1")  ← carrega o M1 base
  │ → processor.resample_ohlc(df_m1, "H4")
  │      → rule = "4h"
  │      → df.resample("4h").agg({Open: first, High: max, Low: min, Close: last, Volume: sum})
  │      → .dropna()
  │ → storage.save_data(df_h4, "DUKASCOPY", "EURUSD", "H4")
  │
  ▼
Saída: "✓ Conversion finished and saved!"
  Arquivo: database/dukascopy/EURUSD/H4/data.parquet
```

---

## 5. Sistema de Armazenamento

### Hierarquia de diretórios:
```
database/
  {source_lowercase}/        # ex: dukascopy, openbb
    {ASSET_UPPERCASE}/       # ex: EURUSD, AAPL
      {TIMEFRAME_UPPERCASE}/ # ex: M1, H1, D1
        data.parquet         # único arquivo de dados por combinação
```

### Formato Parquet:
- Engine: `fastparquet`
- Índice: `DatetimeIndex` com `name="datetime"`, sem timezone
- Colunas: `Open`, `High`, `Low`, `Close`, `Volume`

### Por que Parquet?
- Compressão eficiente para dados de séries temporais
- Leitura rápida por colunas (columnar format)
- Preserva tipos de dados nativos (float64, datetime64)

---

## 6. Catálogo de Metadados

**Arquivo:** `metadata/catalog.json`

O catálogo é uma lista JSON de objetos, um por database armazenado:

```json
[
  {
    "source": "dukascopy",
    "asset": "EURUSD",
    "timeframe": "M1",
    "rows": 2764800,
    "start_date": "2020-01-02 00:00:00",
    "end_date": "2024-12-31 23:59:00",
    "file_size_kb": 45230.5
  }
]
```

**Atualização automática:** O catálogo é atualizado a cada `save_data()`, `append_data()` e `delete_database()`.

**`rebuild`:** O comando `rebuild` (CLI) ou método `storage.rebuild_catalog()` varre todo o diretório `database/` e reconstrói o JSON do zero, útil após operações manuais no sistema de arquivos.

**Leitura rápida:** `list_databases()` lê apenas o JSON (sem abrir nenhum Parquet), tornando o comando `list` muito rápido independente do volume de dados.

---

## 7. Fontes de Dados Suportadas

| Chave | Fetcher | Backend | Dados disponíveis |
|-------|---------|---------|-------------------|
| `DUKASCOPY` | `DukascopyFetcher` | `dukascopy-python` | Forex, índices, commodities, criptos (~3.000 ativos). Histórico completo desde ~2000. |
| `OPENBB` | `OpenBBFetcher` | `openbb` + `yfinance` | Ações, ETFs, índices. Dados M1 limitados a ~30 dias. |

### Arquivo de ativos Dukascopy:
`metadata/dukas_assets.csv` — CSV com ~3.000 linhas e colunas:
- `ticker` — Identificador oficial (ex: `EURUSD`)
- `alias` — Nome alternativo aceito na CLI
- `nome_do_ativo` — Nome legível (ex: "Euro vs US Dollar")
- `categoria` — Grupo do ativo (Forex, Crypto, etc.)

---

## 8. Timeframes Suportados

| Abreviação | Equivalente pandas | Nome |
|------------|-------------------|------|
| `M1` | `1min` | 1 Minuto (base) |
| `M2` | `2min` | 2 Minutos |
| `M5` | `5min` | 5 Minutos |
| `M10` | `10min` | 10 Minutos |
| `M15` | `15min` | 15 Minutos |
| `M30` | `30min` | 30 Minutos |
| `H1` | `1h` | 1 Hora |
| `H2` | `2h` | 2 Horas |
| `H3` | `3h` | 3 Horas |
| `H4` | `4h` | 4 Horas |
| `H6` | `6h` | 6 Horas |
| `D1` | `D` | Diário |
| `W1` | `W` | Semanal |

**Importante:** Apenas `M1` é baixado diretamente dos fetchers. Todos os outros são gerados por resample.

---

## 9. Segurança da API

### Autenticação
- Header obrigatório: `X-API-Key: <chave>`
- Configurada via variável de ambiente `DATAMANAGER_API_KEY`
- HTTP 403 em caso de chave inválida ou ausente

### Proteção contra injeção
- Todos os campos de entrada são validados com regex Pydantic (ex: `^[a-zA-Z0-9_]+$`)
- Parâmetros de URL em `GET /info` e `GET /data` são validados com `re.match()` antes do uso

### Operações assíncronas
- Downloads e updates rodam em `BackgroundTasks` do FastAPI
- O servidor nunca fica bloqueado em operações longas
- Evita duplicatas no `/download` verificando a existência do M1 antes de agendar o background task (retorna HTTP 409 Conflict se já existir)

---

## 10. Deploy com Docker

### Modo API (recomendado para servidor):
```bash
docker-compose up -d
```

O `docker-compose.yml` configura:
- Imagem: `ghcr.io/guilsmatos1/datamanager:latest`
- Porta: `8686:8686`
- Volumes persistentes: `./database` e `./metadata` (dados nunca são perdidos ao recriar o container)
- Reinício automático: `restart: always`
- Variável de ambiente: `DATAMANAGER_API_KEY`
- Comando padrão: `python network_server.py`

### Dockerfile:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN apt-get install -y gcc g++   # necessário para compilar dependências nativas
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py", "-i"]  # modo CLI interativo por padrão no Dockerfile
```

---

## 11. Dependências Principais

| Pacote | Versão | Função |
|--------|--------|--------|
| `pandas` | 3.0.1 | Manipulação de DataFrames, resampling, I/O |
| `fastparquet` | 2025.12.0 | Leitura/escrita de arquivos Parquet |
| `fastapi` | 0.128.8 | Framework da API REST |
| `uvicorn` | 0.40.0 | Servidor ASGI para FastAPI |
| `pydantic` | 2.12.5 | Validação de payloads da API |
| `dukascopy-python` | 4.0.1 | Download de dados Dukascopy |
| `openbb` | 4.7.0 | Plataforma de dados financeiros |
| `yfinance` | 1.2.0 | Backend de dados para OpenBB |
| `colorama` | 0.4.6 | Output colorido no terminal |
| `requests` | 2.32.5 | HTTP client (usado pelo `client.py`) |
| `python-dateutil` | 2.9.0 | Parse flexível de datas na CLI |

---

## 12. Referência de Comandos CLI

### Exemplos de uso completos:

```bash
# Modo interativo
python main.py -i

# Modo direto (sem shell interativo)
python main.py download DUKASCOPY EURUSD 2020-01-01 2024-01-01
python main.py list
python main.py quality DUKASCOPY EURUSD M1
```

### Dentro do shell interativo:

```bash
# Download com histórico completo (desde 2000-01-01)
download DUKASCOPY EURUSD

# Download múltiplos ativos com resampling automático
download DUKASCOPY EURUSD,GBPUSD,USDJPY 2023-01-01 2024-01-01 -timeframe H1,H4,D1

# Atualizar um ativo
update DUKASCOPY EURUSD

# Atualizar todos os databases de uma vez
update all

# Listar todos os databases
list

# Reconstruir catálogo (após mudanças manuais)
rebuild

# Buscar ativos
search                                    # mostra resumo de fontes
search --query "bitcoin"                  # busca em OpenBB
search --source dukascopy --query "EUR"   # busca offline no CSV

# Criar timeframe derivado do M1
resample DUKASCOPY EURUSD H1
resample DUKASCOPY EURUSD,GBPUSD H1,H4,D1

# Ver metadados de um database
info DUKASCOPY EURUSD M1

# Verificar qualidade dos dados
quality DUKASCOPY EURUSD M1
quality OPENBB AAPL,MSFT M1

# Deletar um timeframe específico
delete DUKASCOPY EURUSD H1

# Deletar todos os timeframes de um ativo
delete DUKASCOPY EURUSD

# Deletar TUDO (pede confirmação)
delete all

# Sair
exit
```

---

## 13. Referência da API REST

**Base URL:** `http://<host>:8686`  
**Autenticação:** Header `X-API-Key: <sua_chave>`

### POST /download
```json
// Request body:
{
  "source": "DUKASCOPY",
  "asset": "EURUSD",
  "start_date": "2020-01-01",   // opcional
  "end_date": "2024-01-01"      // opcional
}

// Response 200:
{"status": "success", "message": "Download of EURUSD via DUKASCOPY started in background"}

// Response 409 (já existe):
{"detail": "The database for EURUSD via DUKASCOPY already exists..."}
```

### POST /update
```json
// Request body:
{"source": "DUKASCOPY", "asset": "EURUSD", "timeframe": "M1"}

// Response 200:
{"status": "success", "message": "Update of EURUSD via DUKASCOPY (M1) started in background"}
```

### POST /delete
```json
// Deletar um timeframe:
{"source": "DUKASCOPY", "asset": "EURUSD", "timeframe": "H1"}

// Deletar todos os timeframes do ativo:
{"source": "DUKASCOPY", "asset": "EURUSD"}

// Deletar tudo:
{"source": "all", "asset": "all"}
```

### POST /resample
```json
{"source": "DUKASCOPY", "asset": "EURUSD", "target_timeframe": "H4"}
```

### GET /list
```json
// Response 200:
{
  "databases": [
    {
      "source": "dukascopy",
      "asset": "EURUSD",
      "timeframe": "M1",
      "rows": 2764800,
      "start_date": "2020-01-02 00:00:00",
      "end_date": "2024-12-31 23:59:00",
      "file_size_kb": 45230.5
    }
  ]
}
```

### GET /info/{source}/{asset}/{timeframe}
```
GET /info/dukascopy/EURUSD/M1
// Response: mesmo objeto de get_database_info()
```

### GET /search
```
GET /search?source=dukascopy&query=bitcoin
GET /search?source=openbb&query=Apple&exchange=NASDAQ

// Response 200:
{"assets": [...lista de objetos...]}
```

### GET /data/{source}/{asset}/{timeframe}
```
GET /data/dukascopy/EURUSD/M1

// Response: arquivo binário .parquet
// Content-Type: application/octet-stream
// Content-Disposition: attachment; filename="dukascopy_EURUSD_M1.parquet"
```

---

## Notas para Contribuição / Extensão

### Adicionar uma nova fonte de dados:
1. Criar `fetchers/minha_fonte_fetcher.py` herdando de `BaseFetcher`
2. Implementar `source_name` (property) e `fetch_data()` (retornando DataFrame no padrão)
3. Registrar no dicionário `_fetchers` em `core/server.py`:
   ```python
   self._fetchers["MINHA_FONTE"] = MinhaFonteFetcher()
   ```
4. Nenhuma outra alteração necessária — CLI e API funcionarão automaticamente.

### Adicionar um novo timeframe:
1. Adicionar entrada no dicionário `TF_MAPPING` em `data_management/processor.py`:
   ```python
   'M45': '45min',
   ```
2. O sistema inteiro passa a suportar o novo TF automaticamente.

### Invariantes importantes (contratos do sistema):
- Todo dado persistido tem índice `DatetimeIndex` sem timezone, ordenado.
- Todo fetcher retorna colunas com primeira letra maiúscula: `Open`, `High`, `Low`, `Close`, `Volume`.
- O timeframe `M1` é sempre o dado base; nunca faça resample de um TF derivado para gerar outro.
- O catálogo `catalog.json` deve sempre refletir o estado real do disco. Use `rebuild` em caso de dúvida.
