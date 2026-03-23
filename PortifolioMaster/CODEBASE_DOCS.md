# PortifolioMaster - Documentação Técnica

> **Python:** 3.12+
> **Foco atual:** CLI, shell interativo, parsing MT5, cache em Parquet, otimização vetorizada, relatórios HTML e simulação Monte Carlo.

## 1. Visão Geral

O projeto transforma relatórios HTML do MetaTrader 5 em uma base normalizada de trades e executa otimização de portfólios com cálculo vetorizado. A interface principal é o CLI, com suporte a shell interativo para exploração rápida.

```text
Usuário
  └─ CLI / shell interativo
       ├─ load / list / optimize
       ├─ inspect / cache / config
       ├─ export / montecarlo
       └─ visualização HTML / arquivos de saída
```

## 2. Estrutura do Projeto

```text
src/portifoliomaster/
├── __main__.py                 # Permite `python -m portifoliomaster`
├── main.py                     # Parsing de argumentos e roteamento principal
├── api/
│   └── cli.py                  # Orquestrador da aplicação e shell interativo
├── core/
│   ├── config.py               # AppConfig (Pydantic BaseSettings)
│   └── exceptions.py           # Erros do domínio
├── services/
│   ├── adherence.py            # Validação SQX vs MT5
│   ├── metrics.py              # Métricas de trade / portfólio
│   ├── montecarlo.py           # Simulação Monte Carlo
│   ├── optimization.py         # Motor brute-force / greedy
│   └── portfolio.py            # Estruturas e métricas por estratégia
└── utils/
    ├── help.py                 # Help detalhado do CLI
    ├── logger.py               # Logger padronizado
    ├── mt5_parser.py           # Parser HTML do MT5
    └── visualizer.py           # Relatórios e gráficos Plotly
```

## 3. Fluxo de Execução

### 3.1 Entrada principal

`src/portifoliomaster/main.py` carrega a configuração, inicializa o logger e decide entre:

- subcomandos top-level `inspect`, `cache` e `config`
- flags tradicionais como `--load`, `--optimize`, `--montecarlo`
- shell interativo com `-i`

### 3.2 Carregamento de dados

`PortifolioCLI.load_reports()` segue esta ordem:

1. tenta ler `cache.parquet`
2. se o cache estiver ausente/incompatível, faz parse dos HTMLs
3. armazena estratégias em memória via `PortfolioManager`
4. recria o cache em Parquet quando possível

### 3.3 Otimização

`PortifolioCLI.run_optimization()`:

1. obtém os trades consolidados
2. aplica filtros de data e lista de estratégias, se informados
3. instancia `BruteForceEngine`
4. executa brute-force ou greedy
5. exporta artefatos opcionais
6. salva o melhor resultado em `last_optimization_results`

## 4. CLI e Shell

### 4.1 Comandos principais

- `--load <dir>`: carrega relatórios HTML.
- `--list`: lista estratégias carregadas.
- `--optimize`: roda a otimização.
- `--quiet`: suprime mensagens INFO no console.
- `--import-p <file>`: importa um portfólio salvo (JSON ou Parquet).
- `--output <dir>`: salva artefatos em uma pasta de execução.
- `--montecarlo [N]`: roda Monte Carlo sobre o melhor portfólio.

### 4.2 Subcomandos auxiliares

Os comandos abaixo são tratados antes do parser principal:

- `inspect correlations`
- `inspect strategy <name>`
- `adherence`
- `drawdown pairing`
- `cache info`
- `cache rebuild <directory>`
- `cache clear`
- `config show`
- `config validate`

### 4.3 Shell interativo

O shell interativo reaproveita as mesmas rotas do CLI, mas mantém estado em memória entre comandos. Isso é útil para:

- carregar uma vez e inspecionar várias vezes
- otimizar e depois exportar/plotar sem reprocessar
- comparar estratégias sem sair do processo

## 5. Pipeline de Otimização

### 5.1 Motor brute-force

`src/portifoliomaster/services/optimization.py` contém o núcleo da busca:

- gera combinações de estratégias
- filtra combinações por correlação máxima
- calcula retorno, drawdown e `RetDD` em lote
- calcula pesos volatility-inverse para o portfólio (1/std(returns))
- mantém um heap de top-N resultados
- enriquece os vencedores com métricas detalhadas

### 5.2 Modo greedy

O modo greedy usa o melhor seed do brute-force para crescer o portfólio uma estratégia por vez, aceitando apenas adições que:

- respeitem o limite de correlação
- melhorem estritamente a métrica de ranking

Isso reduz bastante o custo computacional em casos com muitas estratégias.

### 5.3 Métricas

As métricas principais hoje são:

- `Net_Profit`
- `Maximum_Drawdown`
- `RetDD`
- métricas detalhadas de trade exportadas pelo `PortfolioManager`

## 6. Monte Carlo

`src/portifoliomaster/services/montecarlo.py` implementa uma simulação por permutação da ordem dos trades.

Objetivo:

- medir a sensibilidade da curva de equity à ordem dos trades
- comparar drawdown original com distribuição de drawdowns simulados
- gerar uma leitura mais robusta de risco

Saída:

- distribuição de `MaxDD`
- distribuição de `RetDD`
- resumo estatístico
- gráfico HTML com equity curves e histogramas

## 7. Teste de Aderência (Fidelidade)

`src/portifoliomaster/services/adherence.py` valida se backtests exportados de outras ferramentas (como StrategyQuant X) são compatíveis com o MetaTrader 5.

Processo:
- Pareia arquivos pelo **stem** (nome base) do arquivo.
- Calcula métricas (**Trades**, **RetDD** e **Pearson**) usando a mesma lógica vetorizada para ambos os fontes.
- Aplica thresholds configuráveis:
  - **Fidelity Threshold** (padrão 80%): Para número de trades e RetDD.
  - **Pearson Threshold** (padrão 0.85): Para correlação das curvas de equity.
- Gera um relatório comparativo interativo (`adherence_report.html`) com equity curves sobrepostas.
- Opcionalmente exporta os resultados detalhados em JSON.

## 8. Drawdown Pairing

`src/portifoliomaster/services/portfolio.py` (via `drawdown pairing`) permite normalizar o risco entre estratégias diferentes.

O objetivo é calcular o lote ideal para cada estratégia de forma que o Rebaixamento Máximo (MaxDD) individual atinja um alvo financeiro fixo (ex: $4000). Isso permite que estratégias com volatilidades distintas contribuam de forma equilibrada para o portfólio final.

## 9. Visualização e Exportação

`src/portifoliomaster/utils/visualizer.py` gera:

- relatório HTML dos resultados da otimização
- relatório HTML do Monte Carlo
- relatório HTML de aderência (SQX vs MT5)
- gráfico individual de equity por portfólio/estratégia

O projeto grava artefatos em formatos diferentes conforme a ação:

- CSV para tabelas simples
- Parquet para trades em volume (`portfolios/rank_XX.parquet`)
- JSON para portfólio configurável (`rank.json` com pesos volatility-inverse)
- HTML para relatórios interativos
- `montecarlo_report.html` quando a simulação Monte Carlo é executada
- `adherence_report.html` quando o teste de aderência é executado

## 10. Parser MT5 e Portfolio Manager

`src/portifoliomaster/utils/mt5_parser.py` e `src/portifoliomaster/services/portfolio.py` fazem a ponte entre HTML e o motor de cálculo.

Características principais:

- suporta encodings UTF-8, UTF-16 e Latin-1
- reconhece relatórios em PT e EN
- extrai o **Lote Representativo** (mediana da coluna Volume) de cada estratégia automaticamente
- padroniza nomes de colunas para o formato interno
- centraliza a lógica de correlação periódica (H, D, W, M) para consistência entre CLI e motor de otimização

## 11. Cache

O cache atual é composto por dois arquivos para garantir reuso total do estado processado:

- `cache.parquet`: Trades consolidados com uma coluna de tempo e uma coluna por estratégia.
- `cache_lots.json`: Sidecar contendo os lotes representativos extraídos dos relatórios.

Benefícios:

- reuso rápido em execuções subsequentes
- evita reprocessar HTML sempre
- acelera comandos como `list`, `inspect`, `optimize` e `drawdown pairing`

Limitação importante:

- o cache é sensível ao contexto do diretório de trabalho e ao formato esperado das colunas

## 12. Configuração

`src/portifoliomaster/core/config.py` define `AppConfig` com Pydantic Settings.

Ordem de precedência:

1. `config.json`
2. variáveis de ambiente / `.env`
3. defaults embutidos

Campos relevantes:

- `min_assets`, `max_assets`
- `top_n`
- `max_corr`
- `corr_period`
- `rank_by`
- `num_workers`
- `print_results`
- `corr_filter_batch_size`
- `matrix_algebra_batch_size`
- `log_path`
- `cache_path`

## 13. Performance

O projeto usa técnicas de performance que valem ser preservadas:

- vetorização em NumPy para calcular portfólios em lote
- `np.maximum.accumulate` para drawdown sem loop Python
- batching em filtro de correlação e álgebra matricial
- `multiprocessing` no motor de otimização quando `num_workers > 1`
- `tqdm` para feedback de execução

## 14. Pontos de Evolução Naturais

Se o objetivo for evoluir o projeto sem perder coesão, os próximos passos mais valiosos são:

- versionar execuções com um manifesto de parâmetros
- adicionar `results --format json` no CLI
- separar melhor “casos de uso” em vez de concentrar lógica na classe `PortifolioCLI`
- fortalecer o cache com fingerprint de arquivos
- ampliar validação de robustez com Monte Carlo e walk-forward
