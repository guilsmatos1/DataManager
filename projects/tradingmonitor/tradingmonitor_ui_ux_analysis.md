# TradingMonitor — Análise UI/UX

> [!NOTE]
> Análise baseada na leitura estática de **8.661 linhas** de código frontend (CSS, HTML/Jinja2, JS) cobrindo **12 templates**, **5 JS modules**, e **1 CSS global** (1.582 linhas).

---

## 📊 Resumo Executivo

| Categoria | Críticos | Altos | Médios | Baixos |
|---|:---:|:---:|:---:|:---:|
| Arquitetura & Organização | 1 | 2 | 2 | 1 |
| Navegação & IA | 0 | 2 | 3 | 1 |
| Visual & Consistência | 0 | 3 | 4 | 2 |
| Responsividade & Acessibilidade | 1 | 3 | 2 | 0 |
| Fluxos UX | 0 | 2 | 3 | 2 |
| Performance | 1 | 1 | 2 | 0 |
| **Total** | **3** | **13** | **16** | **6** |

---

## 1. Arquitetura & Organização de Código Frontend

### 🔴 CRÍTICO: `strategy.html` é um monolito de 1.494 linhas
O template `strategy.html` contém **~1.250 linhas de JavaScript inline** incluindo lógica de DOM, fetch API, Chart.js rendering, state management e business logic. Isso é o equivalente frontend do "God Object" antipattern.

**Impacto:** Manutenção extremamente difícil; qualquer mudança na página de strategy exige navegar um arquivo massivo.

**Sugestão:** Extrair para `page-strategy.js` externo (como já feito com `page-index.js` e `page-portfolio.js`). O portfolio já demonstra o padrão correto com apenas 36 linhas inline definindo a constante, e toda lógica em `page-portfolio.js`.

### 🟡 ALTO: Inline styles excessivos nos templates
Muitos templates usam `style="..."` inline extensivamente em vez de classes CSS:

```html
<!-- index.html L69 -->
<div style="padding:0.4rem 0 0.25rem;display:flex;align-items:center;gap:0.5rem">

<!-- settings.html L41 -->
<div class="form-group" style="margin-bottom: 1.5rem;">
    <label ... style="display: block; margin-bottom: 0.5rem; color: var(--text-muted); font-size: 0.85rem;">...
    <input ... style="width: 100%; padding: 0.6rem; background: var(--bg); ..." >
```

Os inputs em `settings.html` redefinem manualmente o que `field-input` já oferece, com uma sintaxe inconsistente.

**Sugestão:** Criar classes utilitárias como `.form-group`, `.mb-1`, etc. no CSS.

### 🟡 ALTO: Duplicação de lógica de rendering
Cada template reimplementa funções como sorting, pagination, table rendering e error handling de forma levemente diferente:

| Funcionalidade | Implementações distintas |
|---|---|
| Sorting de tabela | `strategy.html`, `real.html`, `account.html`, `page-index.js` |
| Paginação | `strategy.html`, `real.html`, `portfolio.html`, `page-index.js` |
| Skeleton loading | Markup idêntico copiado em 5+ templates |

**Sugestão:** Centralizar em `table-renderer.js` (já existe mas é subutilizado) e criar um componente de paginação reutilizável.

### 🟠 MÉDIO: CSS scoped nos templates (`<style>` inline)
Quase todos os templates incluem `<style>` blocks no `{% block content %}`:
- `strategy.html` (L5-21), `portfolio.html` (L5-16), `account.html` (L5-31), `real.html` (L5-11), `advanced_analysis.html` (L10-52)

Embora não seja errado, isso quebra a separação de concerns e dificulta encontrar de onde vem um estilo.

**Sugestão:** Migrar estilos page-specific para sections nomeadas dentro de `style.css` (ex: `/* ── page: strategy ── */`).

### 🟠 MÉDIO: Inconsistência `<style>` vs `class`
Settings page redefine, em inline styles, estilos que já existem como classes:
```html
<!-- settings.html define inline o que field-input já cobre -->
<input type="text" ... class="input" style="width: 100%; padding: 0.6rem; background: var(--bg); border: 1px solid var(--border); ..." >
```

A classe `input` (usada em settings) não existe no CSS. O nome correto é `field-input`.

### 🟢 BAIXO: Variáveis globais JS soltas
Muitos scripts inline declaram variáveis globais (`let equityChart`, `let _realPnlPeriod`, etc.) no escopo global sem encapsulamento.

---

## 2. Navegação & Arquitetura da Informação

### 🟡 ALTO: Navbar fica lotada com dropdowns demais
A navbar horizontal contém **7 itens de navegação** (Overview, Real, Strategies▾, Portfolios▾, Accounts▾, Symbols▾, Benchmarks) + Settings + Theme toggle + WS status. Em telas menores isso inevitavelmente quebra.

Não há **nenhum breakpoint responsivo** para a navbar — ela não tem `flex-wrap` nem hamburguer menu.

**Sugestão:** Implementar um hamburguer menu para telas `< 1024px` que colapse os itens de navegação em um drawer lateral.

### 🟡 ALTO: Ausência de breadcrumbs em páginas deep-linked
Páginas como `/strategy/{id}`, `/account/{id}`, `/portfolio/{id}/correlation` não mostram o caminho de navegação. O único mecanismo é o botão "← Overview" na página de Advanced Analysis, mas é inconsistente (outras páginas não o têm).

**Sugestão:** Adicionar breadcrumbs leves abaixo da navbar: `Overview > Strategies > #12345`.

### 🟠 MÉDIO: Dropdowns carregam dados via API on-click, sem cache cross-page
Cada vez que o usuário abre o dropdown de Strategies, uma nova request é feita. Se o usuário navega para outra página e volta, o cache é perdido (`items.dataset.loaded` existe mas é por instância de DOM).

**Sugestão:** Implementar um cache leve em `sessionStorage` com TTL de 60s.

### 🟠 MÉDIO: Página "Real" rename confuso
A rota é `/real`, o menu diz "Real", mas o título da página é "Account Monitor". O settings chama de "/real page mode". Há confusão semântica entre o nome "Real" (que pode significar "real account" vs "demo account") e o propósito da página (monitoramento em tempo real).

**Sugestão:** Renomear para "Live Monitor" em toda a interface para eliminar a ambiguidade com "Real Account".

### 🟠 MÉDIO: O botão "Advanced Analysis" aparece em 2 lugares redundantes na strategy page
Na div de header (L30) e na seção de metrics (L120). Ambos apontam para `/advanced-analysis` genérico, sem pré-selecionar a strategy atual.

**Sugestão:** Um link é suficiente. Deve incluir a strategy como query param: `/advanced-analysis?strategy_ids={id}`.

### 🟢 BAIXO: Sem indicador de página ativa nos dropdowns
Quando estou em `/strategy/123`, o dropdown de "Strategies" marca o toggle como active, mas o item `123` dentro do dropdown não tem destaque visual.

---

## 3. Design Visual & Consistência

### 🟡 ALTO: Hardcoded strings em PT-BR e EN misturados
O JavaScript `dashboard.js` usa strings em PT-BR:
```javascript
// dashboard.js L61-64
if (s < 10)   return "agora";
if (s < 60)   return `${s}s atrás`;
if (s < 3600) return `${Math.floor(s / 60)}m atrás`;
return `${Math.floor(s / 3600)}h atrás`;
```

```javascript
// dashboard.js L277
statusEl.textContent = "Erro";
```

Enquanto toda a interface é em inglês (Overview, Settings, Benchmarks, etc.).

```javascript
// benchmarks.html L167
status.textContent = "DataManager indisponível. Exibindo apenas os benchmarks locais.";
```

**Sugestão:** Unificar todas as strings para um idioma. Como a maioria da UI já está em inglês, converter as strings PT-BR remanescentes.

### 🟡 ALTO: Formato numérico inconsistente
O `fmt()` formata números em locale `pt-BR` (ex: `1.234,56`), mas a interface inteira está em inglês.

```javascript
function fmt(value, decimals = 2) {
    return value.toLocaleString("pt-BR", { ... });
}
```

**Sugestão:** Usar `navigator.language` ou `en-US` se a interface é definidamente em inglês. Alternativamente, adicionar uma opção de locale nas Settings.

### 🟡 ALTO: Botão "Kill All" sem destaque visual adequado
O botão "Kill All" na página `/real` (L15) é extremamente perigoso mas visualmente parece um botão inline normal, usando apenas estilos inline:
```html
<button class="btn" style="margin-left: auto; background-color: var(--red); color: white; ...">Kill All</button>
```

**Sugestão:** Separar visualmente com um divisor ou colocar em uma seção "Danger Zone" isolada. Adicionar um ícone de alerta e torná-lo `.btn-danger` com uma classe dedicada.

### 🟠 MÉDIO: Badges com definição duplicada
`.badge-active` e `.badge-inactive` são definidos **duas vezes** no CSS:
- Linhas 553-558 (primeira definição)
- Linhas 1475-1476 (segunda definição, sobrescreve)

### 🟠 MÉDIO: Login page extremamente barebones
A `login.html` é funcional mas visualmente mínima — um card branco sem logo, sem branding, sem animação. Todas as outras páginas possuem skeleton loaders e polish, mas o login é o primeiro contato do usuário.

**Sugestão:** Adicionar o ícone SVG do TradingMonitor como logo centralizado, gradiente de fundo sutil, e uma mensagem de boas-vindas.

### 🟠 MÉDIO: Não há favicon definido
O `base.html` não inclui um `<link rel="icon">`. A aba do browser mostra o ícone genérico.

### 🟠 MÉDIO: Google Fonts não carregadas
O CSS define `--font: "Inter", system-ui` e `--mono: "JetBrains Mono", "Fira Code", monospace`, mas **nenhum `<link>` de Google Fonts** está presente no `base.html`. Os users que não têm Inter/JetBrains Mono instalados localmente caem silenciosamente para `system-ui` ou `monospace`.

**Sugestão:** Adicionar preconnect + link para Google Fonts no `<head>`:
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
```

### 🟢 BAIXO: Emoji como ícone do theme toggle
O botão de tema usa emoji `🌙`/`☀` vs SVG icons no restante da navbar. Fica visualmente inconsistente.

### 🟢 BAIXO: Cor de fundo do chart export
`exportChart()` exporta o canvas sem background, resultando em PNG com fundo transparente (ou branco) que perde o contexto visual do dark mode.

---

## 4. Responsividade & Acessibilidade

### 🔴 CRÍTICO: Navbar não é responsiva
A navbar horizontal simplesmente apertará ou fará overflow em telas pequenas. Não há:
- Hamburguer menu
- Collapse/drawer
- Media queries para a navbar

```css
/* Não existe no CSS: */
@media (max-width: ???) {
    .navbar { ... }
    .nav-links { ... }
}
```

**Sugestão:** Implementar um mobile nav drawer que aparece `< 900px`.

### 🟡 ALTO: Strategy page header fica ilegível em mobile
A `.page-header` da strategy page contém: título + badge + prev/next nav + Advanced Analysis button + Side Filter tabs (3 buttons) + Mode tabs (3 buttons) + Delete button. Tudo em `display:flex` com `flex-wrap: wrap`, mas sem reordenação adequada.

### 🟡 ALTO: Heatmap table não é acessível
A `heatmap-table` usa cores como único meio de transmitir informação (correlação). Não há texto alternativo, tooltip, ou padrão visual para daltônicos.

**Sugestão:** Adicionar o valor numérico visível em cada célula e considerar padrões (hatching) além de cor.

### 🟡 ALTO: Falta de ARIA labels em elementos interativos
- Botões de paginação: não têm `aria-label`
- Botões de sort nas tabelas: não indicam o estado atual de sorting
- Modal close buttons usam "✕" sem `aria-label`
- O WebSocket status badge não tem `role="status"` nem `aria-live`

### 🟠 MÉDIO: `confirm()` e `alert()` nativos
Ações destrutivas como delete e kill-all usam `window.confirm()` / `window.alert()` nativos, que não estilizam com o tema dark e não são acessíveis.

**Sugestão:** Reutilizar o sistema de modais já existente (`.modal-overlay`) para confirmações.

### 🟠 MÉDIO: Tabelas sem scroll horizontal em mobile
As `data-table` não têm wrapper com `overflow-x: auto` em algumas páginas (account strategies, algumas deals tables).

---

## 5. Fluxos de Experiência do Usuário

### 🟡 ALTO: Sem onboarding / empty state significativo
Quando o dashboard está vazio (sem strategies, sem deals), o index mostra apenas "—" nos summary cards e tabelas com skeletons que nunca resolvem em conteúdo.

**Sugestão:** Criar um zero-state informativo na Overview com steps: "1. Download MetricsPublisher.mq5 → 2. Configure no MT5 → 3. Start Ingestion → 4. See data here".

### 🟡 ALTO: Feedback de delete sem undo
Delete de Strategy, Portfolio, Account, e Benchmark são **irreversíveis** e usam apenas `confirm()`. Não há:
- Toast de confirmação com "Undo" (como Gmail)
- Soft-delete com período de recuperação
- Resumo do que será deletado (quantas deals, equity points)

### 🟠 MÉDIO: Contexto perdido em navegação entre strategies
Quando o user navega entre strategies usando as setas `← →`, os filtros de Side (Buy/Sell/Both) e Period (All/1Y/6M/3M/1M) são resetados. O URL não reflete o estado do filtro.

**Sugestão:** Persistir filtros na URL via query params ou `sessionStorage`.

### 🟠 MÉDIO: Settings page salva **todos os settings de uma vez**
A função `saveSettings()` envia Telegram, VaR, initial balance e visualization mode todos juntos, mesmo que o user só tenha editado um campo. Isso pode sobrescrever silenciosamente valores em tabs que o user não visitou.

**Sugestão:** Separar os endpoints de save por grupo/tab.

### 🟠 MÉDIO: Real-time page polling a cada 5s sem indicador visual
A página `/real` faz polling a cada 5 segundos (`setInterval(loadReal, 5000)`), mas não há indicador de "last updated" nem animação de refresh, fazendo o user questionar se os dados estão atualizados.

### 🟢 BAIXO: Sem atalhos de teclado
Não há keyboard shortcuts para navegar entre tabs, fechar modais (Escape existe para dropdowns mas não é universal para modais), ou ações frequentes.

### 🟢 BAIXO: CSV export sem feedback de conclusão
A função `exportDeals()` e `exportTableCSV()` criam e clicam em um link programaticamente, mas o user não recebe confirmação visual de que o download começou.

---

## 6. Performance

### 🔴 CRÍTICO: CDN scripts carregados de forma blocking
O `base.html` carrega **5 external scripts** de CDNs sem `async` ou `defer`:
```html
<script src="https://unpkg.com/htmx.org@2.0.3"></script>
<script src="https://unpkg.com/htmx-ext-ws@2.0.1/ws.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
```

Isso bloqueia o rendering da página até todos os scripts serem baixados e parseados. São ~280KB de JS blocante.

**Sugestão:** Adicionar `defer` em todos (exceto talvez HTMX se é necessário inline). Ou mover para antes do `</body>`.

### 🟡 ALTO: Página de strategy carrega TUDO de uma vez
Ao abrir uma strategy page, dispara simultaneamente:
- `loadInfo()` → `setPageMode()` → `refreshCurrentView()`
  - `loadEquity()`
  - `loadMetrics()`
  - `loadMonthlyPnL()`
  - `loadDistribution()`
  - `loadDeals()`
- `loadBacktests()`
- `loadStrategyNavigation()`

São **7+ API calls paralelas** imediatamente no page load.

**Sugestão:** Lazy load sections below the fold. Carregar equity + metrics primeiro; distribution e deals sob demanda ou por intersection observer.

### 🟠 MÉDIO: Sem cache/stale-while-revalidate nos fetches
Todas as chamadas de API usam `fetch()` sem caching strategy. A navegação back/forward no browser refaz todas as requests do zero.

**Sugestão:** Implementar cache simples em memória com TTL curto (30-60s) pelo menos para dados imutáveis como strategy info.

### 🟠 MÉDIO: Chart.js + HammerJS + Zoom plugin carregados em todas as páginas
A login page e settings page carregam Chart.js + plugins (~150KB) mesmo sem nenhum gráfico. O base template inclui esses scripts incondicionalmente.

**Sugestão:** Mover Chart.js e plugins para `{% block scripts %}` apenas nos templates que possuem gráficos.

---

## 🎯 Prioridades Recomendadas

### Sprint 1 — Quick Wins (1-2 dias)
1. Adicionar `defer` nos scripts CDN do `base.html`
2. Carregar Google Fonts Inter + JetBrains Mono
3. Adicionar favicon
4. Unificar strings PT-BR → EN no JS
5. Corrigir badge duplicado no CSS

### Sprint 2 — Estrutura (3-5 dias)
1. Extrair JS inline de `strategy.html` → `page-strategy.js`
2. Migrar inline styles de `settings.html` para classes CSS
3. Implementar navbar responsivo com hamburguer menu
4. Criar confirmation modal reutilizável (substituir `confirm()`)

### Sprint 3 — UX Polish (3-5 dias)
1. Adicionar breadcrumbs em páginas internas
2. Criar zero-state/onboarding na Overview
3. Implementar lazy loading em sections de strategy page
4. Adicionar "Last updated" na página Real com countdown visual
5. Mover Chart.js para load condicional

### Sprint 4 — Acessibilidade & Refinamento
1. Adicionar ARIA labels em todos os elementos interativos
2. Implementar keyboard navigation nas tabelas
3. Migrar heatmap para ser color-blind friendly
4. Criar `.btn-danger` class para kill/delete buttons
