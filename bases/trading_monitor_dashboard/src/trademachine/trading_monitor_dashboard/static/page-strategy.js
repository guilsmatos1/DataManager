// ── page-strategy.js ────────────────────────────────────────────────────────
// All JS logic for the strategy detail page (strategy.html).
// STRATEGY_ID is injected by the template as a global const before this file.
// ────────────────────────────────────────────────────────────────────────────

// equityChart, underwaterChart, _allEquityPoints, _equityPeriod, _equityScale declared by table-renderer.js
equityChart = null;
let _currentStrategy = null;
let _currentMetrics = null;
_allEquityPoints = [];
_equityPeriod = localStorage.getItem("tm-equity-period") || "all";
_equityScale  = localStorage.getItem("tm-equity-scale")  || "monetary";
underwaterChart = null;
let _distHourChart = null;
let _distDowChart  = null;
let _dealsSearchTimer = null;
const MIN_STRATEGY_TRADES_FOR_CHARTS = 15;
const PAGE_SIZE = 25;
let _dealsSortCol = "timestamp";
let _dealsSortAsc = false;
let _viewController = null;
let _strategyNavList = [];
let _strategyNavIndex = -1;
let _currentTotalTrades = null;

function compareStrategyIds(a, b) {
    return String(a).localeCompare(String(b), undefined, {
        numeric: true,
        sensitivity: "base",
    });
}

function renderStrategyNavigation() {
    const prevBtn = document.getElementById("strategy-prev-btn");
    const nextBtn = document.getElementById("strategy-next-btn");
    if (!prevBtn || !nextBtn) return;

    const hasPrev = _strategyNavIndex > 0;
    const hasNext = _strategyNavIndex >= 0 && _strategyNavIndex < _strategyNavList.length - 1;
    prevBtn.disabled = !hasPrev;
    nextBtn.disabled = !hasNext;

    prevBtn.title = hasPrev
        ? `Previous strategy: ${_strategyNavList[_strategyNavIndex - 1].name || _strategyNavList[_strategyNavIndex - 1].id}`
        : "Previous strategy";
    nextBtn.title = hasNext
        ? `Next strategy: ${_strategyNavList[_strategyNavIndex + 1].name || _strategyNavList[_strategyNavIndex + 1].id}`
        : "Next strategy";
}

function navigateStrategy(offset) {
    const target = _strategyNavList[_strategyNavIndex + offset];
    if (!target) return;
    window.location.href = `/strategy/${encodeURIComponent(target.id)}`;
}

async function loadStrategyNavigation() {
    try {
        const strategies = await fetchJson("/api/strategies");
        _strategyNavList = [...strategies].sort((a, b) => compareStrategyIds(a.id, b.id));
        _strategyNavIndex = _strategyNavList.findIndex(
            (strategy) => String(strategy.id) === String(STRATEGY_ID)
        );
    } catch (error) {
        _strategyNavList = [];
        _strategyNavIndex = -1;
    }
    renderStrategyNavigation();
}

/* ── Side filter (both / long / short) ── */
let _sideFilter = "both";
function sideParam() { return _sideFilter !== "both" ? "&side=" + _sideFilter : ""; }
function currentViewKey() { return `${_pageMode}:${_sideFilter}:${_selectedBtId || ""}`; }

function beginViewRequest() {
    if (_viewController) _viewController.abort();
    _viewController = new AbortController();
    return _viewController.signal;
}

function isAbortError(error) {
    return error?.name === "AbortError";
}

function selectedBacktest() {
    if (!Array.isArray(_backtests) || _selectedBtId == null) return null;
    return _backtests.find((bt) => bt.id === _selectedBtId) || null;
}

function getStrategyEquityPctOptions() {
    // Return (%) metric uses Profit / initial_balance * 100.
    // For live/incubation equity, backend baselines at 0 (equity = cumulative PnL),
    // so pctBaseline = 0. For backtest equity, backend baselines at initial_balance,
    // so pctBaseline = initial_balance. pctDenominator is always initial_balance.
    if (_pageMode === "backtest") {
        const bt = selectedBacktest();
        const ib = Number(bt?.initial_balance);
        if (!Number.isFinite(ib) || ib <= 0) return {};
        return { pctBaseline: ib, pctDenominator: ib };
    }
    const ib = Number(_currentStrategy?.initial_balance);
    if (!Number.isFinite(ib) || ib <= 0) return {};
    return { pctBaseline: 0, pctDenominator: ib };
}

function ensureCanvas(wrapperId, canvasId) {
    let canvas = document.getElementById(canvasId);
    if (canvas) return canvas;
    const wrapper = document.getElementById(wrapperId);
    if (!wrapper) return null;
    wrapper.innerHTML = `<canvas id="${canvasId}"></canvas>`;
    return document.getElementById(canvasId);
}

function renderChartEmptyState(wrapperId, message = "No data yet.") {
    const wrapper = document.getElementById(wrapperId);
    if (!wrapper) return;
    wrapper.innerHTML = `<p class="empty-state" style="padding:1rem 0">${message}</p>`;
}

function extractTotalTrades(metrics) {
    const trades = metrics?.["Total Trades"];
    return Number.isFinite(Number(trades)) ? Number(trades) : null;
}

function renderTradeThresholdState() {
    const message = `At least ${MIN_STRATEGY_TRADES_FOR_CHARTS} trades are required to render equity and drawdown charts.`;
    if (equityChart) {
        equityChart.destroy();
        equityChart = null;
    }
    if (underwaterChart) {
        underwaterChart.destroy();
        underwaterChart = null;
    }
    const equityWrapper = document.querySelector("#chart-section .chart-wrapper");
    if (equityWrapper) {
        equityWrapper.innerHTML = `<p class="empty-state" style="padding:2rem 0">${message}</p>`;
    }
    const drawdownWrapper = document.querySelector("#underwater-section .chart-wrapper");
    if (drawdownWrapper) {
        drawdownWrapper.innerHTML = `<p class="empty-state" style="padding:1rem 0">${message}</p>`;
    }
}

function maybeRenderStrategyCharts() {
    if (_currentTotalTrades == null) return;
    if (_currentTotalTrades < MIN_STRATEGY_TRADES_FOR_CHARTS) {
        renderTradeThresholdState();
        return;
    }
    renderEquityChart(filterEquityPointsByPeriod(_allEquityPoints, _equityPeriod));
}

let _visibleSections = new Set();
let _sectionLoadedKey = {};

function initLazyLoading() {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                _visibleSections.add(entry.target.id);
                loadSection(entry.target.id);
            } else {
                _visibleSections.delete(entry.target.id);
            }
        });
    }, { rootMargin: "300px" });

    document.querySelectorAll("#monthly-section, #distribution-section, #deals-section").forEach(el => {
        if (el) observer.observe(el);
    });
}

function loadSection(sectionId, signal = null) {
    if (!signal && _viewController) signal = _viewController.signal;
    const loadKey = `${sectionId}:${currentViewKey()}`;
    if (_sectionLoadedKey[sectionId] === loadKey) return;

    _sectionLoadedKey[sectionId] = loadKey;

    if (_pageMode === "backtest") {
        if (!_selectedBtId) return;
        if (sectionId === "monthly-section")      loadBtMonthlyPnL(_selectedBtId, signal);
        if (sectionId === "distribution-section") loadBtDistribution(_selectedBtId, signal);
        if (sectionId === "deals-section")        loadBtDealsInMain(_selectedBtId, 1, signal);
    } else {
        if (sectionId === "monthly-section")      loadMonthlyPnL(signal);
        if (sectionId === "distribution-section") loadDistribution(signal);
        if (sectionId === "deals-section")        loadDeals(1, signal);
    }
}

function refreshCurrentView() {
    const signal = beginViewRequest();
    const reportBtn = document.getElementById("full-report-btn");

    if (_pageMode === "backtest") {
        if (_selectedBtId) {
            if (reportBtn) {
                reportBtn.href = `/backtest/${_selectedBtId}/quantstats-report`;
                reportBtn.style.display = "";
            }
            loadBtEquityInMain(_selectedBtId, signal);
            loadBtMetricsInMain(_selectedBtId, signal);
        } else {
            if (reportBtn) reportBtn.style.display = "none";
        }
    } else {
        if (reportBtn) {
            reportBtn.href = `/strategy/${STRATEGY_ID}/quantstats-report`;
            reportBtn.style.display = "";
        }
        loadEquity(signal);
        loadMetrics(signal);
    }

    for (const sec of _visibleSections) {
        loadSection(sec, signal);
    }
}

function showMetricsSkeleton() {
    document.getElementById("metrics-container").innerHTML =
        '<div class="skel skel-metric"></div><div class="skel skel-metric"></div>' +
        '<div class="skel skel-metric"></div><div class="skel skel-metric"></div>' +
        '<div class="skel skel-metric"></div><div class="skel skel-metric"></div>' +
        '<div class="skel skel-metric"></div>';
}

function renderStrategyMetrics(container, data) {
    renderMetricsGrid(container, data, {
        hiddenKeys: ["gross profit", "gross loss", "expected value"],
        integerKeys: ["total trades"],
    });
}

function resetSideFilteredVisualState() {
    _allEquityPoints = [];

    if (equityChart) {
        equityChart.destroy();
        equityChart = null;
    }
    if (underwaterChart) {
        underwaterChart.destroy();
        underwaterChart = null;
    }
    if (_monthlyChart) {
        _monthlyChart.destroy();
        _monthlyChart = null;
    }
    if (_annualChart) {
        _annualChart.destroy();
        _annualChart = null;
    }
    if (window._distHourChart) {
        window._distHourChart.destroy();
        window._distHourChart = null;
    }
    if (window._distDowChart) {
        window._distDowChart.destroy();
        window._distDowChart = null;
    }

    const equityWrapper = document.querySelector("#chart-section .chart-wrapper");
    if (equityWrapper) {
        equityWrapper.innerHTML = '<p class="empty-state" style="padding:2rem 0">Loading filtered equity...</p>';
    }

    const drawdownWrapper = document.querySelector("#underwater-section .chart-wrapper");
    if (drawdownWrapper) {
        drawdownWrapper.innerHTML = '<p class="empty-state" style="padding:1rem 0">Loading filtered drawdown...</p>';
    }

    renderChartEmptyState("monthly-pnl-wrapper", "Loading filtered P&L...");
    renderChartEmptyState("annual-pnl-wrapper", "Loading filtered P&L...");
    renderChartEmptyState("dist-hour-wrapper", "Loading filtered distribution...");
    renderChartEmptyState("dist-dow-wrapper", "Loading filtered distribution...");
}

function setSideFilter(side) {
    _sideFilter = side;
    _currentTotalTrades = null;
    document.querySelectorAll("#side-filter-tabs .period-tab").forEach(b =>
        b.classList.toggle("active", b.dataset.side === side));
    const eqInfo = document.getElementById("equity-side-info");
    if (eqInfo) {
        if (side === "both") {
            eqInfo.style.display = "none";
        } else {
            eqInfo.textContent = `Equity filtered: ${side[0].toUpperCase()}${side.slice(1)}`;
            eqInfo.style.display = "";
        }
    }
    _currentMetrics = null;
    showMetricsSkeleton();
    resetSideFilteredVisualState();
    refreshCurrentView();
}

/* ── Page mode (backtest / incubation / real) ── */
let _pageMode = "incubation";
let _selectedBtId = null;
let _backtests = [];

function updateTabAvailability() {
    const incubationBtn = document.querySelector('.period-tab[data-sm="incubation"]');
    const realBtn       = document.querySelector('.period-tab[data-sm="real"]');
    const backtestBtn   = document.querySelector('.period-tab[data-sm="backtest"]');

    if (_currentStrategy) {
        const isReal = !!_currentStrategy.real_account;
        incubationBtn?.classList.toggle("disabled", isReal);
        realBtn?.classList.toggle("disabled", !isReal);
    }
    backtestBtn?.classList.toggle("disabled", _backtests.length === 0);
}

function setPageMode(mode) {
    const btn = document.querySelector(`.period-tab[data-sm="${mode}"]`);
    if (btn && btn.classList.contains("disabled")) return;
    _pageMode = mode;
    _currentTotalTrades = null;
    document.querySelectorAll(".period-tab[data-sm]").forEach(b =>
        b.classList.toggle("active", b.dataset.sm === mode));

    const isBt = mode === "backtest";
    document.getElementById("bt-run-selector").style.display   = isBt ? "" : "none";
    document.getElementById("deals-live-panel").style.display  = isBt ? "none" : "";

    if (!isBt) {
        refreshCurrentView();
    } else {
        // Reset metrics to skeleton
        document.getElementById("metrics-container").innerHTML =
            '<div class="skel skel-metric"></div><div class="skel skel-metric"></div>' +
            '<div class="skel skel-metric"></div><div class="skel skel-metric"></div>';
        // Reset equity chart
        equityChart = destroyChart(equityChart);
        const wrapper = document.querySelector("#chart-section .chart-wrapper");
        if (wrapper) wrapper.innerHTML = '<canvas id="equity-chart"></canvas>';
        // Reset underwater chart
        underwaterChart = destroyChart(underwaterChart);
        const uwWrapper = document.querySelector("#underwater-section .chart-wrapper");
        if (uwWrapper) uwWrapper.innerHTML = '<canvas id="underwater-chart"></canvas>';
        // Reset P&L and distribution charts
        _monthlyChart = destroyChart(_monthlyChart);
        _annualChart = destroyChart(_annualChart);
        window._distHourChart = destroyChart(window._distHourChart);
        window._distDowChart = destroyChart(window._distDowChart);
        // Reset deals panel
        document.getElementById("deals-container").innerHTML =
            '<div class="skel skel-row"></div><div class="skel skel-row"></div>' +
            '<div class="skel skel-row"></div>';
        document.getElementById("pagination").innerHTML = "";
        document.getElementById("deals-count").textContent = "";
        // Load backtest runs list
        loadBacktests();
    }
}

async function selectBtRun(btId) {
    _selectedBtId = btId;
    renderBacktestsList(); // re-render to highlight selected row
    refreshCurrentView();
}

async function loadBtMonthlyPnL(btId, signal = null) {
    const requestKey = currentViewKey();
    try {
        const res = await fetch(`/api/backtests/${btId}/daily?_=1${sideParam()}`, { signal });
        const rows = await res.json();
        if (requestKey !== currentViewKey()) return;
        const agg = {};
        rows.forEach(r => {
            const key = r.date.slice(0, 7);
            agg[key] = (agg[key] || 0) + r.net_profit;
        });
        _monthlyRawLabels = Object.keys(agg).sort();
        _monthlyValues    = _monthlyRawLabels.map(k => parseFloat(agg[k].toFixed(2)));
        renderMonthlyChart();
        renderAnnualChart();
    } catch(e) { if (!isAbortError(e)) console.error("Bt Monthly P&L error:", e); }
}

async function loadBtDistribution(btId, signal = null) {
    const requestKey = currentViewKey();
    try {
        const res = await fetch(`/api/backtests/${btId}/trade-stats?_=1${sideParam()}`, { signal });
        const data = await res.json();
        if (requestKey !== currentViewKey()) return;
        renderDistChart("dist-hour-chart", "_distHourChart",
            data.by_hour.map(r => r.hour + ":00"),
            data.by_hour.map(r => r.count),
            data.by_hour.map(r => r.net_profit),
            (v) => v < 0 ? CHART_COLORS.redSoft : CHART_COLORS.greenSoft
        );
        renderDistChart("dist-dow-chart", "_distDowChart",
            data.by_dow.map(r => r.label),
            data.by_dow.map(r => r.count),
            data.by_dow.map(r => r.net_profit),
            (v) => v < 0 ? CHART_COLORS.redSoft : CHART_COLORS.greenSoft
        );
    } catch(e) { if (!isAbortError(e)) console.error("Bt Distribution error:", e); }
}

async function loadBtMetricsInMain(btId, signal = null) {
    const requestKey = currentViewKey();
    const container = document.getElementById("metrics-container");
    showMetricsSkeleton();
    try {
        const qs = new URLSearchParams({ _: String(Date.now()) });
        if (_sideFilter !== "both") qs.set("side", _sideFilter);
        const res = await fetch(`/api/backtests/${btId}/metrics?${qs.toString()}`, { signal });
        const data = await res.json();
        if (requestKey !== currentViewKey()) return;
        if (data.error) {
            _currentTotalTrades = null;
            container.innerHTML = `<p class="empty-state">${data.error}</p>`;
            return;
        }
        _currentTotalTrades = extractTotalTrades(data);
        renderStrategyMetrics(container, data);
        maybeRenderStrategyCharts();
    } catch(e) {
        if (!isAbortError(e)) {
            container.innerHTML = '<p class="error">Error loading metrics.</p>';
        }
    }
}

async function loadBtEquityInMain(btId, signal = null) {
    const requestKey = currentViewKey();
    try {
        const qs = new URLSearchParams({ _: String(Date.now()) });
        if (_sideFilter !== "both") qs.set("side", _sideFilter);
        const res = await fetch(`/api/backtests/${btId}/equity?${qs.toString()}`, { signal });
        const points = await res.json();
        if (requestKey !== currentViewKey()) return;
        if (!points.length) {
            const wrapper = document.querySelector("#chart-section .chart-wrapper");
            if (wrapper) wrapper.innerHTML = '<p class="empty-state" style="padding:2rem 0">No equity data yet.</p>';
            _allEquityPoints = [];
            return;
        }
        _allEquityPoints = points;
        if (!document.getElementById("equity-chart")) {
            const wrapper = document.querySelector("#chart-section .chart-wrapper");
            if (wrapper) wrapper.innerHTML = '<canvas id="equity-chart"></canvas>';
        }
        maybeRenderStrategyCharts();
    } catch(e) {
        if (!isAbortError(e)) console.error("BT equity (main) error:", e);
    }
}

async function loadBtDealsInMain(btId, page = 1, signal = null) {
    const requestKey = currentViewKey();
    const container = document.getElementById("deals-container");
    document.getElementById("deals-live-panel").style.display = "";
    try {
        const res = await fetch(`/api/backtests/${btId}/deals?page=${page}&page_size=50${sideParam()}`, { signal });
        if (requestKey !== currentViewKey()) return;
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            container.innerHTML =
                `<p class="error">${err.detail || "Error loading deals (status " + res.status + ")"}</p>`;
            return;
        }
        const data = await res.json();
        document.getElementById("deals-count").textContent = `${data.total} deals`;
        if (!data.items || !data.items.length) {
            container.innerHTML = '<p class="empty-state">No deals.</p>';
            document.getElementById("pagination").innerHTML = "";
            return;
        }
        const rows = data.items.map(d => {
            const profit = d.profit || 0;
            const net = profit + (d.commission || 0) + (d.swap || 0);
            const profitCls = profit > 0 ? "profit-positive" : profit < 0 ? "profit-negative" : "";
            const netCls    = net    > 0 ? "profit-positive" : net    < 0 ? "profit-negative" : "";
            return `<tr>
                <td>${formatMt5ServerTimestamp(d.timestamp)}</td>
                <td class="mono">${d.ticket}</td>
                <td>${d.symbol || "—"}</td>
                <td class="type-${d.type}">${d.type.toUpperCase()}</td>
                <td>${fmt(d.volume, 2)}</td><td>${fmt(d.price, 2)}</td>
                <td class="${profitCls}">${fmt(profit)}</td>
                <td class="text-muted">${fmt(d.commission || 0)}</td>
                <td class="text-muted">${fmt(d.swap || 0)}</td>
                <td class="${netCls}">${fmt(net)}</td>
            </tr>`;
        }).join("");
        container.innerHTML = `<div class="table-responsive"><table class="data-table">
            <thead><tr>
                <th>Date</th><th>Ticket</th><th>Symbol</th><th>Type</th>
                <th>Volume</th><th>Price</th><th>Profit</th>
                <th>Commission</th><th>Swap</th><th>Net</th>
            </tr></thead>
            <tbody>${rows}</tbody>
        </table></div>`;
        const totalPages = Math.ceil(data.total / data.page_size);
        const pg = document.getElementById("pagination");
        pg.innerHTML = totalPages <= 1 ? "" : `
            <button onclick="loadBtDealsInMain(${btId},${page - 1})" ${page <= 1 ? "disabled" : ""}>← Previous</button>
            <span>Page ${page} of ${totalPages}</span>
            <button onclick="loadBtDealsInMain(${btId},${page + 1})" ${page >= totalPages ? "disabled" : ""}>Next →</button>`;
    } catch(e) {
        if (!isAbortError(e)) {
            container.innerHTML = '<p class="error">Error loading deals.</p>';
        }
    }
}

function toggleEdit() {
    const form = document.getElementById("edit-form");
    const isHidden = form.style.display === "none";
    if (isHidden && _currentStrategy) {
        const s = _currentStrategy;
        document.getElementById("edit-name").value = s.name || "";
        document.getElementById("edit-symbol").value = s.symbol || "";
        document.getElementById("edit-timeframe").value = s.timeframe || "";
        document.getElementById("edit-style").value = s.operational_style || "";
        document.getElementById("edit-duration").value = s.trade_duration || "";
        document.getElementById("edit-description").value = s.description || "";
    }
    form.style.display = isHidden ? "block" : "none";
    document.getElementById("edit-status").textContent = "";
}

async function saveStrategy() {
    const status = document.getElementById("edit-status");
    status.textContent = "Saving...";
    const payload = {
        name: document.getElementById("edit-name").value || null,
        symbol: document.getElementById("edit-symbol").value || null,
        timeframe: document.getElementById("edit-timeframe").value || null,
        operational_style: document.getElementById("edit-style").value || null,
        trade_duration: document.getElementById("edit-duration").value || null,
        description: document.getElementById("edit-description").value || null,
    };
    try {
        const res = await fetch(`/api/strategies/${STRATEGY_ID}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error(await res.text());
        _currentStrategy = await res.json();
        status.textContent = "✅ Saved";
        setTimeout(() => {
            document.getElementById("edit-form").style.display = "none";
            loadInfo();
        }, 800);
    } catch(err) {
        status.textContent = "❌ Error: " + err.message;
    }
}

async function confirmDeleteStrategy() {
    const strategyName = _currentStrategy?.name || STRATEGY_ID;
    const confirmed = await showConfirmModal(
        "Delete Strategy",
        `Delete strategy <strong>${strategyName}</strong> (#${STRATEGY_ID})?<br><br>This will permanently remove all associated deals and equity data.`,
        { confirmLabel: "Delete", confirmClass: "btn-danger" }
    );
    if (!confirmed) return;

    try {
        const res = await fetch(`/api/strategies/${STRATEGY_ID}`, { method: "DELETE" });
        if (res.ok) {
            window.location.href = "/";
            return;
        }
        showToast("Error", "Failed to delete strategy.", "error");
    } catch (error) {
        showToast("Error", "Failed to delete strategy.", "error");
    }
}

async function loadInfo() {
    try {
        const res = await fetch(`/api/strategies/${STRATEGY_ID}`);
        if (!res.ok) return;
        const s = await res.json();
        _currentStrategy = s;
        checkDrawdownAlert();

        document.getElementById("strategy-title").innerHTML =
            `<span class="mono">#${s.id}</span><button class="btn-copy-id" style="opacity:1;font-size:0.9em;margin-left:0.25rem" onclick="copyId('${s.id}',this)" title="Copy Magic Number">⎘</button>`;

        const badge = document.getElementById("strategy-status-badge");
        badge.textContent = s.live ? "Live" : "Incubation";
        badge.className = `badge ${s.live ? "badge-live" : "badge-incubation"}`;

        const fields = [
            ["Name",             s.name],
            ["Symbol",           s.symbol],
            ["Timeframe",         s.timeframe],
            ["Operational Style", s.operational_style],
            ["Trade Duration",    s.trade_duration],
            ["Account Type",      s.real_account ? "Real" : "Demo"],
            ["Initial Balance",   s.initial_balance != null ? `${fmt(s.initial_balance)} ${s.base_currency || ""}` : null],
            ["Currency",          s.base_currency],
            ["Linked Account",    s.account_name ? `${s.account_name} (${s.account_id})` : s.account_id],
            ["Description",       s.description],
        ];

        const container = document.getElementById("info-container");
        container.innerHTML = fields
            .filter(([, v]) => v != null && v !== "")
            .map(([label, value]) => `
                <div class="info-item">
                    <span class="info-label">${label}</span>
                    <span class="info-value">${esc(value)}</span>
                </div>`).join("");

        updateTabAvailability();
        if (s.real_account === true) {
            setPageMode("real");
        } else {
            setPageMode("incubation");
        }
    } catch(e) { console.error("Info load error:", e); }
}

async function loadMetrics(signal = null) {
    const requestKey = currentViewKey();
    showMetricsSkeleton();
    try {
        const qs = new URLSearchParams({ _: String(Date.now()) });
        if (_sideFilter !== "both") qs.set("side", _sideFilter);
        const res = await fetch(`/api/strategies/${STRATEGY_ID}/metrics?${qs.toString()}`, { signal });
        const data = await res.json();
        if (requestKey !== currentViewKey()) return;
        const container = document.getElementById("metrics-container");
        if (data.error) {
            _currentTotalTrades = null;
            container.innerHTML = `<p class="empty-state">${data.error}</p>`;
            return;
        }
        renderStrategyMetrics(container, data);
        _currentMetrics = data;
        _currentTotalTrades = extractTotalTrades(data);
        checkDrawdownAlert();
        maybeRenderStrategyCharts();
        markUpdated("metrics");
    } catch(e) {
        if (!isAbortError(e)) {
            document.getElementById("metrics-container").innerHTML = '<p class="error">Error loading metrics.</p>';
        }
    }
}

function checkDrawdownAlert() {
    const banner = document.getElementById("drawdown-alert-banner");
    if (!banner || !_currentStrategy || !_currentMetrics) return;
    const limit = _currentStrategy.max_allowed_drawdown;
    if (!limit || limit <= 0) { banner.style.display = "none"; return; }
    const liveDd = _currentMetrics["Drawdown"];
    if (liveDd == null) { banner.style.display = "none"; return; }
    const pctUsed = (liveDd / limit) * 100;
    if (liveDd < limit * 0.8) { banner.style.display = "none"; return; }
    const isCritical = liveDd >= limit;
    banner.className = `drawdown-alert-banner ${isCritical ? "drawdown-alert-critical" : "drawdown-alert-warning"}`;
    document.getElementById("drawdown-alert-title").textContent =
        isCritical ? "CRITICAL: Drawdown limit reached!" : "WARNING: Drawdown approaching limit";
    document.getElementById("drawdown-alert-detail").textContent =
        ` Current: ${liveDd.toFixed(1)}% / Limit: ${limit.toFixed(1)}% (${pctUsed.toFixed(0)}% used)`;
    banner.style.display = "flex";
}

async function loadEquity(signal = null) {
    const requestKey = currentViewKey();
    try {
        const qs = new URLSearchParams({ _: String(Date.now()) });
        if (_sideFilter !== "both") qs.set("side", _sideFilter);
        const res = await fetch(`/api/strategies/${STRATEGY_ID}/equity?${qs.toString()}`, { signal });
        _allEquityPoints = await res.json();
        if (requestKey !== currentViewKey()) return;
        maybeRenderStrategyCharts();
        markUpdated("equity");
    } catch(e) {
        if (!isAbortError(e)) console.error("Equity load error:", e);
    }
}

function setEquityPeriod(period) {
    _equityPeriod = period;
    localStorage.setItem("tm-equity-period", period);
    document.querySelectorAll(".period-tab[data-ep]").forEach(b =>
        b.classList.toggle("active", b.dataset.ep === period));
    maybeRenderStrategyCharts();
}

function setEquityScale(scale) {
    _equityScale = scale;
    localStorage.setItem("tm-equity-scale", scale);
    document.querySelectorAll(".period-tab[data-es]").forEach(b =>
        b.classList.toggle("active", b.dataset.es === scale));
    maybeRenderStrategyCharts();
}

function renderEquityChart(points) {
    if (!document.getElementById("equity-chart")) {
        const wrapper = document.querySelector("#chart-section .chart-wrapper");
        if (wrapper) wrapper.innerHTML = '<canvas id="equity-chart"></canvas>';
    }
    const ctx = document.getElementById("equity-chart").getContext("2d");
    if (points.length === 0) {
        ctx.canvas.parentElement.innerHTML = '<p class="empty-state" style="padding:2rem 0">No equity data yet.</p>';
        return;
    }
    const isPct = _equityScale === "pct";
    const labels = buildEquityChartLabels(points);
    const pctOpts = getStrategyEquityPctOptions();
    const chartValues = buildRebasedEquitySeries(
        points,
        _equityScale,
        (point) => point.equity,
        pctOpts,
    );
    const palette = getProfitPalette(
        typeof _currentMetrics?.Profit === "number" ? _currentMetrics.Profit : null
    );

    if (equityChart) equityChart.destroy();
    equityChart = createEquityLineChart(ctx, {
        labels,
        datasets: [{
            label: isPct ? "Return (%)" : "Equity",
            data: chartValues,
            borderColor: palette.borderColor,
            backgroundColor: palette.backgroundColor,
            fill: true,
            tension: 0.3,
            pointRadius: 0,
            borderWidth: 2,
        }],
        isPct,
        tooltipLabel: isPct
            ? c => ` Return: ${c.parsed.y.toFixed(2)}%`
            : c => ` Equity: ${fmt(c.parsed.y)}`,
        onHover: (e, elements) => {
            if (!underwaterChart) return;
            if (elements.length > 0) {
                const idx = elements[0].index;
                underwaterChart.setActiveElements([{ datasetIndex: 0, index: idx }]);
                underwaterChart.tooltip.setActiveElements([{ datasetIndex: 0, index: idx }], { x: 0, y: 0 });
                underwaterChart.update();
            } else {
                underwaterChart.setActiveElements([]);
                underwaterChart.tooltip.setActiveElements([], { x: 0, y: 0 });
                underwaterChart.update();
            }
        },
    });
    renderUnderwaterChart(points);
}

function renderUnderwaterChart(points) {
    const canvasId = "underwater-chart";
    if (!document.getElementById(canvasId)) {
        const wrapper = document.querySelector("#underwater-section .chart-wrapper");
        if (wrapper) wrapper.innerHTML = `<canvas id="${canvasId}"></canvas>`;
    }
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    if (!points || points.length === 0) {
        canvas.parentElement.innerHTML = '<p class="empty-state" style="padding:1rem 0">No data yet.</p>';
        underwaterChart = destroyChart(underwaterChart);
        return;
    }

    const isPct = _equityScale === "pct";
    const seriesValues = buildRebasedEquitySeries(
        points,
        _equityScale,
        (point) => point.equity ?? point.balance ?? 0,
        getStrategyEquityPctOptions(),
    );

    let peak = -Infinity;
    const ddValues = seriesValues.map(value => {
        if (value > peak) peak = value;
        return parseFloat((value - peak).toFixed(4));
    });

    const labels = buildEquityChartLabels(points);
    const { tickColor, gridColor } = getEquityChartColors();

    const ddLabel    = isPct ? "Drawdown %" : "Drawdown $";
    const ddTickCb   = isPct ? v => `${v.toFixed(1)}%` : v => fmt(v);
    const ddTooltipCb = isPct
        ? c => ` DD: ${c.parsed.y.toFixed(2)}%`
        : c => ` DD: ${fmt(c.parsed.y)}`;

    destroyChart(underwaterChart);
    underwaterChart = new Chart(canvas.getContext("2d"), {
        type: "line",
        data: {
            labels,
            datasets: [{
                label: ddLabel,
                data: ddValues,
                borderColor: CHART_COLORS.underwaterBorder,
                backgroundColor: CHART_COLORS.underwaterFill,
                fill: true,
                tension: 0.2,
                pointRadius: 0,
                borderWidth: 1.5,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            onHover: (e, elements, chart) => {
                if (!equityChart) return;
                if (elements.length > 0) {
                    const idx = elements[0].index;
                    equityChart.setActiveElements([{ datasetIndex: 0, index: idx }]);
                    equityChart.tooltip.setActiveElements([{ datasetIndex: 0, index: idx }], { x: 0, y: 0 });
                    equityChart.update();
                } else {
                    equityChart.setActiveElements([]);
                    equityChart.tooltip.setActiveElements([], { x: 0, y: 0 });
                    equityChart.update();
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: ddTooltipCb } },
                zoom: {
                    zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: "x" },
                    pan:  { enabled: true, mode: "x" },
                },
            },
            scales: {
                x: { ticks: { maxTicksLimit: 12, color: tickColor }, grid: { color: gridColor } },
                y: {
                    ticks: { color: tickColor, callback: ddTickCb },
                    grid: { color: gridColor },
                    max: 0,
                },
            },
        },
    });
}

/* ── Monthly P&L ── */
let _monthlyChart = null;
let _annualChart = null;
let _monthlyRawLabels = [];
let _monthlyValues   = [];
let _monthlyView = localStorage.getItem("tm-monthly-view") || "bar";

async function loadMonthlyPnL(signal = null) {
    const requestKey = currentViewKey();
    try {
        const res = await fetch(`/api/strategies/${STRATEGY_ID}/daily?_=1${sideParam()}`, { signal });
        const rows = await res.json();
        if (requestKey !== currentViewKey()) return;
        const agg = {};
        rows.forEach(r => {
            const key = r.date.slice(0, 7);
            agg[key] = (agg[key] || 0) + r.net_profit;
        });
        _monthlyRawLabels = Object.keys(agg).sort();
        _monthlyValues    = _monthlyRawLabels.map(k => parseFloat(agg[k].toFixed(2)));
        renderMonthlyChart();
        renderAnnualChart();
    } catch(e) { if (!isAbortError(e)) console.error("Monthly P&L error:", e); }
}

function setMonthlyView(v) {
    _monthlyView = v;
    localStorage.setItem("tm-monthly-view", v);
    document.querySelectorAll(".period-tab[data-mp]").forEach(b =>
        b.classList.toggle("active", b.dataset.mp === v));
    renderMonthlyChart();
}

function renderMonthlyChart() {
    if (!_monthlyRawLabels.length) {
        _monthlyChart = destroyChart(_monthlyChart);
        renderChartEmptyState("monthly-pnl-wrapper", "No P&L data for this side.");
        return;
    }
    const canvas = ensureCanvas("monthly-pnl-wrapper", "monthly-pnl-chart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    _monthlyChart = destroyChart(_monthlyChart);

    const { tickColor, gridColor } = getEquityChartColors();

    const labels = _monthlyRawLabels.map(k => {
        const [y, m] = k.split("-");
        return new Date(y, m - 1).toLocaleDateString("en-GB", { month: "short", year: "2-digit" });
    });
    const isBar    = _monthlyView === "bar";
    const bgColors = _monthlyValues.map(profitBgColor);
    const brColors = _monthlyValues.map(profitBorderColor);

    _monthlyChart = new Chart(ctx, {
        type: isBar ? "bar" : "line",
        data: {
            labels,
            datasets: [{
                label: "Net P&L",
                data: _monthlyValues,
                backgroundColor: isBar ? bgColors : CHART_COLORS.mutedBg,
                borderColor:     isBar ? brColors : CHART_COLORS.muted,
                borderWidth: isBar ? 1 : 2,
                borderRadius: isBar ? 4 : 0,
                fill: !isBar,
                tension: 0.3,
                pointRadius: isBar ? 0 : 3,
                pointBackgroundColor: brColors,
                segment: isBar ? undefined : {
                    borderColor: ctx => profitBorderColor(ctx.p1.parsed.y),
                },
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: ctx => ` ${fmt(ctx.parsed.y)}` } },
            },
            scales: {
                x: { ticks: { color: tickColor, maxTicksLimit: 18, font: { size: 11 } }, grid: { display: false } },
                y: {
                    ticks: { color: tickColor, callback: v => fmt(v) },
                    grid:  { color: gridColor },
                },
            },
        },
    });
}

function renderAnnualChart() {
    if (!_monthlyRawLabels.length) {
        _annualChart = destroyChart(_annualChart);
        renderChartEmptyState("annual-pnl-wrapper", "No P&L data for this side.");
        return;
    }
    const canvas = ensureCanvas("annual-pnl-wrapper", "annual-pnl-chart");
    if (!canvas) return;
    _annualChart = destroyChart(_annualChart);

    const { tickColor, gridColor } = getEquityChartColors();

    const yearAgg = {};
    _monthlyRawLabels.forEach((k, i) => {
        const year = k.slice(0, 4);
        yearAgg[year] = (yearAgg[year] || 0) + _monthlyValues[i];
    });
    const years = Object.keys(yearAgg).sort();
    const values = years.map(y => parseFloat(yearAgg[y].toFixed(2)));

    const bgColors = values.map(profitBgColor);
    const brColors = values.map(profitBorderColor);

    _annualChart = new Chart(canvas.getContext("2d"), {
        type: "bar",
        data: {
            labels: years,
            datasets: [{
                label: "Annual Net P&L",
                data: values,
                backgroundColor: bgColors,
                borderColor: brColors,
                borderWidth: 1,
                borderRadius: 4,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: ctx => ` ${fmt(ctx.parsed.y)}` } },
            },
            scales: {
                x: { ticks: { color: tickColor }, grid: { display: false } },
                y: { ticks: { color: tickColor, callback: v => fmt(v) }, grid: { color: gridColor } },
            },
        },
    });
}

/* ── Trade Distribution ── */
async function loadDistribution(signal = null) {
    const requestKey = currentViewKey();
    try {
        const res = await fetch(`/api/strategies/${STRATEGY_ID}/trade-stats?_=1${sideParam()}`, { signal });
        const data = await res.json();
        if (requestKey !== currentViewKey()) return;
        renderDistChart("dist-hour-chart", "_distHourChart",
            data.by_hour.map(r => r.hour + ":00"),
            data.by_hour.map(r => r.count),
            data.by_hour.map(r => r.net_profit),
            (v) => v < 0 ? CHART_COLORS.redSoft : CHART_COLORS.greenSoft
        );
        renderDistChart("dist-dow-chart", "_distDowChart",
            data.by_dow.map(r => r.label),
            data.by_dow.map(r => r.count),
            data.by_dow.map(r => r.net_profit),
            (v) => v < 0 ? CHART_COLORS.redSoft : CHART_COLORS.greenSoft
        );
    } catch(e) { if (!isAbortError(e)) console.error("Distribution load error:", e); }
}

function renderDistChart(canvasId, chartVar, labels, counts, profits) {
    const wrapperId = canvasId === "dist-hour-chart" ? "dist-hour-wrapper" : "dist-dow-wrapper";
    const hasData = Array.isArray(counts) && counts.some(c => c > 0);

    if (!labels.length || !hasData) {
        window[chartVar] = destroyChart(window[chartVar]);
        const orphan = document.getElementById(canvasId);
        if (orphan) { const inst = Chart.getChart(orphan); if (inst) inst.destroy(); }
        renderChartEmptyState(wrapperId, "No trade distribution for this side.");
        return;
    }

    const canvas = ensureCanvas(wrapperId, canvasId);
    if (!canvas) return;

    window[chartVar] = destroyChart(window[chartVar]);
    const orphan = Chart.getChart(canvas);
    if (orphan) orphan.destroy();

    const { tickColor, gridColor } = getEquityChartColors();

    const bgColors = profits.map(profitBgColor);
    const brColors = profits.map(profitBorderColor);

    window[chartVar] = new Chart(canvas, {
        type: "bar",
        data: {
            labels,
            datasets: [{
                label: "Net P&L",
                data: profits,
                backgroundColor: bgColors,
                borderColor: brColors,
                borderWidth: 1,
                borderRadius: 3,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: ctx => ` ${fmt(ctx.parsed.y)}` } },
            },
            scales: {
                x: { ticks: { color: tickColor, font: { size: 10 } }, grid: { display: false } },
                y: {
                    ticks: { color: tickColor, callback: v => fmt(v) },
                    grid: { color: gridColor },
                },
            },
        },
    });
}

/* ── Deals ── */
function exportDeals() {
    if (_pageMode === "backtest") {
        if (!_selectedBtId) { showToast("Select a backtest run first.", "", "error"); return; }
        window.location.href = `/api/backtests/${_selectedBtId}/deals/export`;
    } else {
        window.location.href = `/api/strategies/${STRATEGY_ID}/deals/export`;
    }
}

function filterDeals() {
    clearTimeout(_dealsSearchTimer);
    _dealsSearchTimer = setTimeout(() => loadDeals(1), 350);
}

async function loadDeals(page = 1, signal = null) {
    const requestKey = currentViewKey();
    const q = (document.getElementById("deals-search")?.value || "").trim();
    const ps = parseInt(document.getElementById("deals-page-size")?.value || "25");
    try {
        let url = `/api/strategies/${STRATEGY_ID}/deals?page=${page}&page_size=${ps}${sideParam()}`;
        if (q) url += `&q=${encodeURIComponent(q)}`;
        const res = await fetch(url, { signal });
        if (requestKey !== currentViewKey()) return;
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            document.getElementById("deals-container").innerHTML =
                `<p class="error">${err.detail || "Error loading deals (status " + res.status + ")"}</p>`;
            return;
        }
        const data = await res.json();
        renderDeals(data);
    } catch(e) {
        if (!isAbortError(e)) {
            document.getElementById("deals-container").innerHTML = '<p class="error">Error loading deals.</p>';
        }
    }
}

function dealsSortBy(col) {
    ({ col: _dealsSortCol, asc: _dealsSortAsc } = toggleSort(_dealsSortCol, _dealsSortAsc, col, false));
    loadDeals(1);
}

function renderDeals(data) {
    document.getElementById("deals-count").textContent = `${data.total} deals`;
    const container = document.getElementById("deals-container");
    if (!data.items || data.items.length === 0) {
        container.innerHTML = '<p class="empty-state">No deals found.</p>';
        return;
    }

    const items = [...data.items];
    items.sort((a, b) => {
        let av = a[_dealsSortCol], bv = b[_dealsSortCol];
        if (_dealsSortCol === "net") {
            av = (a.profit || 0) + (a.commission || 0) + (a.swap || 0);
            bv = (b.profit || 0) + (b.commission || 0) + (b.swap || 0);
        }
        if (av == null) av = "";
        if (bv == null) bv = "";
        if (typeof av === "string") av = av.toLowerCase();
        if (typeof bv === "string") bv = bv.toLowerCase();
        if (av < bv) return _dealsSortAsc ? -1 : 1;
        if (av > bv) return _dealsSortAsc ? 1 : -1;
        return 0;
    });

    const rows = items.map(d => {
        const profit = d.profit || 0;
        const net = profit + (d.commission || 0) + (d.swap || 0);
        const profitCls = profit > 0 ? "profit-positive" : profit < 0 ? "profit-negative" : "";
        const netCls = net > 0 ? "profit-positive" : net < 0 ? "profit-negative" : "";
        const date = formatMt5ServerTimestamp(d.timestamp);
        return `<tr>
            <td>${date}</td>
            <td class="mono">${d.ticket}</td>
            <td>${d.symbol || "—"}</td>
            <td class="type-${d.type}">${d.type.toUpperCase()}</td>
            <td>${fmt(d.volume, 2)}</td>
            <td>${fmt(d.price, 2)}</td>
            <td class="${profitCls}">${fmt(profit)}</td>
            <td class="text-muted">${fmt(d.commission || 0)}</td>
            <td class="text-muted">${fmt(d.swap || 0)}</td>
            <td class="${netCls}">${fmt(net)}</td>
        </tr>`;
    }).join("");

    function thD(label, col) {
        const arrow = _dealsSortCol === col ? (_dealsSortAsc ? " ▲" : " ▼") : "";
        return `<th class="sortable" onclick="dealsSortBy('${col}')">${label}${arrow}</th>`;
    }

    container.innerHTML = `
        <div class="table-responsive"><table class="data-table">
            <thead>
                <tr>
                    ${thD("Date","timestamp")}${thD("Ticket","ticket")}${thD("Symbol","symbol")}${thD("Type","type")}
                    ${thD("Volume","volume")}${thD("Price","price")}${thD("Profit","profit")}
                    <th>Commission</th><th>Swap</th>${thD("Net","net")}
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table></div>`;

    const totalPages = Math.ceil(data.total / data.page_size);
    renderPagination("pagination", data.page, totalPages, p => loadDeals(p));
}

window.addEventListener("ws-event", function(e) {
    const { topic, data } = e.detail;
    const stratId = data && (data.magic ? String(data.magic) : data.strategy_id);
    if (stratId !== STRATEGY_ID) return;
    if (topic === "DEAL" && _pageMode !== "backtest") {
        refreshCurrentView();
    } else if (topic === "EQUITY" && _pageMode !== "backtest") {
        const signal = beginViewRequest();
        loadEquity(signal);
        loadMetrics(signal);
    } else if (topic === "BACKTEST_END") {
        loadBacktests();
    }
});

/* ── Backtests ── */
async function loadBacktests() {
    try {
        const res = await fetch(`/api/strategies/${STRATEGY_ID}/backtests`);
        _backtests = await res.json();
        updateTabAvailability();
        renderBacktestsList();
    } catch(e) { console.error("Backtests load error:", e); }
}

function renderBacktestsList() {
    const container = document.getElementById("bt-run-list");
    document.getElementById("bt-runs-count").textContent = `${_backtests.length} runs`;

    if (!_backtests.length) {
        container.innerHTML = '<p class="empty-state">No backtest runs yet. Send BACKTEST_START from MT5 to begin.</p>';
        return;
    }

    if (_pageMode === "backtest" && !_selectedBtId && _backtests.length > 0) {
        _selectedBtId = _backtests[0].id;
        refreshCurrentView();
    }

    const STATUS_CLS = { complete: "badge-active", running: "badge-live", pending: "badge-neutral", failed: "badge-inactive" };
    const rows = _backtests.map(b => {
        const net = b.net_profit;
        const netCls = net == null ? "" : net > 0 ? "profit-positive" : net < 0 ? "profit-negative" : "";
        const statusCls = STATUS_CLS[b.status] || "badge-neutral";
        const period = b.start_date && b.end_date
            ? `${new Date(b.start_date).toLocaleDateString("en-GB")} – ${new Date(b.end_date).toLocaleDateString("en-GB")}`
            : "—";
        const selected = _selectedBtId === b.id ? "selected-row" : "";
        return `<tr class="clickable-row ${selected}" onclick="selectBtRun(${b.id})">
            <td>${b.name || `Run #${b.id}`}</td>
            <td>${b.symbol || "—"}</td>
            <td>${b.timeframe || "—"}</td>
            <td class="text-muted" style="font-size:0.8rem">${period}</td>
            <td><span class="badge ${statusCls}">${b.status}</span></td>
            <td class="${netCls}">${net != null ? fmt(net) : "—"}</td>
            <td><button class="btn-delete-row" title="Delete" onclick="event.stopPropagation();deleteBacktest(${b.id})">✕</button></td>
        </tr>`;
    }).join("");

    container.innerHTML = `
        <div class="table-responsive"><table class="data-table">
            <thead><tr>
                <th>Name</th><th>Symbol</th><th>TF</th><th>Period</th>
                <th>Status</th><th>Profit</th><th></th>
            </tr></thead>
            <tbody>${rows}</tbody>
        </table></div>`;
}

async function loadBtMetrics(btId) {
    return loadBtMetricsInMain(btId);
}

async function loadBtDeals(btId, page = 1) {
    return loadBtDealsInMain(btId, page);
}

async function deleteBacktest(btId) {
    const confirmed = await showConfirmModal(
        "Delete Backtest",
        "Delete this backtest and all its data?",
        { confirmLabel: "Delete", confirmClass: "btn-danger" }
    );
    if (!confirmed) return;
    try {
        const res = await fetch(`/api/backtests/${btId}`, { method: "DELETE" });
        if (!res.ok) throw new Error(await res.text());
        if (_selectedBtId === btId) {
            _selectedBtId = null;
            document.getElementById("metrics-container").innerHTML =
                '<div class="skel skel-metric"></div><div class="skel skel-metric"></div>' +
                '<div class="skel skel-metric"></div><div class="skel skel-metric"></div>';
            document.getElementById("deals-container").innerHTML = "";
            document.getElementById("pagination").innerHTML = "";
            document.getElementById("deals-count").textContent = "";
        }
        await loadBacktests();
    } catch(e) { showToast("Error", "Failed to delete: " + e.message, "error"); }
}

window.addEventListener("tm-theme-change", function() {
    // Redraw equity/drawdown charts using existing data
    if (_allEquityPoints && _allEquityPoints.length) {
        maybeRenderStrategyCharts();
    }

    // Monthly P&L can redraw from memory
    if (_monthlyRawLabels && _monthlyRawLabels.length) {
        renderMonthlyChart();
        renderAnnualChart();
    }

    // Distribution charts don't cache data, so refetch ONLY if visible
    if (_visibleSections.has("distribution-section")) {
        if (_pageMode === "backtest" && _selectedBtId) loadBtDistribution(_selectedBtId);
        else if (_pageMode !== "backtest") loadDistribution();
    }
});

// ── Restore persisted UI preferences ──────────────────────────────────────
document.querySelectorAll(".period-tab[data-ep]").forEach(b =>
    b.classList.toggle("active", b.dataset.ep === _equityPeriod));
document.querySelectorAll(".period-tab[data-es]").forEach(b =>
    b.classList.toggle("active", b.dataset.es === _equityScale));
document.querySelectorAll(".period-tab[data-mp]").forEach(b =>
    b.classList.toggle("active", b.dataset.mp === _monthlyView));
const _savedPs = localStorage.getItem("tm-deals-page-size");
if (_savedPs) {
    const _psSel = document.getElementById("deals-page-size");
    if (_psSel) _psSel.value = _savedPs;
}

loadInfo();
loadBacktests();
if (typeof requestIdleCallback === "function") {
    requestIdleCallback(() => loadStrategyNavigation(), { timeout: 2000 });
} else {
    setTimeout(loadStrategyNavigation, 500);
}
initLazyLoading();
