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
        const portfolios = await fetchJson("/api/portfolios");
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
            </a>
        `).join("");
        items.dataset.loaded = "true";
    } catch (e) {
        state.textContent = `Failed to load symbols: ${e.message}`;
    }
}
