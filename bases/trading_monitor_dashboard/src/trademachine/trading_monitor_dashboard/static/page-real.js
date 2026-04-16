let realPnlChart = null;
let _allRealPnlPoints = [];
let _realPnlPeriod = localStorage.getItem("tm-real-pnl-period") || "all";
let _realPnlDataKey = "";
let _realPnlRenderedKey = "";
let _recentDeals = [];
let _recentDealsSortCol = "timestamp";
let _recentDealsSortAsc = false;
let _recentDealsPage = 1;

function parseRealPnlDate(value) {
    if (typeof value !== "string") return new Date(value);
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    if (!match) return new Date(value);
    const [, year, month, day] = match;
    return new Date(Number(year), Number(month) - 1, Number(day));
}

async function loadReal() {
    let data;
    try {
        data = await fetchJson("/api/real");
    } catch(e) {
        document.getElementById("real-status-badge").textContent = "Error";
        document.getElementById("real-status-badge").className = "badge badge-inactive";
        return;
    }

    const isDemoMode = (data.mode || "real") === "demo";
    document.getElementById("real-page-title").textContent = "Live Monitor";

    if (!data.strategies || data.strategies.length === 0) {
        document.getElementById("real-empty").style.display = "block";
        return;
    }

    const totals = data.totals;
    const dayCls = totals.day_pnl >= 0 ? "profit-positive" : "profit-negative";
    const npCls = totals.net_profit >= 0 ? "profit-positive" : "profit-negative";
    const flCls = totals.floating_pnl >= 0 ? "profit-positive" : "profit-negative";

    document.getElementById("sum-strategies").textContent = data.strategies.length;
    document.getElementById("sum-open-trades").textContent = totals.open_trades_count != null ? totals.open_trades_count : "—";
    document.getElementById("sum-pending-orders").textContent = totals.pending_orders_count != null ? totals.pending_orders_count : "—";
    document.getElementById("sum-day-pnl").textContent = fmt(totals.day_pnl);
    document.getElementById("sum-day-pnl").className = "summary-num " + dayCls;
    document.getElementById("sum-net-profit").textContent = fmt(totals.net_profit);
    document.getElementById("sum-net-profit").className = "summary-num " + npCls;
    document.getElementById("sum-floating").textContent = fmt(totals.floating_pnl);
    document.getElementById("sum-floating").className = "summary-num " + flCls;
    document.getElementById("real-summary").style.display = "";
    document.getElementById("real-status-badge").textContent = isDemoMode ? "Demo" : "Real";
    document.getElementById("real-status-badge").className = `badge ${isDemoMode ? "badge-demo" : "badge-real"}`;

}

function filterRealPnlPoints(points, period) {
    if (period === "all" || !points.length) return points;
    const cutoff = new Date();
    if (period === "1W") {
        cutoff.setDate(cutoff.getDate() - 7);
    } else if (period === "1M") {
        cutoff.setMonth(cutoff.getMonth() - 1);
    } else if (period === "1Y") {
        cutoff.setFullYear(cutoff.getFullYear() - 1);
    }
    cutoff.setHours(0, 0, 0, 0);
    return points.filter(point => parseRealPnlDate(point.date) >= cutoff);
}

function syncRealPnlPeriodButtons() {
    document.querySelectorAll(".period-tab[data-rp]").forEach(btn =>
        btn.classList.toggle("active", btn.dataset.rp === _realPnlPeriod)
    );
}

function renderRealPnlIfNeeded(force = false) {
    const renderKey = `${_realPnlPeriod}::${_realPnlDataKey}`;
    if (!force && renderKey === _realPnlRenderedKey) {
        return;
    }
    renderRealPnlChart(filterRealPnlPoints(_allRealPnlPoints, _realPnlPeriod));
    _realPnlRenderedKey = renderKey;
}

function setRealPnlPeriod(period) {
    _realPnlPeriod = period;
    localStorage.setItem("tm-real-pnl-period", period);
    syncRealPnlPeriodButtons();
    renderRealPnlIfNeeded(true);
}

function renderRealPnlChart(points) {
    const wrapper = document.querySelector("#pnl-card .chart-box");
    if (!document.getElementById("real-pnl-chart")) {
        wrapper.innerHTML = '<canvas id="real-pnl-chart"></canvas>';
    }
    const canvas = document.getElementById("real-pnl-chart");
    if (!points.length) {
        wrapper.innerHTML = '<p class="empty-state" style="padding:2rem 0">No P&L data yet.</p>';
        document.getElementById("pnl-badge").textContent = "0 points";
        document.getElementById("pnl-card").style.display = "";
        return;
    }

    const ctx = canvas.getContext("2d");
    const { tickColor, gridColor } = getEquityChartColors();
    const labels = points.map(point => {
        const d = parseRealPnlDate(point.date);
        return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });
    });
    const values = points.map(point => point.net_profit);
    const colors = values.map(v => v >= 0 ? CHART_COLORS.greenSoft : CHART_COLORS.redSoft);

    destroyChart(realPnlChart);
    realPnlChart = new Chart(ctx, {
        type: "bar",
        data: {
            labels,
            datasets: [{
                label: "Daily P&L",
                data: values,
                backgroundColor: colors,
                borderColor: colors,
                borderWidth: 1,
                borderRadius: 4,
                barPercentage: 0.9,
                categoryPercentage: 0.9,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: ctx => ` P&L: ${fmt(ctx.parsed.y)}` } },
            },
            scales: {
                x: {
                    ticks: { maxTicksLimit: 12, color: tickColor, font: { size: 11 } },
                    grid: { color: gridColor },
                },
                y: {
                    ticks: { color: tickColor, font: { size: 11 }, callback: v => fmt(v) },
                    grid: { color: gridColor },
                },
            },
        },
    });

    document.getElementById("pnl-badge").textContent = `${labels.length} points`;
    document.getElementById("pnl-card").style.display = "";
}

async function loadRealDailyPnl() {
    try {
        const points = await fetchJson("/api/real/daily");
        const nextKey = JSON.stringify(points);
        if (nextKey === _realPnlDataKey) {
            return;
        }
        _allRealPnlPoints = points;
        _realPnlDataKey = nextKey;
        renderRealPnlIfNeeded(true);
    } catch (e) {
        const wrapper = document.querySelector("#pnl-card .chart-box");
        if (wrapper) {
            wrapper.innerHTML = '<p class="empty-state" style="padding:2rem 0">Failed to load P&L data.</p>';
        }
        _realPnlRenderedKey = "";
        document.getElementById("pnl-card").style.display = "";
    }
}

async function killAll() {
    const confirmed = await showConfirmModal(
        "Kill All Strategies",
        "<strong>CRITICAL:</strong> This will close <em>ALL</em> active positions on all connected accounts and stop all running strategies.<br><br>Are you absolutely sure?",
        { confirmLabel: "Kill All", confirmClass: "btn-danger", cancelLabel: "Abort" }
    );
    if (!confirmed) return;
    try {
        const result = await fetchJson("/api/strategies/kill-all", { method: "POST" });
        showToast("Kill All", result.message || "Kill-all command sent.", "info");
        loadReal();
    } catch (e) {
        showToast("Error", "Request failed: " + e.message, "error");
    }
}

async function loadRecentDeals() {
    const container = document.getElementById("recent-deals-body");
    const badge = document.getElementById("badge-recent-deals");
    try {
        const deals = await fetchJson("/api/real/recent-deals?limit=250");
        _recentDeals = deals;
        badge.textContent = String(deals.length);
        renderRecentDealsTable();
    } catch (e) {
        _recentDeals = [];
        container.innerHTML = `<tr><td colspan="8" class="empty-state" style="padding: 2rem;">Failed to load recent deals.</td></tr>`;
        badge.textContent = "—";
        document.getElementById("recent-deals-pagination").innerHTML = "";
    }
}

function recentDealsSortBy(col) {
    ({ col: _recentDealsSortCol, asc: _recentDealsSortAsc } = toggleSort(_recentDealsSortCol, _recentDealsSortAsc, col, col !== "timestamp"));
    _recentDealsPage = 1;
    renderRecentDealsTable();
}

function recentDealsGoPage(page) {
    _recentDealsPage = page;
    renderRecentDealsTable();
}

function renderRecentDealsTable() {
    const container = document.getElementById("recent-deals-body");
    const pageSize = parseInt(document.getElementById("recent-deals-page-size")?.value || "25", 10);

    // Update sort arrows in static thead
    ["timestamp", "strategy_name", "symbol", "type", "profit", "commission", "swap", "net_profit"].forEach(col => {
        const el = document.getElementById(`recent-deals-arrow-${col}`);
        if (el) el.textContent = _recentDealsSortCol === col ? (_recentDealsSortAsc ? " ↑" : " ↓") : "";
    });

    if (!_recentDeals.length) {
        container.innerHTML = `<tr><td colspan="8" class="empty-state" style="padding: 2rem;">No recent deals found.</td></tr>`;
        renderPagination("recent-deals-pagination", 1, 1, () => {});
        return;
    }

    // Use sortList with a type-aware valueFn
    const numericCols = new Set(["profit", "commission", "swap", "net_profit"]);
    const sorted = sortList(_recentDeals, _recentDealsSortCol, _recentDealsSortAsc, d => {
        const raw = d[_recentDealsSortCol];
        if (_recentDealsSortCol === "timestamp") return raw ? new Date(raw).getTime() : 0;
        if (numericCols.has(_recentDealsSortCol)) return Number(raw ?? 0);
        return String(raw || "").toLowerCase();
    });

    const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
    if (_recentDealsPage > totalPages) _recentDealsPage = 1;
    const pageDeals = sorted.slice((_recentDealsPage - 1) * pageSize, _recentDealsPage * pageSize);

    container.innerHTML = pageDeals.map(d => {
        const ts = formatMt5ServerTimestamp(d.timestamp);
        const profit = d.profit ?? 0;
        const commission = d.commission ?? 0;
        const swap = d.swap ?? 0;
        const net = d.net_profit ?? 0;
        const profitCls = profit > 0 ? "profit-positive" : profit < 0 ? "profit-negative" : "";
        const commissionCls = commission > 0 ? "profit-positive" : commission < 0 ? "profit-negative" : "";
        const swapCls = swap > 0 ? "profit-positive" : swap < 0 ? "profit-negative" : "";
        const cls = net > 0 ? "profit-positive" : net < 0 ? "profit-negative" : "";
        return `
            <tr>
                <td style="font-variant-numeric:tabular-nums;white-space:nowrap">${ts}</td>
                <td><a href="/strategy/${d.strategy_id}" style="color:var(--accent)">${d.strategy_name || d.strategy_id || "—"}</a></td>
                <td><span class="badge badge-neutral">${d.symbol || "—"}</span></td>
                <td><span class="badge badge-neutral">${d.type || "—"}</span></td>
                <td class="${profitCls}" style="font-variant-numeric:tabular-nums">${fmt(profit)}</td>
                <td class="${commissionCls}" style="font-variant-numeric:tabular-nums">${fmt(commission)}</td>
                <td class="${swapCls}" style="font-variant-numeric:tabular-nums">${fmt(swap)}</td>
                <td class="${cls}" style="font-variant-numeric:tabular-nums;font-weight:600">${fmt(net)}</td>
            </tr>
        `;
    }).join("");

    renderPagination("recent-deals-pagination", _recentDealsPage, totalPages,
        p => { _recentDealsPage = p; renderRecentDealsTable(); });
}

syncRealPnlPeriodButtons();
loadReal();
loadRealDailyPnl();
loadRecentDeals();

// ── Last-updated countdown bar ────────────────────────────────────────────
const REFRESH_INTERVAL_MS = 5000;
let _lastRefresh = Date.now();
let _nextRefresh = _lastRefresh + REFRESH_INTERVAL_MS;

function updateLastUpdatedBar() {
    const now = Date.now();
    const elapsed = now - _lastRefresh;
    const remaining = Math.max(0, _nextRefresh - now);
    const progress = Math.min(1, elapsed / REFRESH_INTERVAL_MS);
    const secs = Math.ceil(remaining / 1000);
    const fill = document.getElementById("last-updated-fill");
    const text = document.getElementById("last-updated-text");
    if (fill) fill.style.width = (progress * 100) + "%";
    if (text) text.textContent = remaining <= 0 ? "Refreshing…" : `Refreshes in ${secs}s`;
}

setInterval(() => {
    _lastRefresh = Date.now();
    _nextRefresh = _lastRefresh + REFRESH_INTERVAL_MS;
    loadReal();
    loadRealDailyPnl();
    loadRecentDeals();
}, REFRESH_INTERVAL_MS);

setInterval(updateLastUpdatedBar, 250);
