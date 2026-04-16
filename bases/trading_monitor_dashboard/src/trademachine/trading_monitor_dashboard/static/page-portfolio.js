/* ── portfolio.html page-specific initialization ──────────────────────────────── */

// Note: PORTFOLIO_ID is a Jinja variable injected by the template (not defined here).
// loadPortfolio, loadMetrics, loadEquity, loadCalendar are in api-client.js.
// renderPortfolioStrategies, renderEquityChart, renderCalendar are in table-renderer.js.

/* ── Portfolio Navigation ──────────────────────────────────────────────────── */

let _portfolioNavList = [];
let _portfolioNavIndex = -1;

function comparePortfolioIds(a, b) {
    return String(a).localeCompare(String(b), undefined, {
        numeric: true,
        sensitivity: "base",
    });
}

function renderPortfolioNavigation() {
    const prevBtn = document.getElementById("portfolio-prev-btn");
    const nextBtn = document.getElementById("portfolio-next-btn");
    if (!prevBtn || !nextBtn) return;

    const hasPrev = _portfolioNavIndex > 0;
    const hasNext = _portfolioNavIndex >= 0 && _portfolioNavIndex < _portfolioNavList.length - 1;
    prevBtn.disabled = !hasPrev;
    nextBtn.disabled = !hasNext;

    prevBtn.title = hasPrev
        ? `Previous portfolio: ${_portfolioNavList[_portfolioNavIndex - 1].name || _portfolioNavList[_portfolioNavIndex - 1].id}`
        : "Previous portfolio";
    nextBtn.title = hasNext
        ? `Next portfolio: ${_portfolioNavList[_portfolioNavIndex + 1].name || _portfolioNavList[_portfolioNavIndex + 1].id}`
        : "Next portfolio";
}

function navigatePortfolio(offset) {
    const target = _portfolioNavList[_portfolioNavIndex + offset];
    if (!target) return;
    window.location.href = `/portfolio/${encodeURIComponent(target.id)}`;
}

async function loadPortfolioNavigation() {
    try {
        const portfolios = await fetchJson("/api/portfolios/nav");
        _portfolioNavList = [...portfolios].sort((a, b) =>
            comparePortfolioIds(a.id, b.id)
        );
        _portfolioNavIndex = _portfolioNavList.findIndex(
            (p) => String(p.id) === String(PORTFOLIO_ID)
        );
    } catch (error) {
        _portfolioNavList = [];
        _portfolioNavIndex = -1;
    }
    renderPortfolioNavigation();
}

window.addEventListener("ws-event", function(e) {
    const { topic } = e.detail;
    if (topic === "DEAL" || topic === "EQUITY") { loadMetrics(); loadEquity(); loadCalendar(); loadPortfolioStrategies(); loadPortfolioDeals(); }
});

window.addEventListener("tm-theme-change", function() {
    loadEquity();
});

function updateAdvancedAnalysisLink() {
    const link = document.getElementById("advanced-analysis-link");
    if (!link || !_portfolio) return;

    const params = new URLSearchParams();
    const strategyIds = Array.isArray(_portfolio.strategy_ids) ? _portfolio.strategy_ids : [];
    const historyType = _portfolio.real_account ? "real" : "demo";

    link.dataset.hasStrategies = strategyIds.length ? "true" : "false";
    strategyIds.forEach((strategyId) => params.append("strategy_ids", strategyId));
    params.set("history_type", historyType);

    const initialBalance = Number(_portfolio.initial_balance);
    if (Number.isFinite(initialBalance)) {
        params.set("initial_balance", String(initialBalance));
    }

    if (strategyIds.length) {
        link.href = `/advanced-analysis?${params.toString()}`;
        link.removeAttribute("aria-disabled");
    } else {
        link.href = "#";
        link.setAttribute("aria-disabled", "true");
    }

    link.title = strategyIds.length
        ? "Open advanced analysis with this portfolio's strategies."
        : "This portfolio has no linked strategies.";
}

function handleAdvancedAnalysisClick(event) {
    const link = document.getElementById("advanced-analysis-link");
    if (link?.dataset.hasStrategies === "true") return;

    event.preventDefault();
    if (typeof showToast === "function") {
        showToast(
            "No strategies linked",
            "Add at least one strategy to this portfolio before opening Advanced Analysis.",
            "error"
        );
    }
}

async function loadPortfolioStrategies() {
    try {
        const res = await fetch(`/api/portfolios/${PORTFOLIO_ID}/strategies`);
        _portStratList = await res.json();
        renderPortfolioStrategies();
        document.getElementById("strategies-badge").textContent = `${_portStratList.length} strategies`;
    } catch(e) {
        console.error("Failed to load portfolio strategies:", e);
    }
}

/* ── Portfolio Deals ───────────────────────────────────────────────────────────── */

let _portDealsSearchTimer = null;
let _portDealsSortCol = "timestamp";
let _portDealsSortAsc = false;

function filterPortfolioDeals() {
    clearTimeout(_portDealsSearchTimer);
    _portDealsSearchTimer = setTimeout(() => loadPortfolioDeals(1), 350);
}

function portDealsSortBy(col) {
    ({ col: _portDealsSortCol, asc: _portDealsSortAsc } = toggleSort(_portDealsSortCol, _portDealsSortAsc, col, false));
    loadPortfolioDeals(1);
}

async function loadPortfolioDeals(page = 1) {
    const q = (document.getElementById("deals-search")?.value || "").trim();
    const ps = parseInt(document.getElementById("deals-page-size")?.value || "25");
    try {
        let url = `/api/portfolios/${PORTFOLIO_ID}/deals?page=${page}&page_size=${ps}`;
        if (q) url += `&q=${encodeURIComponent(q)}`;
        const res = await fetch(url);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            document.getElementById("deals-container").innerHTML =
                `<p class="error">${err.detail || "Error loading deals (status " + res.status + ")"}</p>`;
            return;
        }
        const data = await res.json();
        renderPortfolioDeals(data);
    } catch(e) {
        document.getElementById("deals-container").innerHTML = '<p class="error">Error loading deals.</p>';
    }
}

function renderPortfolioDeals(data) {
    document.getElementById("deals-count").textContent = `${data.total} deals`;
    const container = document.getElementById("deals-container");
    if (!data.items || data.items.length === 0) {
        container.innerHTML = '<p class="empty-state">No deals found.</p>';
        document.getElementById("deals-pagination").innerHTML = "";
        return;
    }

    const items = [...data.items];
    items.sort((a, b) => {
        let av = a[_portDealsSortCol], bv = b[_portDealsSortCol];
        if (_portDealsSortCol === "net") {
            av = (a.profit || 0) + (a.commission || 0) + (a.swap || 0);
            bv = (b.profit || 0) + (b.commission || 0) + (b.swap || 0);
        }
        if (av == null) av = "";
        if (bv == null) bv = "";
        if (typeof av === "string") av = av.toLowerCase();
        if (typeof bv === "string") bv = bv.toLowerCase();
        if (av < bv) return _portDealsSortAsc ? -1 : 1;
        if (av > bv) return _portDealsSortAsc ? 1 : -1;
        return 0;
    });

    const rows = items.map(d => {
        const profit = d.profit || 0;
        const swap = d.swap || 0;
        const net = profit + (d.commission || 0) + (d.swap || 0);
        const profitCls = profit > 0 ? "profit-positive" : profit < 0 ? "profit-negative" : "";
        const swapCls = swap > 0 ? "profit-positive" : swap < 0 ? "profit-negative" : "";
        const netCls = net > 0 ? "profit-positive" : net < 0 ? "profit-negative" : "";
        const date = formatMt5ServerTimestamp(d.timestamp);
        return `<tr>
            <td>${date}</td>
            <td class="mono">${d.strategy_id}</td>
            <td class="mono">${d.ticket}</td>
            <td>${d.symbol || "—"}</td>
            <td class="type-${d.type}">${d.type.toUpperCase()}</td>
            <td>${fmt(d.volume, 2)}</td>
            <td>${fmt(d.price, 2)}</td>
            <td class="${profitCls}">${fmt(profit)}</td>
            <td class="text-muted">${fmt(d.commission || 0)}</td>
            <td class="${swapCls}">${fmt(swap)}</td>
            <td class="${netCls}">${fmt(net)}</td>
        </tr>`;
    }).join("");

    function thD(label, col) {
        const arrow = _portDealsSortCol === col ? (_portDealsSortAsc ? " ▲" : " ▼") : "";
        return `<th class="sortable" onclick="portDealsSortBy('${col}')">${label}${arrow}</th>`;
    }

    container.innerHTML = `
        <div class="table-responsive"><table class="data-table">
            <thead>
                <tr>
                    ${thD("Date","timestamp")}${thD("Strategy","strategy_id")}${thD("Ticket","ticket")}${thD("Symbol","symbol")}${thD("Type","type")}
                    ${thD("Volume","volume")}${thD("Price","price")}${thD("Profit","profit")}
                    <th>Commission</th><th>Swap</th>${thD("Net","net")}
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table></div>`;

    const totalPages = Math.ceil(data.total / data.page_size);
    const pg = document.getElementById("deals-pagination");
    if (totalPages <= 1) { pg.innerHTML = ""; return; }
    pg.innerHTML = `
        <button onclick="loadPortfolioDeals(${data.page - 1})" ${data.page <= 1 ? "disabled" : ""}>← Previous</button>
        <span>Page ${data.page} of ${totalPages}</span>
        <button onclick="loadPortfolioDeals(${data.page + 1})" ${data.page >= totalPages ? "disabled" : ""}>Next →</button>`;
}

/* ── P&L Analysis & Trade Distribution ─────────────────────────────────────── */

let _portMonthlyChart = null;
let _portAnnualChart = null;
let _portDistHourChart = null;
let _portDistDowChart = null;

async function loadPortfolioPnl() {
    try {
        const res = await fetch(`/api/portfolios/${PORTFOLIO_ID}/daily`);
        const rows = await res.json();
        const { labels, values } = aggregateMonthlyPnl(rows);
        _portMonthlyChart = renderPnlBarChart(
            "monthly-pnl-chart", "monthly-pnl-wrapper",
            monthLabelsForDisplay(labels), values, _portMonthlyChart
        );
        const annual = aggregateAnnualPnl(labels, values);
        _portAnnualChart = renderPnlBarChart(
            "annual-pnl-chart", "annual-pnl-wrapper",
            annual.labels, annual.values, _portAnnualChart
        );
    } catch (e) { console.error("Portfolio P&L error:", e); }
}

async function loadPortfolioDistribution() {
    try {
        const res = await fetch(`/api/portfolios/${PORTFOLIO_ID}/trade-stats`);
        const data = await res.json();
        _portDistHourChart = renderDistBarChart(
            "dist-hour-chart", "dist-hour-wrapper",
            data.by_hour.map(r => r.hour + ":00"),
            data.by_hour.map(r => r.net_profit),
            _portDistHourChart
        );
        _portDistDowChart = renderDistBarChart(
            "dist-dow-chart", "dist-dow-wrapper",
            data.by_dow.map(r => r.label),
            data.by_dow.map(r => r.net_profit),
            _portDistDowChart
        );
    } catch (e) { console.error("Portfolio distribution error:", e); }
}

// Restore saved page size
const _savedPortDealsPs = localStorage.getItem("tm-port-deals-page-size");
if (_savedPortDealsPs) {
    const _sel = document.getElementById("deals-page-size");
    if (_sel) _sel.value = _savedPortDealsPs;
}

(async () => {
    document.querySelectorAll(".period-tab[data-es]").forEach((button) =>
        button.classList.toggle("active", button.dataset.es === _equityScale)
    );
    document.getElementById("advanced-analysis-link")?.addEventListener("click", handleAdvancedAnalysisClick);
    await loadPortfolio();
    loadPortfolioNavigation();
    loadMetrics();
    loadEquity();
    loadCalendar();
    loadPortfolioPnl();
    loadPortfolioDistribution();
    loadPortfolioStrategies();
    loadPortfolioDeals();
})();
