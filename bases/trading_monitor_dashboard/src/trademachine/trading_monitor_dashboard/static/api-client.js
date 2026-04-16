/* ── API Client — shared data-fetching functions ─────────────────────────────── */

let _portfolio = null;
let _portfolioTotalTrades = null;
let _portfolioNetProfit = null;

// ── Overview page (index.html) ───────────────────────────────────────────────

async function loadSummary(silent = false) {
    try {
        const res = await fetch("/api/summary");
        if (!res.ok) throw new Error(`API error ${res.status}`);
        const d = await res.json();

        document.getElementById("count-strategies").textContent = d.strategies_count ?? "—";
        document.getElementById("count-portfolios").textContent = d.portfolios_count ?? "—";
        document.getElementById("count-accounts").textContent   = d.accounts_count   ?? "—";

        // Show zero-state onboarding when there are no strategies
        const zeroState = document.getElementById("zero-state");
        if (zeroState) {
            zeroState.style.display = (d.strategies_count === 0) ? "" : "none";
        }

        if (!silent) {
            renderPie("symbol",   "pie-symbol",   d.by_symbol);
            renderPie("style",    "pie-style",    d.by_style);
            renderPie("duration", "pie-duration", d.by_duration);
        }
    } catch (e) {
        if (!silent) {
            console.error("Summary load error:", e);
            ["pie-symbol","pie-style","pie-duration"].forEach(id => {
                const canvas = document.getElementById(id);
                if (canvas) canvas.parentElement.innerHTML =
                    `<p class="chart-empty">No data — ${e.message}</p>`;
            });
        }
    }
}

async function loadStrategies(silent = false) {
    if (!silent) {
        const el = document.getElementById("table-all-strategies");
        if (el) el.innerHTML = skelRows(2);
    }
    try {
        const res = await fetch("/api/strategies");
        if (!res.ok) throw new Error(`API error ${res.status}`);
        _allStrategies = await res.json();
        renderStrategiesTable();
    } catch (e) {
        console.error("Strategies load error:", e);
        if (!silent) {
            const el = document.getElementById("table-all-strategies");
            if (el) el.innerHTML = `<p class="error">Failed to load strategies: ${e.message}</p>`;
        }
    }
}

async function loadAccounts() {
    const container = document.getElementById("accounts-table-container");
    try {
        _allAccounts = await fetchJson("/api/accounts");
        document.getElementById("accounts-badge").textContent = `${_allAccounts.length} total`;
        renderAccountsTable();
    } catch(e) {
        container.innerHTML = `<p class="error">Failed to load accounts: ${e.message}</p>`;
    }
}

async function loadPortfolios() {
    try {
        const res = await fetch("/api/portfolios");
        if (!res.ok) throw new Error(`API error ${res.status}`);
        _allPortfolios = await res.json();
        document.getElementById("portfolios-badge").textContent = `${_allPortfolios.length} total`;
        renderPortfoliosTable();
    } catch(e) {
        document.getElementById("portfolios-table-container").innerHTML =
            `<p class="error">Failed to load portfolios: ${e.message}</p>`;
    }
}

async function loadSymbols(silent = false) {
    if (!silent) {
        const el = document.getElementById("symbols-table-container");
        if (el) el.innerHTML = skelRows(1);
    }
    try {
        _allSymbols = await fetchJson("/api/symbols");
        document.getElementById("symbols-badge").textContent = `${_allSymbols.length} total`;
        renderSymbolsTable();
    } catch(e) {
        document.getElementById("symbols-table-container").innerHTML =
            `<p class="error">Failed to load symbols: ${e.message}</p>`;
    }
}

async function loadFloatingPnL() {
    try {
        const data = await fetchJson("/api/floating-pnl");
        const badge = document.getElementById("floating-total-badge");
        const container = document.getElementById("floating-container");
        const updated = document.getElementById("floating-updated");

        const total = data.total_floating_pnl ?? 0;
        badge.textContent = fmt(total);
        badge.className = "badge " + (total >= 0 ? "badge-live" : "badge-incubation");
        if (updated) updated.textContent = "updated " + new Date().toLocaleTimeString();

        const items = data.strategies || [];
        if (!items.length) {
            container.innerHTML = '<p class="empty-state">No open positions.</p>';
            return;
        }
        const rows = items.map(s => {
            const fp = s.floating_pnl ?? 0;
            const cls = fp >= 0 ? "profit-positive" : "profit-negative";
            return `<tr>
                <td class="mono">${s.strategy_id}</td>
                <td>${esc(s.strategy_name) || "—"}</td>
                <td style="font-variant-numeric:tabular-nums">${s.balance != null ? fmt(s.balance) : "—"}</td>
                <td style="font-variant-numeric:tabular-nums">${s.equity != null ? fmt(s.equity) : "—"}</td>
                <td class="${cls}" style="font-variant-numeric:tabular-nums">${fmt(fp)}</td>
            </tr>`;
        }).join("");
        container.innerHTML = `<div class="table-responsive"><table class="data-table">
            <thead><tr><th>ID</th><th>Strategy</th><th>Balance</th><th>Equity</th><th>Floating P&amp;L</th></tr></thead>
            <tbody>${rows}</tbody>
        </table></div>`;
    } catch(e) {
        document.getElementById("floating-container").innerHTML =
            `<p class="text-muted" style="padding:0.5rem">No data available.</p>`;
    }
}

// ── CRUD actions ──────────────────────────────────────────────────────────────

async function createOrUpdatePortfolio() {
    const status = document.getElementById("create-status");
    const name = document.getElementById("new-name").value.trim();
    if (!name) { status.textContent = "❌ Name is required"; return; }
    status.textContent = _editingPortfolioId ? "Saving..." : "Creating...";
    const checkedIds = [...document.querySelectorAll("#new-strategy-list input:checked")].map(el => el.value);
    const ibRaw = document.getElementById("new-initial-balance").value;
    const payload = {
        name,
        description: document.getElementById("new-description").value || null,
        strategy_ids: checkedIds,
        initial_balance: ibRaw !== "" ? parseFloat(ibRaw) : null,
    };
    try {
        let res;
        if (_editingPortfolioId) {
            res = await fetch(`/api/portfolios/${_editingPortfolioId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
        } else {
            res = await fetch("/api/portfolios", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
        }
        if (!res.ok) throw new Error(await res.text());
        const p = await res.json();
        closeCreateModal();
        loadPortfolios();
        loadSummary();
        if (!_editingPortfolioId) {
            window.location = `/portfolio/${p.id}`;
        }
    } catch(err) {
        status.textContent = "❌ " + err.message;
    }
}

async function deleteStrategy(id, name) {
    const confirmed = await showConfirmModal(
        "Delete Strategy",
        `Delete strategy <strong>${name}</strong> (${id})?<br><br>This will permanently remove all associated deals and equity data.`,
        { confirmLabel: "Delete", confirmClass: "btn-danger" }
    );
    if (!confirmed) return;
    const res = await fetch(`/api/strategies/${id}`, { method: "DELETE" });
    if (res.ok) { loadSummary(); loadStrategies(); }
    else showToast("Error", "Failed to delete strategy.", "error");
}

async function deletePortfolio(id, name) {
    const confirmed = await showConfirmModal(
        "Delete Portfolio",
        `Delete portfolio <strong>${name}</strong>?<br><br>This will <em>not</em> delete the strategies inside it.`,
        { confirmLabel: "Delete", confirmClass: "btn-danger" }
    );
    if (!confirmed) return;
    const res = await fetch(`/api/portfolios/${id}`, { method: "DELETE" });
    if (res.ok) { loadPortfolios(); loadSummary(); }
    else showToast("Error", "Failed to delete portfolio.", "error");
}

async function patchStrategy(id, data) {
    return fetchJson(`/api/strategies/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
    });
}

async function patchPortfolio(id, data) {
    return fetchJson(`/api/portfolios/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
    });
}

async function patchAccount(id, data) {
    return fetchJson(`/api/accounts/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
    });
}

async function saveSymbol() {
    const status = document.getElementById("sym-status");
    const name = document.getElementById("sym-name").value.trim();
    if (!name) { status.textContent = "❌ Name is required"; return; }
    const lot = document.getElementById("sym-lot").value.trim();
    const payload = {
        name,
        market: document.getElementById("sym-market").value || null,
        lot: lot !== "" && !isNaN(parseFloat(lot)) ? parseFloat(lot) : null,
    };
    status.textContent = "Saving…";
    try {
        if (_editingSymbolId) {
            await fetchJson(`/api/symbols/${_editingSymbolId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
        } else {
            await fetchJson("/api/symbols", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
        }
        closeSymbolModal();
        await loadSymbols(true);
    } catch(e) {
        status.textContent = "❌ " + e.message;
    }
}

async function deleteSymbol(id, name) {
    const confirmed = await showConfirmModal(
        "Delete Symbol",
        `Delete symbol <strong>${name}</strong>?`,
        { confirmLabel: "Delete", confirmClass: "btn-danger" }
    );
    if (!confirmed) return;
    try {
        await fetchJson(`/api/symbols/${id}`, { method: "DELETE" });
        await loadSymbols(true);
    } catch(e) { showToast("Error", "Failed to delete symbol.", "error"); }
}

// ── Portfolio page ────────────────────────────────────────────────────────────

async function loadPortfolio() {
    const res = await fetch(`/api/portfolios/${PORTFOLIO_ID}`);
    if (!res.ok) return;
    _portfolio = await res.json();

    document.getElementById("portfolio-title").innerHTML =
        `${esc(_portfolio.name) || "Portfolio"} <span class="mono" style="font-size:0.75em;color:var(--text-muted)">#${_portfolio.id}</span>`;

    const badge = document.getElementById("portfolio-status-badge");
    badge.textContent = _portfolio.live ? "Live" : "Incubation";
    badge.className = `badge ${_portfolio.live ? "badge-live" : "badge-incubation"}`;

    const fields = [
        ["Status",       _portfolio.live ? "Live" : "Incubation"],
        ["Account Type", _portfolio.real_account ? "Real" : "Demo"],
        ["Strategies",   _portfolio.strategy_ids.length + " linked"],
        ["Initial Balance", _portfolio.initial_balance != null ? fmt(_portfolio.initial_balance) : null],
        ["Description",  _portfolio.description],
    ];
    document.getElementById("info-container").innerHTML = fields
        .filter(([, v]) => v != null && v !== "")
        .map(([label, value]) => `
            <div class="info-item">
                <span class="info-label">${label}</span>
                <span class="info-value">${esc(value)}</span>
            </div>`).join("");

    if (typeof updateAdvancedAnalysisLink === "function") {
        updateAdvancedAnalysisLink();
    }
}

async function loadMetrics() {
    try {
        const res = await fetch(`/api/portfolios/${PORTFOLIO_ID}/metrics`);
        const data = await res.json();
        const container = document.getElementById("metrics-container");
        if (data.error) {
            _portfolioTotalTrades = null;
            _portfolioNetProfit = null;
            container.innerHTML = `<p class="empty-state">${data.error}</p>`;
            return;
        }
        _portfolioTotalTrades = Number.isFinite(Number(data["Total Trades"]))
            ? Number(data["Total Trades"])
            : null;
        _portfolioNetProfit = Number.isFinite(Number(data.Profit))
            ? Number(data.Profit)
            : null;
        renderMetricsGrid(container, data, {
            hiddenKeys: ["gross profit", "gross loss"],
            integerKeys: ["total trades"],
            negateKeys: ["gross loss"],
        });
        if (_allEquityPoints.length) {
            renderEquityChart(_allEquityPoints, {}, _equityPeriod);
        }
        markUpdated("metrics");
    } catch(e) {
        _portfolioTotalTrades = null;
        _portfolioNetProfit = null;
        document.getElementById("metrics-container").innerHTML = '<p class="error">Error loading metrics.</p>';
    }
}

async function loadEquity() {
    try {
        const res = await fetch(`/api/portfolios/${PORTFOLIO_ID}/equity/breakdown`);
        const data = await res.json();
        _allEquityPoints = data.total || [];
        renderEquityChart(_allEquityPoints, {}, _equityPeriod);
        markUpdated("equity");
    } catch(e) { console.error("Equity load error:", e); }
}

async function loadCalendar() {
    try {
        const res = await fetch(`/api/portfolios/${PORTFOLIO_ID}/daily`);
        const rows = await res.json();
        _dailyData = {};
        rows.forEach(r => {
            _dailyData[r.date] = { profit: r.net_profit, count: r.trades_count };
        });
        renderCalendar();
    } catch(e) { console.error("Calendar load error:", e); }
}

async function loadAllStrategiesForEdit() {
    const container = document.getElementById("edit-strategy-list");
    if (!_allStrategies.length) {
        const res = await fetch("/api/strategies");
        _allStrategies = await res.json();
    }
    renderEditStrategiesTable();
}

async function toggleEdit() {
    const form = document.getElementById("edit-form");
    if (!form) return;

    const isHidden = form.style.display === "none";
    if (isHidden && typeof PORTFOLIO_ID !== "undefined" && _portfolio) {
        document.getElementById("edit-name").value = _portfolio.name || "";
        document.getElementById("edit-description").value = _portfolio.description || "";
        document.getElementById("edit-live").checked = _portfolio.live || false;
        document.getElementById("edit-real").checked = _portfolio.real_account || false;
        await loadAllStrategiesForEdit();
    }

    form.style.display = isHidden ? "block" : "none";
    const status = document.getElementById("edit-status");
    if (status) status.textContent = "";
}

async function savePortfolio() {
    const status = document.getElementById("edit-status");
    status.textContent = "Saving...";
    const checkedIds = [...document.querySelectorAll("#edit-strategy-list input:checked")].map(el => el.value);
    const payload = {
        name: document.getElementById("edit-name").value || null,
        description: document.getElementById("edit-description").value || null,
        live: document.getElementById("edit-live").checked,
        real_account: document.getElementById("edit-real").checked,
        strategy_ids: checkedIds,
    };
    try {
        const res = await fetch(`/api/portfolios/${PORTFOLIO_ID}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error(await res.text());
        _portfolio = await res.json();
        status.textContent = "✅ Saved";
        setTimeout(() => {
            document.getElementById("edit-form").style.display = "none";
            loadPortfolio();
            loadStrategies();
            loadEquity();
            loadMetrics();
        }, 700);
    } catch(err) {
        status.textContent = "❌ " + err.message;
    }
}

async function confirmDelete() {
    const confirmed = await showConfirmModal(
        "Delete Portfolio",
        `Delete portfolio <strong>${_portfolio?.name}</strong>? This action cannot be undone.`,
        { confirmLabel: "Delete", confirmClass: "btn-danger" }
    );
    if (!confirmed) return;
    const res = await fetch(`/api/portfolios/${PORTFOLIO_ID}`, { method: "DELETE" });
    if (res.ok) window.location = "/";
    else showToast("Error", "Failed to delete portfolio.", "error");
}
