// ── Theme ────────────────────────────────────────────────────────────────────
function _applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("tm-theme", theme);

    const darkIcon = document.getElementById("theme-icon-dark");
    const lightIcon = document.getElementById("theme-icon-light");
    if (darkIcon && lightIcon) {
        darkIcon.style.display = theme === "dark" ? "block" : "none";
        lightIcon.style.display = theme === "dark" ? "none" : "block";
    }

    // Update Chart.js global defaults
    if (typeof Chart !== "undefined") {
        const isDark = theme === "dark";
        Chart.defaults.color      = isDark ? "#94a3b8" : "#475569";
        Chart.defaults.borderColor = isDark ? "#334155" : "#cbd5e1";
    }

    window.dispatchEvent(new CustomEvent("tm-theme-change", { detail: { theme } }));
}

function toggleTheme() {
    const current = document.documentElement.getAttribute("data-theme") || "dark";
    _applyTheme(current === "dark" ? "light" : "dark");
}

// Init theme and Chart.js defaults on every page load
document.addEventListener("DOMContentLoaded", function() {
    const saved = localStorage.getItem("tm-theme") || "dark";
    _applyTheme(saved);
    setupMobileNav();
    setupNavDropdown({
        wrapperId: "strategies-nav",
        toggleId: "strategies-toggle",
        itemsId: "strategies-menu-items",
        stateId: "strategies-menu-state",
        loader: loadStrategiesDropdown,
    });
    setupNavDropdown({
        wrapperId: "portfolios-nav",
        toggleId: "portfolios-toggle",
        itemsId: "portfolios-menu-items",
        stateId: "portfolios-menu-state",
        loader: loadPortfoliosDropdown,
    });
    setupNavDropdown({
        wrapperId: "accounts-nav",
        toggleId: "accounts-toggle",
        itemsId: "accounts-menu-items",
        stateId: "accounts-menu-state",
        loader: loadAccountsDropdown,
    });
    setupNavDropdown({
        wrapperId: "symbols-nav",
        toggleId: "symbols-toggle",
        itemsId: "symbols-menu-items",
        stateId: "symbols-menu-state",
        loader: loadSymbolsDropdown,
    });
});

// ── Time & Cache utilities ──────────────────────────────────────────────────
async function fetchJsonCached(url, ttlMs = 60000) {
    const cacheKey = `tm_cache_${url}`;
    const cached = sessionStorage.getItem(cacheKey);
    if (cached) {
        try {
            const parsed = JSON.parse(cached);
            if (Date.now() - parsed.timestamp < ttlMs) {
                return parsed.data;
            }
        } catch (e) { /* ignore parse error */ }
    }
    const data = await fetchJson(url);
    sessionStorage.setItem(cacheKey, JSON.stringify({ timestamp: Date.now(), data }));
    return data;
}

function timeAgo(ts) {
    const s = Math.floor((Date.now() - ts) / 1000);
    if (s < 10)   return "just now";
    if (s < 60)   return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    return `${Math.floor(s / 3600)}h ago`;
}

const _updatedAt = {};
function markUpdated(key) {
    _updatedAt[key] = Date.now();
    _flushUpdatedAt();
}
function _flushUpdatedAt() {
    Object.entries(_updatedAt).forEach(([key, ts]) => {
        const el = document.getElementById(`updated-${key}`);
        if (el) el.textContent = `· ${timeAgo(ts)}`;
    });
}
setInterval(_flushUpdatedAt, 15000);

function formatMt5ServerTimestamp(value, locale = "en-GB") {
    if (!value) return "—";
    if (typeof value !== "string") {
        const parsedDate = new Date(value);
        return Number.isNaN(parsedDate.getTime()) ? "—" : parsedDate.toLocaleString(locale, { hour12: false });
    }

    const match = value.match(
        /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/
    );
    if (!match) {
        const parsedDate = new Date(value);
        return Number.isNaN(parsedDate.getTime()) ? value : parsedDate.toLocaleString(locale, { hour12: false });
    }

    const [, year, month, day, hour, minute, second = "00"] = match;
    return `${day}/${month}/${year}, ${hour}:${minute}:${second}`;
}

function formatDateTime(value) {
    if (!value) return "—";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString("en-GB", { hour12: false });
}

// HTML-escape user-provided text before interpolating into innerHTML
function esc(str) {
    if (str == null) return "";
    const d = document.createElement("div");
    d.textContent = String(str);
    return d.innerHTML;
}

// Number formatter
function fmt(value, decimals = 2) {
    if (value === null || value === undefined) return "—";
    if (typeof value !== "number") return value;
    return value.toLocaleString("en-US", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });
}

const DASHBOARD_ADVANCED_METRIC_KEYS = [
    "risk-reward ratio",
    "sharpe ratio",
    "sortino ratio",
    "calmar ratio",
    "var 95% (daily)",
    "cvar 95% (daily)",
    "consecutive wins",
    "consecutive losses",
    "long trades",
    "long trades (%)",
    "short trades",
    "short trades (%)",
    "z-score",
];

function renderMetricsGrid(container, metrics, options = {}) {
    const advancedKeys = new Set(
        (options.advancedKeys || DASHBOARD_ADVANCED_METRIC_KEYS).map((key) =>
            String(key).toLowerCase()
        )
    );
    const hiddenKeys = new Set(
        (options.hiddenKeys || []).map((key) => String(key).toLowerCase())
    );
    const integerKeys = new Set(
        (options.integerKeys || []).map((key) => String(key).toLowerCase())
    );
    const negateKeys = new Set(
        (options.negateKeys || []).map((key) => String(key).toLowerCase())
    );
    const thresholdPositiveKeys = {
        "profit factor": 1,
        ...(options.thresholdPositiveKeys || {}),
    };

    // Filter metrics first
    const filteredMetrics = Object.entries(metrics).filter(([key]) => {
        const keyLower = key.toLowerCase();
        return !advancedKeys.has(keyLower) && !hiddenKeys.has(keyLower);
    });

    // Define preferred order for main metrics
    // "Avg Profit" is placed penultimate before "Ret/DD" and "Win Rate (%)" might follow,
    // but the user said "penúltima posição da aba Performance Metrics".
    // Usually Performance Metrics has: Total Trades, Profit, Return (%), Profit Factor, Drawdown, Win Rate (%) ...
    // Let's see the keys in _ORDERED_KEYS from calculator.py:
    // Total Trades, Profit, Avg Profit, Return (%), Profit Factor, Ret/DD, Win Rate (%), Drawdown...
    // In the dashboard, we want to ensure Avg Profit is there and in a good spot.

    const preferredOrder = [
        "total trades",
        "profit",
        "return (%)",
        "profit factor",
        "drawdown",
        "avg profit",
        "win rate (%)"
    ];

    const sortedMetrics = filteredMetrics.sort((a, b) => {
        const idxA = preferredOrder.indexOf(a[0].toLowerCase());
        const idxB = preferredOrder.indexOf(b[0].toLowerCase());
        if (idxA !== -1 && idxB !== -1) return idxA - idxB;
        if (idxA !== -1) return -1;
        if (idxB !== -1) return 1;
        return a[0].localeCompare(b[0]);
    });

    container.innerHTML = sortedMetrics
        .map(([key, value]) => {
            const keyLower = key.toLowerCase();
            const shouldNegate = negateKeys.has(keyLower);
            const displayValue =
                shouldNegate && typeof value === "number" && value !== null
                    ? -Math.abs(value)
                    : value;

            let formattedValue = "—";
            if (displayValue !== null && displayValue !== undefined) {
                if (typeof displayValue === "number") {
                    if (integerKeys.has(keyLower)) {
                        formattedValue = displayValue.toFixed(0);
                    } else if (keyLower === "cumulative return (%)" || keyLower === "return (%)") {
                        formattedValue = `${fmt(displayValue)}%`;
                    } else if (keyLower === "win rate (%)") {
                        formattedValue = `${fmt(displayValue)}%`;
                    } else {
                        formattedValue = fmt(displayValue);
                    }
                } else {
                    formattedValue = displayValue;
                }
            }

            let valueClass = "metric-value";
            if (!integerKeys.has(keyLower) && typeof value === "number" && value !== null) {
                if (shouldNegate) {
                    valueClass += " profit-negative";
                } else if (Object.hasOwn(thresholdPositiveKeys, keyLower)) {
                    valueClass += value >= thresholdPositiveKeys[keyLower]
                        ? " profit-positive"
                        : " profit-negative";
                } else if (value > 0) {
                    valueClass += " profit-positive";
                } else if (value < 0) {
                    valueClass += " profit-negative";
                }
            }

            return `<div class="metric-item">
                <span class="metric-label">${key}</span>
                <span class="${valueClass}">${formattedValue}</span>
            </div>`;
        })
        .join("");
}

function filterEquityPointsByPeriod(points, period) {
    if (period === "all" || !points.length) return points;
    const months = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12 }[period] || 0;
    const cutoff = new Date();
    cutoff.setMonth(cutoff.getMonth() - months);
    return points.filter((point) => new Date(point.timestamp) >= cutoff);
}

function buildEquityChartLabels(points) {
    return points.map((point) => {
        const date = new Date(point.timestamp);
        return date.toLocaleDateString("en-GB", {
            day: "2-digit",
            month: "short",
            year: "2-digit",
        });
    });
}

function buildRebasedEquitySeries(points, scale, valueGetter = (point) => point.equity, options = {}) {
    const { pctBaseline, pctDenominator } = options;
    const firstValue = Number(valueGetter(points[0])) || 1;
    const hasExplicitPct =
        Number.isFinite(Number(pctDenominator)) && Number(pctDenominator) > 0;
    return points.map((point) => {
        const value = Number(valueGetter(point)) || 0;
        if (scale === "pct") {
            if (hasExplicitPct) {
                const base = Number.isFinite(Number(pctBaseline))
                    ? Number(pctBaseline)
                    : 0;
                return parseFloat(
                    (((value - base) / Number(pctDenominator)) * 100).toFixed(4)
                );
            }
            const absBaseline = Math.abs(firstValue) || 1;
            return parseFloat((((value - firstValue) / absBaseline) * 100).toFixed(4));
        }
        return parseFloat(value.toFixed(4));
    });
}

// ── Chart color palette (single source of truth) ────────────────────────────
const CHART_COLORS = {
    green:      "#10b981",
    red:        "#ef4444",
    greenBg:    "rgba(16,185,129,0.72)",
    redBg:      "rgba(239,68,68,0.72)",
    greenFill:  "rgba(16,185,129,0.06)",
    redFill:    "rgba(239,68,68,0.10)",
    greenSoft:  "rgba(16,185,129,0.75)",
    redSoft:    "rgba(239,68,68,0.75)",
    underwaterBorder: "#ef4444",
    underwaterFill:   "rgba(239,68,68,0.18)",
    muted:      "#64748b",
    mutedBg:    "rgba(100,116,139,0.08)",
};

function profitBgColor(v) { return v >= 0 ? CHART_COLORS.greenBg : CHART_COLORS.redBg; }
function profitBorderColor(v) { return v >= 0 ? CHART_COLORS.green : CHART_COLORS.red; }

/**
 * Safely destroy a Chart.js instance and return null.
 * Usage: myChart = destroyChart(myChart);
 */
function destroyChart(chart) {
    if (chart) chart.destroy();
    return null;
}

function getEquityChartColors() {
    const isDark = document.documentElement.getAttribute("data-theme") !== "light";
    return {
        tickColor: isDark ? "#64748b" : "#94a3b8",
        gridColor: isDark ? "#334155" : "#e2e8f0",
        legendColor: isDark ? "#94a3b8" : "#475569",
    };
}

function getProfitPalette(netProfit) {
    if (typeof netProfit === "number" && netProfit < 0) {
        return {
            borderColor: CHART_COLORS.red,
            backgroundColor: CHART_COLORS.redFill,
        };
    }
    return {
        borderColor: CHART_COLORS.green,
        backgroundColor: CHART_COLORS.greenFill,
    };
}

/**
 * Create a standard equity line chart with consistent styling.
 * @param {CanvasRenderingContext2D} ctx - Canvas 2D context
 * @param {Object} config
 * @param {string[]}  config.labels    - X-axis labels
 * @param {Object[]}  config.datasets  - Chart.js dataset objects
 * @param {boolean}   config.isPct     - Whether Y-axis shows percentages
 * @param {Object}    [config.legend]  - Legend config override (default: hidden)
 * @param {boolean}   [config.zoom]    - Enable zoom/pan plugin (default: true)
 * @param {string}    [config.yTitle]  - Y-axis title text
 * @param {Function}  [config.onHover] - Chart onHover callback
 * @param {Function}  [config.tooltipLabel] - Tooltip label callback override
 * @returns {Chart}
 */
function createEquityLineChart(ctx, { labels, datasets, isPct, legend, zoom = true, yTitle, onHover, tooltipLabel }) {
    const { tickColor, gridColor } = getEquityChartColors();
    const yTickCb = isPct ? v => `${Number(v).toFixed(2)}%` : v => fmt(v);
    const defaultTooltipLabel = c => {
        if (c.parsed.y == null) return null;
        return ` ${c.dataset.label}: ${isPct ? `${Number(c.parsed.y).toFixed(2)}%` : fmt(c.parsed.y)}`;
    };

    const plugins = {
        legend: legend || { display: false },
        tooltip: { callbacks: { label: tooltipLabel || defaultTooltipLabel } },
    };
    if (zoom) {
        plugins.zoom = {
            zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: "x" },
            pan: { enabled: true, mode: "x" },
        };
    }

    const yScale = {
        ticks: { color: tickColor, callback: yTickCb },
        grid: { color: gridColor },
    };
    if (yTitle) {
        yScale.title = { display: true, text: yTitle, color: tickColor, font: { size: 11 } };
    }

    return new Chart(ctx, {
        type: "line",
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            onHover,
            plugins,
            scales: {
                x: { ticks: { maxTicksLimit: 12, color: tickColor }, grid: { color: gridColor } },
                y: yScale,
            },
        },
    });
}

// ── API Key injection ─────────────────────────────────────────────────────────
// Intercept all fetch() calls to /api/* and inject X-API-Key automatically.
const _API_KEY = document.querySelector('meta[name="api-key"]')?.content || "";
const _nativeFetch = window.fetch.bind(window);
window.fetch = function(url, options = {}) {
    const isApiCall = typeof url === "string" && url.startsWith("/api/");
    if (isApiCall && _API_KEY) {
        options = {
            ...options,
            headers: { "X-API-Key": _API_KEY, ...(options.headers || {}) },
        };
    }
    return _nativeFetch(url, options);
};

// ── Copy ID utility ──────────────────────────────────────────────────────────
function copyId(id, btn) {
    navigator.clipboard.writeText(String(id)).then(() => {
        const orig = btn.textContent;
        btn.textContent = "✓";
        btn.classList.add("copy-id-success");
        setTimeout(() => {
            btn.textContent = orig;
            btn.classList.remove("copy-id-success");
        }, 1500);
    });
}

// ── Fetch helper ─────────────────────────────────────────────────────────────
async function fetchJson(url, options = {}) {
    const res = await fetch(url, options);
    if (!res.ok) {
        let detail = res.statusText;
        try { detail = (await res.json()).detail || detail; } catch (_) {}
        throw new Error(`HTTP ${res.status}: ${detail}`);
    }
    if (res.status === 204) return null;
    return res.json();
}

async function apiFetch(url, options = {}) {
    const res = await fetch(url, options);
    if (!res.ok) {
        let detail = res.statusText;
        try { detail = (await res.json()).detail || detail; } catch (_) {}
        throw new Error(`HTTP ${res.status}: ${detail}`);
    }
    return res;
}

// WebSocket status indicator
(function setupWsStatus() {
    const wsContainer = document.getElementById("ws-container");
    const statusEl = document.getElementById("ws-status");
    if (!statusEl) return;

    document.body.addEventListener("htmx:wsOpen", function() {
        statusEl.textContent = "Online";
        statusEl.className = "badge badge-active";
    });

    document.body.addEventListener("htmx:wsClose", function() {
        statusEl.textContent = "Offline";
        statusEl.className = "badge badge-inactive";
    });

    document.body.addEventListener("htmx:wsError", function() {
        statusEl.textContent = "Error";
        statusEl.className = "badge badge-inactive";
    });
})();

// Dispatch custom ws-event from HTMX WS messages
document.body.addEventListener("htmx:wsAfterMessage", function(evt) {
    // Pulse the LED on every incoming message
    const led = document.getElementById("ws-pulse");
    if (led) {
        led.classList.remove("ws-pulse-flash");
        void led.offsetWidth; // force reflow to restart animation
        led.classList.add("ws-pulse-flash");
    }

    try {
        const payload = JSON.parse(evt.detail.message);
        window.dispatchEvent(new CustomEvent("ws-event", { detail: payload }));
    } catch (e) {
        // ignore non-JSON messages
    }
});

// ── Shared chart helpers ──────────────────────────────────────────────────

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

function renderPnlBarChart(canvasId, wrapperId, labels, values, chartRef, view = "bar") {
    if (!labels.length) {
        destroyChart(chartRef);
        renderChartEmptyState(wrapperId, "No P&L data.");
        return null;
    }
    const canvas = ensureCanvas(wrapperId, canvasId);
    if (!canvas) return chartRef;
    destroyChart(chartRef);

    const { tickColor, gridColor } = getEquityChartColors();
    const isBar = view === "bar";
    const bgColors = values.map(profitBgColor);
    const brColors = values.map(profitBorderColor);

    return new Chart(canvas.getContext("2d"), {
        type: isBar ? "bar" : "line",
        data: {
            labels,
            datasets: [{
                label: "Net P&L",
                data: values,
                backgroundColor: isBar ? bgColors : CHART_COLORS.mutedBg,
                borderColor: isBar ? brColors : CHART_COLORS.muted,
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
                y: { ticks: { color: tickColor, callback: v => fmt(v) }, grid: { color: gridColor } },
            },
        },
    });
}

function renderDistBarChart(canvasId, wrapperId, labels, profits, chartRef) {
    const hasData = Array.isArray(profits) && profits.some(v => v !== 0);
    if (!labels.length || !hasData) {
        destroyChart(chartRef);
        renderChartEmptyState(wrapperId, "No trade distribution data.");
        return null;
    }
    const canvas = ensureCanvas(wrapperId, canvasId);
    if (!canvas) return chartRef;
    destroyChart(chartRef);
    const orphan = Chart.getChart(canvas);
    if (orphan) orphan.destroy();

    const { tickColor, gridColor } = getEquityChartColors();
    const bgColors = profits.map(profitBgColor);
    const brColors = profits.map(profitBorderColor);

    return new Chart(canvas, {
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
                y: { ticks: { color: tickColor, callback: v => fmt(v) }, grid: { color: gridColor } },
            },
        },
    });
}

function aggregateMonthlyPnl(dailyRows) {
    const agg = {};
    dailyRows.forEach(r => {
        const key = r.date.slice(0, 7);
        agg[key] = (agg[key] || 0) + r.net_profit;
    });
    const labels = Object.keys(agg).sort();
    const values = labels.map(k => parseFloat(agg[k].toFixed(2)));
    return { labels, values };
}

function monthLabelsForDisplay(rawLabels) {
    return rawLabels.map(k => {
        const [y, m] = k.split("-");
        return new Date(y, m - 1).toLocaleDateString("en-GB", { month: "short", year: "2-digit" });
    });
}

function aggregateAnnualPnl(monthlyLabels, monthlyValues) {
    const yearAgg = {};
    monthlyLabels.forEach((k, i) => {
        const year = k.slice(0, 4);
        yearAgg[year] = (yearAgg[year] || 0) + monthlyValues[i];
    });
    const labels = Object.keys(yearAgg).sort();
    const values = labels.map(y => parseFloat(yearAgg[y].toFixed(2)));
    return { labels, values };
}

// ── Export Chart utility ───────────────────────────────────────────────────
function exportChart(canvasId, filename = "chart.png") {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    // Create a temporary canvas
    const tempCanvas = document.createElement("canvas");
    tempCanvas.width = canvas.width;
    tempCanvas.height = canvas.height;
    const ctx = tempCanvas.getContext("2d");

    // Draw background to avoid transparency on dark mode
    const bgColor = getComputedStyle(document.documentElement).getPropertyValue('--surface').trim() ||
                    (document.documentElement.getAttribute("data-theme") === "dark" ? "#1e293b" : "#ffffff");
    ctx.fillStyle = bgColor;
    ctx.fillRect(0, 0, tempCanvas.width, tempCanvas.height);

    // Draw the chart over the background
    ctx.drawImage(canvas, 0, 0);

    const link = document.createElement("a");
    link.download = filename;
    link.href = tempCanvas.toDataURL("image/png");
    link.click();
}

async function setupNavDropdown({ wrapperId, toggleId, itemsId, stateId, loader }) {
    const wrapper = document.getElementById(wrapperId);
    const toggle = document.getElementById(toggleId);
    const items = document.getElementById(itemsId);
    const state = document.getElementById(stateId);
    if (!wrapper || !toggle || !items || !state) return;

    const setOpen = (open) => {
        wrapper.classList.toggle("open", open);
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
    };

    const closeOtherDropdowns = () => {
        document.querySelectorAll(".nav-dropdown.open").forEach((el) => {
            if (el !== wrapper) {
                el.classList.remove("open");
                const btn = el.querySelector(".nav-dropdown-toggle");
                if (btn) btn.setAttribute("aria-expanded", "false");
            }
        });
    };

    toggle.addEventListener("click", async function(e) {
        e.stopPropagation();
        const willOpen = !wrapper.classList.contains("open");
        if (willOpen) closeOtherDropdowns();
        setOpen(willOpen);
        if (willOpen && !items.dataset.loaded) {
            await loader(items, state);
        }
    });

    document.addEventListener("click", function(e) {
        if (!wrapper.contains(e.target)) setOpen(false);
    });

    document.addEventListener("keydown", function(e) {
        if (e.key === "Escape") setOpen(false);
    });
}

async function loadStrategiesDropdown(items, state) {
    try {
        const strategies = await fetchJsonCached("/api/strategies");
        const sorted = [...strategies].sort((a, b) => {
            const an = (a.name || "").toLowerCase();
            const bn = (b.name || "").toLowerCase();
            if (an && bn) return an.localeCompare(bn);
            return String(a.id).localeCompare(String(b.id));
        });

        if (!sorted.length) {
            state.textContent = "No strategies found.";
            items.dataset.loaded = "true";
            return;
        }

        state.style.display = "none";
        items.innerHTML = sorted.map((s) => `
            <a class="nav-dropdown-item" href="/strategy/${s.id}">
                <span>${esc(s.name) || s.id}</span>
                <span class="nav-dropdown-item-meta">ID: ${s.id}</span>
            </a>
        `).join("");
        items.dataset.loaded = "true";
    } catch (e) {
        state.textContent = `Failed to load strategies: ${e.message}`;
    }
}

async function loadPortfoliosDropdown(items, state) {
    try {
        const portfolios = await fetchJsonCached("/api/portfolios/nav");
        const sorted = [...portfolios].sort((a, b) => String(a.name || a.id).localeCompare(String(b.name || b.id)));

        if (!sorted.length) {
            state.textContent = "No portfolios found.";
            items.dataset.loaded = "true";
            return;
        }

        state.style.display = "none";
        items.innerHTML = sorted.map((p) => `
            <a class="nav-dropdown-item" href="/portfolio/${p.id}">
                <span>${esc(p.name) || `Portfolio ${p.id}`}</span>
            </a>
        `).join("");
        items.dataset.loaded = "true";
    } catch (e) {
        state.textContent = `Failed to load portfolios: ${e.message}`;
    }
}

async function loadAccountsDropdown(items, state) {
    try {
        const accounts = await fetchJsonCached("/api/accounts");
        const sorted = [...accounts].sort((a, b) => String(a.name || a.id).localeCompare(String(b.name || b.id)));

        if (!sorted.length) {
            state.textContent = "No accounts found.";
            items.dataset.loaded = "true";
            return;
        }

        state.style.display = "none";
        items.innerHTML = sorted.map((a) => `
            <a class="nav-dropdown-item" href="/account/${encodeURIComponent(a.id)}">
                <span>${esc(a.name) || a.id}</span>
                <span class="nav-dropdown-item-meta">ID: ${a.id}</span>
            </a>
        `).join("");
        items.dataset.loaded = "true";
    } catch (e) {
        state.textContent = `Failed to load accounts: ${e.message}`;
    }
}

async function loadSymbolsDropdown(items, state) {
    try {
        const symbols = await fetchJsonCached("/api/symbols");
        const sorted = [...symbols].sort((a, b) => String(a.name).localeCompare(String(b.name)));

        if (!sorted.length) {
            state.textContent = "No symbols found.";
            items.dataset.loaded = "true";
            return;
        }

        state.style.display = "none";
        items.innerHTML = sorted.map((s) => `
            <a class="nav-dropdown-item" href="/symbol/${encodeURIComponent(s.name)}">
                <span>${esc(s.name)}</span>
                <span class="nav-dropdown-item-meta">${esc(s.market) || "Market unavailable"}</span>
            </a>
        `).join("");
        items.dataset.loaded = "true";
    } catch (e) {
        state.textContent = `Failed to load symbols: ${e.message}`;
    }
}

// ── Inline Error Display ────────────────────────────────────────────────────

function showInlineError(containerId, message) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.style.display = "block";
    el.innerHTML = `<p class="empty-state">${message}</p>`;
}

// ── Toast Notifications ──────────────────────────────────────────────────────

function showToast(title, message, type = "info", duration = 5000) {
    const container = document.getElementById("toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;

    toast.innerHTML = `
        <div class="toast-header">
            <span class="toast-title">${title}</span>
            <button class="toast-close" aria-label="Close">✕</button>
        </div>
        <div class="toast-message">${message}</div>
    `;

    container.appendChild(toast);

    const closeBtn = toast.querySelector(".toast-close");

    const removeToast = () => {
        toast.classList.add("toast-hiding");
        toast.addEventListener("animationend", () => {
            if (toast.parentElement) {
                toast.parentElement.removeChild(toast);
            }
        });
    };

    closeBtn.addEventListener("click", removeToast);

    if (duration > 0) {
        setTimeout(removeToast, duration);
    }
}

// ── Confirm Modal (replaces window.confirm) ──────────────────────────────────
function showConfirmModal(title, body, opts = {}) {
    return new Promise((resolve) => {
        const {
            confirmLabel = "Confirm",
            confirmClass = "btn-danger",
            cancelLabel  = "Cancel",
        } = opts;

        const overlay = document.createElement("div");
        overlay.className = "confirm-modal-overlay";
        overlay.setAttribute("role", "dialog");
        overlay.setAttribute("aria-modal", "true");
        overlay.setAttribute("aria-labelledby", "confirm-modal-title");

        overlay.innerHTML = `
            <div class="confirm-modal">
                <div class="confirm-modal-title" id="confirm-modal-title">
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
                    ${title}
                </div>
                <div class="confirm-modal-body">${body}</div>
                <div class="confirm-modal-actions">
                    <button class="btn btn-ghost btn-sm" id="confirm-cancel-btn">${cancelLabel}</button>
                    <button class="btn ${confirmClass} btn-sm" id="confirm-ok-btn">${confirmLabel}</button>
                </div>
            </div>`;

        document.body.appendChild(overlay);

        const cleanup = (result) => {
            if (overlay.parentElement) overlay.parentElement.removeChild(overlay);
            resolve(result);
        };

        overlay.querySelector("#confirm-ok-btn").addEventListener("click", () => cleanup(true));
        overlay.querySelector("#confirm-cancel-btn").addEventListener("click", () => cleanup(false));
        overlay.addEventListener("click", (e) => { if (e.target === overlay) cleanup(false); });
        document.addEventListener("keydown", function onKey(e) {
            if (e.key === "Escape") { cleanup(false); document.removeEventListener("keydown", onKey); }
        });
        setTimeout(() => overlay.querySelector("#confirm-cancel-btn")?.focus(), 50);
    });
}

// ── Mobile Navigation Drawer ─────────────────────────────────────────────────
function setupMobileNav() {
    if (document.getElementById("nav-drawer")) return;
    const path = window.location.pathname;
    const links = [
        { href: "/",           label: "Overview" },
        { href: "/real",       label: "Live Monitor" },
        { href: "/advanced-analysis", label: "Advanced Analysis" },
        { href: "/benchmarks", label: "Benchmarks" },
        { href: "/settings",   label: "Settings" },
    ];

    const drawer = document.createElement("div");
    drawer.id = "nav-drawer";
    drawer.className = "nav-drawer";
    drawer.setAttribute("role", "navigation");
    drawer.setAttribute("aria-label", "Mobile navigation");
    drawer.innerHTML = `
        <div class="nav-drawer-header">
            <a class="nav-brand" href="/">
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>
                TradingMonitor
            </a>
            <button class="nav-drawer-close" id="nav-drawer-close" aria-label="Close menu">
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
            </button>
        </div>
        <div class="nav-drawer-section">Navigation</div>
        ${links.map(l => `<a href="${l.href}" class="${path === l.href || (l.href !== "/" && path.startsWith(l.href)) ? "active" : ""}">${l.label}</a>`).join("")}
    `;

    const mobOverlay = document.createElement("div");
    mobOverlay.id = "nav-mobile-overlay";
    mobOverlay.className = "nav-mobile-overlay";

    document.body.appendChild(mobOverlay);
    document.body.appendChild(drawer);

    const openDrawer  = () => { drawer.classList.add("open"); mobOverlay.classList.add("open"); document.body.style.overflow = "hidden"; };
    const closeDrawer = () => { drawer.classList.remove("open"); mobOverlay.classList.remove("open"); document.body.style.overflow = ""; };

    document.getElementById("nav-hamburger")?.addEventListener("click", openDrawer);
    document.getElementById("nav-drawer-close").addEventListener("click", closeDrawer);
    mobOverlay.addEventListener("click", closeDrawer);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && drawer.classList.contains("open")) closeDrawer(); });
}

// Listen to WebSocket events globally to show toasts

window.addEventListener("ws-event", function(e) {
    const payload = e.detail;
    if (!payload || !payload.topic) return;

    const topic = payload.topic;
    const data = payload.data || {};

    if (topic === "DEAL") {
        const stratId = data.magic || data.strategy_id || "Unknown";
        const symbol = data.symbol || "";
        const profit = data.profit || 0;
        const net = profit + (data.commission || 0) + (data.swap || 0);
        const type = net >= 0 ? "success" : "error";
        const action = data.type ? data.type.toUpperCase() : "TRADE";

        const title = `New ${action} Executed`;
        const msg = `Strategy: <a href="/strategy/${stratId}" style="color:inherit;text-decoration:underline;">${stratId}</a><br>Symbol: ${symbol}<br>Net: <strong>${fmt(net)}</strong>`;

        showToast(title, msg, type);
    } else if (topic === "BACKTEST_END") {
        const stratId = data.strategy_id || data.magic || "Unknown";
        const btId = data.backtest_id || "Unknown";

        showToast(
            "Backtest Completed",
            `Strategy: <a href="/strategy/${stratId}" style="color:inherit;text-decoration:underline;">${stratId}</a><br>Run ID: #${btId}`,
            "info",
            10000
        );
    }
    // We intentionally ignore high-frequency events like EQUITY here to avoid spamming the user.
});
