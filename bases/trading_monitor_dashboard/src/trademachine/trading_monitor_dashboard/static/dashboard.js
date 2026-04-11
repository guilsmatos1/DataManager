// ── Theme ────────────────────────────────────────────────────────────────────
function _applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("tm-theme", theme);

    const btn = document.getElementById("theme-toggle");
    if (btn) btn.textContent = theme === "dark" ? "🌙" : "☀";

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

// ── Time utilities ──────────────────────────────────────────────────────────
function timeAgo(ts) {
    const s = Math.floor((Date.now() - ts) / 1000);
    if (s < 10)   return "agora";
    if (s < 60)   return `${s}s atrás`;
    if (s < 3600) return `${Math.floor(s / 60)}m atrás`;
    return `${Math.floor(s / 3600)}h atrás`;
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

// Number formatter
function fmt(value, decimals = 2) {
    if (value === null || value === undefined) return "—";
    if (typeof value !== "number") return value;
    return value.toLocaleString("pt-BR", {
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

    container.innerHTML = Object.entries(metrics)
        .filter(([key]) => {
            const keyLower = key.toLowerCase();
            return !advancedKeys.has(keyLower) && !hiddenKeys.has(keyLower);
        })
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

function buildRebasedEquitySeries(points, scale, valueGetter = (point) => point.equity) {
    const baseline = Number(valueGetter(points[0])) || 1;
    return points.map((point) => {
        const value = Number(valueGetter(point)) || 0;
        if (scale === "pct") {
            const absBaseline = Math.abs(baseline) || 1;
            return parseFloat((((value - baseline) / absBaseline) * 100).toFixed(4));
        }
        return parseFloat((value - baseline).toFixed(4));
    });
}

function getEquityChartColors() {
    const isDark = document.documentElement.getAttribute("data-theme") !== "light";
    return {
        tickColor: isDark ? "#64748b" : "#94a3b8",
        gridColor: isDark ? "#334155" : "#e2e8f0",
        legendColor: isDark ? "#94a3b8" : "#475569",
    };
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
        statusEl.textContent = "Erro";
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

// ── Export Chart utility ───────────────────────────────────────────────────
function exportChart(canvasId, filename = "chart.png") {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    // If we want to ensure the background is captured (for dark mode)
    // we might need to draw to a temp canvas with background, but
    // Chart.js usually doesn't fill the canvas background.
    // However, for simplicity and "what you see is what you get":
    const link = document.createElement("a");
    link.download = filename;
    link.href = canvas.toDataURL("image/png");
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
        const strategies = await fetchJson("/api/strategies");
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
                <span>${s.name || s.id}</span>
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
        const portfolios = await fetchJson("/api/portfolios/nav");
        const sorted = [...portfolios].sort((a, b) => String(a.name || a.id).localeCompare(String(b.name || b.id)));

        if (!sorted.length) {
            state.textContent = "No portfolios found.";
            items.dataset.loaded = "true";
            return;
        }

        state.style.display = "none";
        items.innerHTML = sorted.map((p) => `
            <a class="nav-dropdown-item" href="/portfolio/${p.id}">
                <span>${p.name || `Portfolio ${p.id}`}</span>
            </a>
        `).join("");
        items.dataset.loaded = "true";
    } catch (e) {
        state.textContent = `Failed to load portfolios: ${e.message}`;
    }
}

async function loadAccountsDropdown(items, state) {
    try {
        const accounts = await fetchJson("/api/accounts");
        const sorted = [...accounts].sort((a, b) => String(a.name || a.id).localeCompare(String(b.name || b.id)));

        if (!sorted.length) {
            state.textContent = "No accounts found.";
            items.dataset.loaded = "true";
            return;
        }

        state.style.display = "none";
        items.innerHTML = sorted.map((a) => `
            <a class="nav-dropdown-item" href="/account/${encodeURIComponent(a.id)}">
                <span>${a.name || a.id}</span>
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
        const symbols = await fetchJson("/api/symbols");
        const sorted = [...symbols].sort((a, b) => String(a.name).localeCompare(String(b.name)));

        if (!sorted.length) {
            state.textContent = "No symbols found.";
            items.dataset.loaded = "true";
            return;
        }

        state.style.display = "none";
        items.innerHTML = sorted.map((s) => `
            <a class="nav-dropdown-item" href="/symbol/${encodeURIComponent(s.name)}">
                <span>${s.name}</span>
                <span class="nav-dropdown-item-meta">${s.market || "Market unavailable"}</span>
            </a>
        `).join("");
        items.dataset.loaded = "true";
    } catch (e) {
        state.textContent = `Failed to load symbols: ${e.message}`;
    }
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
