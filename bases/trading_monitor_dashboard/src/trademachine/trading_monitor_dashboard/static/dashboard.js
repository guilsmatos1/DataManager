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

// ── Fetch helper ─────────────────────────────────────────────────────────────
async function fetchJson(url, options = {}) {
    const res = await fetch(url, options);
    if (!res.ok) {
        let detail = res.statusText;
        try { detail = (await res.json()).detail || detail; } catch (_) {}
        throw new Error(`HTTP ${res.status}: ${detail}`);
    }
    return res.json();
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
    try {
        const payload = JSON.parse(evt.detail.message);
        window.dispatchEvent(new CustomEvent("ws-event", { detail: payload }));
    } catch (e) {
        // ignore non-JSON messages
    }
});
