/* ── Table & Chart Rendering ────────────────────────────────────────────────── */

const CHART_COLORS = [
    "#3b82f6","#10b981","#f59e0b","#ef4444","#8b5cf6",
    "#ec4899","#06b6d4","#84cc16","#f97316","#a78bfa"
];

const charts = { symbol: null, style: null, duration: null };

// ── Pie charts (index.html) ───────────────────────────────────────────────────

function renderPie(key, canvasId, data) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    if (charts[key]) { charts[key].destroy(); charts[key] = null; }

    const labels = Object.keys(data || {});
    const values = Object.values(data || {});

    if (labels.length === 0) {
        canvas.parentElement.innerHTML = '<p class="chart-empty">No data yet</p>';
        return;
    }

    charts[key] = new Chart(canvas, {
        type: "doughnut",
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: CHART_COLORS.slice(0, labels.length),
                borderColor: "transparent",
                borderWidth: 0,
                hoverOffset: 4,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: "bottom",
                    labels: { boxWidth: 12, padding: 10, font: { size: 11 } }
                }
            }
        }
    });
}

// ── Cell formatters ───────────────────────────────────────────────────────────

function npCell(val) {
    if (val == null) return `<td class="text-muted" style="font-variant-numeric:tabular-nums">—</td>`;
    const cls = val >= 0 ? "profit-positive" : "profit-negative";
    return `<td class="${cls}" style="font-variant-numeric:tabular-nums">${fmt(val)}</td>`;
}

function portfolioNpCell(val) {
    if (val == null) return `<td class="text-muted">—</td>`;
    const cls = val >= 0 ? "profit-positive" : "profit-negative";
    return `<td class="${cls}" style="font-variant-numeric:tabular-nums">${fmt(val)}</td>`;
}

// ── Strategies table (index.html) ─────────────────────────────────────────────

let _allStrategies = [];
let _stratSortCol = "id", _stratSortAsc = true;
let _stratPage = 1;

function renderStrategiesTable() {
    const q = (document.getElementById("strat-search")?.value || "").toLowerCase();
    let list = _allStrategies.filter(s =>
        !q || `${s.id} ${s.name || ""} ${s.symbol || ""}`.toLowerCase().includes(q));

    document.getElementById("badge-strategies").textContent = list.length;

    const container = document.getElementById("table-all-strategies");
    if (!list.length) {
        container.innerHTML = '<p class="empty-state">No strategies found.</p>';
        return;
    }

    // Filter out invalid entries (e.g., API returns "——" as placeholder)
    list = list.filter(s => s.id && String(s.id) !== "——");

    if (_stratSortCol) {
        list = [...list].sort((a, b) => {
            let va = a[_stratSortCol], vb = b[_stratSortCol];
            if (va == null) va = _stratSortAsc ? Infinity : -Infinity;
            if (vb == null) vb = _stratSortAsc ? Infinity : -Infinity;
            return _stratSortAsc ? (va > vb ? 1 : -1) : (va < vb ? 1 : -1);
        });
    }

    const th = (label, c) => {
        const arrow = _stratSortCol === c ? (_stratSortAsc ? " ↑" : " ↓") : "";
        return `<th class="sortable" onclick="stratSortBy('${c}')">${label}${arrow}</th>`;
    };

    const ps = parseInt(document.getElementById("strat-page-size")?.value || "25");
    const total = list.length;
    const totalPages = Math.ceil(total / ps) || 1;
    if (_stratPage > totalPages) _stratPage = 1;
    const pageList = list.slice((_stratPage - 1) * ps, _stratPage * ps);

    const STALE_MS = 5 * 60 * 1000;
    const now = Date.now();
    const rows = pageList.map(s => {
        const npBt   = s.backtest_net_profit ?? null;
        const npDemo = !s.real_account ? s.net_profit : null;
        const npReal = s.real_account  ? s.net_profit : null;
        const liveCls   = s.live ? "badge-live" : "badge-incubation";
        const liveLabel = s.live ? "Live" : "Incubation";
        let signalDot = "";
        if (s.live) {
            if (!s.last_seen_at) {
                signalDot = `<span class="signal-dot signal-unknown" title="Aguardando dados…"></span>`;
            } else {
                const age = now - new Date(s.last_seen_at).getTime();
                const mins = Math.round(age / 60000);
                signalDot = age > STALE_MS
                    ? `<span class="signal-dot signal-stale" title="Sem dados há ${mins}min"></span>`
                    : `<span class="signal-dot signal-ok"    title="Ativo (há ${mins}min)"></span>`;
            }
        }
        const liveBadge = `<span class="badge ${liveCls} editable-badge" onclick="event.stopPropagation();toggleStratLive('${s.id}',${s.live})">${liveLabel}</span>`;
        let zombieBadge = "";
        if (s.zombie_alert) {
            const lastT = s.last_trade_at ? new Date(s.last_trade_at) : null;
            const hoursAgo = lastT ? Math.round((Date.now() - lastT.getTime()) / 3600000) : "?";
            zombieBadge = `<span class="badge badge-zombie" title="Sem trades há ${hoursAgo}h — verifique o robô">Zombie</span>`;
        }
        const npPct = (np, ib) => {
            if (np == null || np === "—" || ib == null || ib <= 0) return `<td class="text-muted">—</td>`;
            const pct = (np / ib) * 100;
            const cls = pct >= 0 ? "profit-positive" : "profit-negative";
            return `<td class="${cls}" style="font-variant-numeric:tabular-nums">${pct.toFixed(2)}%</td>`;
        };
        return `<tr class="clickable-row" onclick="window.location='/strategy/${s.id}'">
            <td class="mono">${s.id}<button class="btn-copy-id" onclick="event.stopPropagation();copyId('${s.id}',this)" title="Copy Magic Number">⎘</button></td>
            <td class="editable-cell" data-strat-id="${s.id}" data-field="name" onclick="event.stopPropagation();startEdit(this)">${s.name || "—"}</td>
            <td>${s.symbol || "—"}</td>
            <td class="editable-cell" data-strat-id="${s.id}" data-field="timeframe" onclick="event.stopPropagation();startEdit(this)">${s.timeframe || "—"}</td>
            <td>${s.operational_style || "—"}</td>
            <td class="editable-cell" data-strat-id="${s.id}" data-field="trade_duration" onclick="event.stopPropagation();startEdit(this)">${s.trade_duration || "—"}</td>
            <td class="editable-cell" data-strat-id="${s.id}" data-field="initial_balance" data-type="number" onclick="event.stopPropagation();startEdit(this)" style="font-variant-numeric:tabular-nums">${s.initial_balance != null ? fmt(s.initial_balance) : "—"}</td>
            ${npPct(npBt, s.initial_balance)}${npPct(npDemo, s.initial_balance)}${npPct(npReal, s.initial_balance)}
            <td>${signalDot}${liveBadge}${zombieBadge}</td>
            <td><button class="btn-delete-row" title="Delete" onclick="event.stopPropagation();deleteStrategy('${s.id}','${(s.name||s.id).replace(/'/g,"\\'")}')">✕</button></td>
        </tr>`;
    }).join("");

    container.innerHTML = `<table class="data-table">
        <thead><tr>
            ${th("ID","id")}${th("Name","name")}${th("Symbol","symbol")}
            ${th("TF","timeframe")}${th("Style","operational_style")}${th("Duration","trade_duration")}
            ${th("Initial Balance","initial_balance")}
            ${th("NP Backtest","backtest_net_profit")}${th("NP Demo","net_profit")}${th("NP Real","net_profit")}
            <th>Status</th><th>Actions</th>
        </tr></thead>
        <tbody>${rows}</tbody>
    </table>`;

    const pg = document.getElementById("strat-pagination");
    if (pg) {
        pg.innerHTML = totalPages <= 1 ? "" : `
            <button onclick="stratGoPage(${_stratPage-1})" ${_stratPage<=1?"disabled":""}>← Previous</button>
            <span>Page ${_stratPage} of ${totalPages}</span>
            <button onclick="stratGoPage(${_stratPage+1})" ${_stratPage>=totalPages?"disabled":""}>Next →</button>`;
    }
}

function stratSortBy(col) {
    if (_stratSortCol === col) _stratSortAsc = !_stratSortAsc;
    else { _stratSortCol = col; _stratSortAsc = true; }
    _stratPage = 1;
    renderStrategiesTable();
}

function stratGoPage(p) { _stratPage = p; renderStrategiesTable(); }

// ── Accounts table (index.html) ───────────────────────────────────────────────

let _allAccounts = [];
let _acctSortCol = "id", _acctSortAsc = true;
let _acctPage = 1;

function renderAccountsTable() {
    const container = document.getElementById("accounts-table-container");
    const q = (document.getElementById("accounts-search")?.value || "").toLowerCase().trim();
    let list = _allAccounts.filter(a =>
        !q || `${a.id} ${a.name||""} ${a.broker||""} ${a.account_type||""} ${a.currency||""}`.toLowerCase().includes(q));
    if (!list.length) {
        container.innerHTML = '<p class="empty-state">No accounts registered.</p>';
        document.getElementById("acct-pagination").innerHTML = "";
        return;
    }
    if (_acctSortCol) {
        list = [...list].sort((a, b) => {
            let va = a[_acctSortCol], vb = b[_acctSortCol];
            if (va == null) va = _acctSortAsc ? "\uffff" : "";
            if (vb == null) vb = _acctSortAsc ? "\uffff" : "";
            if (typeof va === "number" && typeof vb === "number")
                return _acctSortAsc ? va - vb : vb - va;
            return _acctSortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
        });
    }
    const tha = (label, c) => {
        const arrow = _acctSortCol === c ? (_acctSortAsc ? " ↑" : " ↓") : "";
        return `<th class="sortable" onclick="acctSortBy('${c}')">${label}${arrow}</th>`;
    };
    const ps = parseInt(document.getElementById("acct-page-size")?.value || "25");
    const total = list.length;
    const totalPages = Math.ceil(total / ps) || 1;
    if (_acctPage > totalPages) _acctPage = 1;
    const pageList = list.slice((_acctPage - 1) * ps, _acctPage * ps);

    const rows = pageList.map(a => {
        const balanceCls  = (a.balance ?? 0) >= 0 ? "profit-positive" : "profit-negative";
        const marginCls   = (a.free_margin ?? 0) >= 0 ? "profit-positive" : "profit-negative";
        const depositsCls = (a.total_deposits ?? 0) > 0 ? "profit-positive" : "";
        const withdrawCls = (a.total_withdrawals ?? 0) > 0 ? "profit-negative" : "";
        const npCls       = a.net_profit == null ? "" : a.net_profit >= 0 ? "profit-positive" : "profit-negative";
        return `<tr class="clickable-row" onclick="window.location='/account/${encodeURIComponent(a.id)}'">
            <td class="mono">${a.id}</td>
            <td class="editable-cell" data-account-id="${a.id}" data-field="name" onclick="event.stopPropagation();startAccountEdit(this)">${a.name || "—"}</td>
            <td>${a.broker || "—"}</td>
            <td><span class="badge ${a.account_type?.toLowerCase().includes('real') ? 'badge-real' : 'badge-demo'}">${a.account_type || "—"}</span></td>
            <td class="editable-cell" data-account-id="${a.id}" data-field="currency" onclick="event.stopPropagation();startAccountEdit(this)">${a.currency || "—"}</td>
            <td class="${balanceCls}" style="font-variant-numeric:tabular-nums">${a.balance != null ? fmt(a.balance) : "—"}</td>
            <td class="${marginCls}" style="font-variant-numeric:tabular-nums">${a.free_margin != null ? fmt(a.free_margin) : "—"}</td>
            <td class="${depositsCls}" style="font-variant-numeric:tabular-nums">${a.total_deposits ? fmt(a.total_deposits) : "—"}</td>
            <td class="${withdrawCls}" style="font-variant-numeric:tabular-nums">${a.total_withdrawals ? fmt(a.total_withdrawals) : "—"}</td>
            <td class="${npCls}" style="font-variant-numeric:tabular-nums;font-weight:600">${a.net_profit != null ? fmt(a.net_profit) : "—"}</td>
        </tr>`;
    }).join("");
    container.innerHTML = `<table class="data-table">
        <thead><tr>
            ${tha("Number","id")}${tha("Name","name")}${tha("Broker","broker")}
            ${tha("Type","account_type")}${tha("Currency","currency")}
            ${tha("Balance","balance")}${tha("Free Margin","free_margin")}
            ${tha("Deposits","total_deposits")}${tha("Withdrawals","total_withdrawals")}
            ${tha("Net Profit","net_profit")}
        </tr></thead>
        <tbody>${rows}</tbody>
    </table>`;

    const pg = document.getElementById("acct-pagination");
    if (pg) {
        pg.innerHTML = totalPages <= 1 ? "" : `
            <button onclick="acctGoPage(${_acctPage-1})" ${_acctPage<=1?"disabled":""}>← Previous</button>
            <span>Page ${_acctPage} of ${totalPages}</span>
            <button onclick="acctGoPage(${_acctPage+1})" ${_acctPage>=totalPages?"disabled":""}>Next →</button>`;
    }
}

function acctSortBy(col) {
    if (_acctSortCol === col) _acctSortAsc = !_acctSortAsc;
    else { _acctSortCol = col; _acctSortAsc = true; }
    _acctPage = 1;
    renderAccountsTable();
}

function acctGoPage(p) { _acctPage = p; renderAccountsTable(); }

// ── Portfolios table (index.html) ─────────────────────────────────────────────

let _allPortfolios = [];
let _portSortCol = "name", _portSortAsc = true;
let _portPage = 1;

function renderPortfoliosTable() {
    const container = document.getElementById("portfolios-table-container");
    const q = (document.getElementById("portfolio-search")?.value || "").toLowerCase().trim();
    let list = _allPortfolios.filter(p =>
        !q || `${p.name||""} ${p.description||""}`.toLowerCase().includes(q));
    if (!list.length) {
        container.innerHTML = '<p class="empty-state">No portfolios yet. Create one above.</p>';
        document.getElementById("port-pagination").innerHTML = "";
        return;
    }
    if (_portSortCol) {
        list = [...list].sort((a, b) => {
            let va = a[_portSortCol], vb = b[_portSortCol];
            if (va == null) va = _portSortAsc ? "\uffff" : "";
            if (vb == null) vb = _portSortAsc ? "\uffff" : "";
            if (typeof va === "number" && typeof vb === "number")
                return _portSortAsc ? va - vb : vb - va;
            return _portSortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
        });
    }
    const thp = (label, c) => {
        const arrow = _portSortCol === c ? (_portSortAsc ? " ↑" : " ↓") : "";
        return `<th class="sortable" onclick="portSortBy('${c}')">${label}${arrow}</th>`;
    };
    const ps = parseInt(document.getElementById("port-page-size")?.value || "25");
    const total = list.length;
    const totalPages = Math.ceil(total / ps) || 1;
    if (_portPage > totalPages) _portPage = 1;
    const pageList = list.slice((_portPage - 1) * ps, _portPage * ps);

    const rows = pageList.map(p => {
        const npPct = val => (
            val != null && p.initial_balance && p.initial_balance > 0
                ? ((val / p.initial_balance) * 100).toFixed(2) + "%"
                : "—"
        );
        const npCls = val => (
            val != null ? (val >= 0 ? "profit-positive" : "profit-negative") : "text-muted"
        );
        return `<tr class="clickable-row" onclick="window.location='/portfolio/${p.id}'">
            <td class="mono">${p.id}</td>
            <td class="editable-cell" data-portfolio-id="${p.id}" data-field="name" onclick="event.stopPropagation();startPortfolioEdit(this)">${p.name || "—"}</td>
            <td class="editable-cell" data-portfolio-id="${p.id}" data-field="description" onclick="event.stopPropagation();startPortfolioEdit(this)">${p.description || "—"}</td>
            <td>${p.strategy_ids.length}</td>
            <td class="editable-cell" data-portfolio-id="${p.id}" data-field="initial_balance" data-type="number" onclick="event.stopPropagation();startPortfolioEdit(this)" style="font-variant-numeric:tabular-nums">${p.initial_balance != null ? fmt(p.initial_balance) : "—"}</td>
            <td class="${npCls(p.backtest_net_profit)}" style="font-variant-numeric:tabular-nums">${npPct(p.backtest_net_profit)}</td>
            <td class="${npCls(p.demo_net_profit)}" style="font-variant-numeric:tabular-nums">${npPct(p.demo_net_profit)}</td>
            <td class="${npCls(p.real_net_profit)}" style="font-variant-numeric:tabular-nums">${npPct(p.real_net_profit)}</td>
            <td><span class="badge ${p.live ? 'badge-live' : 'badge-incubation'}">${p.live ? "Live" : "Incubation"}</span></td>
            <td>
                <button class="btn-edit-row" onclick="event.stopPropagation();openEditPortfolioModalById(${p.id})" title="Edit">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                </button>
                <button class="btn-delete-row" title="Delete" onclick="event.stopPropagation();deletePortfolio(${p.id},'${(p.name||p.id).replace(/'/g,"\\'")}')">✕</button>
            </td>
        </tr>`;
    }).join("");
    container.innerHTML = `<table class="data-table">
        <thead><tr>
            ${thp("ID","id")}${thp("Name","name")}${thp("Description","description")}
            <th>Strategies</th>${thp("Initial Balance","initial_balance")}
            ${thp("NP Backtest %","backtest_net_profit")}${thp("NP Demo %","demo_net_profit")}${thp("NP Real %","real_net_profit")}
            <th>Status</th><th>Actions</th>
        </tr></thead>
        <tbody>${rows}</tbody>
    </table>`;

    const pg = document.getElementById("port-pagination");
    if (pg) {
        pg.innerHTML = totalPages <= 1 ? "" : `
            <button onclick="portGoPage(${_portPage-1})" ${_portPage<=1?"disabled":""}>← Previous</button>
            <span>Page ${_portPage} of ${totalPages}</span>
            <button onclick="portGoPage(${_portPage+1})" ${_portPage>=totalPages?"disabled":""}>Next →</button>`;
    }
}

function portSortBy(col) {
    if (_portSortCol === col) _portSortAsc = !_portSortAsc;
    else { _portSortCol = col; _portSortAsc = true; }
    _portPage = 1;
    renderPortfoliosTable();
}

function portGoPage(p) { _portPage = p; renderPortfoliosTable(); }

// ── Symbols table (index.html) ────────────────────────────────────────────────

let _allSymbols = [];
let _symSortCol = "name", _symSortAsc = true;
let _symPage = 1;

function renderSymbolsTable() {
    const container = document.getElementById("symbols-table-container");
    const q = (document.getElementById("symbols-search")?.value || "").toLowerCase().trim();
    let list = _allSymbols.filter(s =>
        !q || `${s.name} ${s.market||""}`.toLowerCase().includes(q));
    if (!list.length) {
        container.innerHTML = '<p class="empty-state">No symbols registered.</p>';
        document.getElementById("sym-pagination").innerHTML = "";
        return;
    }
    if (_symSortCol) {
        list = [...list].sort((a, b) => {
            let va = a[_symSortCol], vb = b[_symSortCol];
            if (va == null) va = _symSortAsc ? "\uffff" : "";
            if (vb == null) vb = _symSortAsc ? "\uffff" : "";
            if (typeof va === "number" && typeof vb === "number")
                return _symSortAsc ? va - vb : vb - va;
            return _symSortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
        });
    }
    const ths = (label, c) => {
        const arrow = _symSortCol === c ? (_symSortAsc ? " ↑" : " ↓") : "";
        return `<th class="sortable" onclick="symSortBy('${c}')">${label}${arrow}</th>`;
    };
    const ps = parseInt(document.getElementById("sym-page-size")?.value || "25");
    const total = list.length;
    const totalPages = Math.ceil(total / ps) || 1;
    if (_symPage > totalPages) _symPage = 1;
    const pageList = list.slice((_symPage - 1) * ps, _symPage * ps);

    const rows = pageList.map(s => `<tr class="clickable-row" onclick="window.location='/symbol/${encodeURIComponent(s.name)}'">
        <td class="mono">${s.id}</td>
        <td class="editable-cell" data-sym-id="${s.id}" data-field="name" onclick="event.stopPropagation();startSymbolEdit(this)">${s.name}</td>
        <td class="editable-cell" data-sym-id="${s.id}" data-field="market" onclick="event.stopPropagation();startSymbolEdit(this)">${s.market || "—"}</td>
        <td class="editable-cell" data-sym-id="${s.id}" data-field="lot" data-type="number" onclick="event.stopPropagation();startSymbolEdit(this)" style="font-variant-numeric:tabular-nums">${s.lot != null ? s.lot : "—"}</td>
        <td style="text-align:center;font-weight:600">${s.strategies_count || 0}</td>
        <td><button class="btn-delete-row" title="Delete" onclick="event.stopPropagation();deleteSymbol(${s.id},'${s.name.replace(/'/g,"\\'")}')">✕</button></td>
    </tr>`).join("");

    container.innerHTML = `<table class="data-table">
        <thead><tr>${ths("ID","id")}${ths("Name","name")}${ths("Market","market")}${ths("Lot Tick","lot")}<th class="sortable" style="text-align:center" onclick="symSortBy('strategies_count')">Strategies${_symSortCol==="strategies_count"?(_symSortAsc?" ↑":" ↓"):""}</th><th>Actions</th></tr></thead>
        <tbody>${rows}</tbody>
    </table>`;

    const pg = document.getElementById("sym-pagination");
    if (pg) {
        pg.innerHTML = totalPages <= 1 ? "" : `
            <button onclick="symGoPage(${_symPage-1})" ${_symPage<=1?"disabled":""}>← Previous</button>
            <span>Page ${_symPage} of ${totalPages}</span>
            <button onclick="symGoPage(${_symPage+1})" ${_symPage>=totalPages?"disabled":""}>Next →</button>`;
    }
}

function symSortBy(col) {
    if (_symSortCol === col) _symSortAsc = !_symSortAsc;
    else { _symSortCol = col; _symSortAsc = true; }
    _symPage = 1;
    renderSymbolsTable();
}

function symGoPage(p) { _symPage = p; renderSymbolsTable(); }

// ── Create Portfolio modal strategies table ────────────────────────────────────

let _modalStratSort = "id", _modalStratSortAsc = true;
let _modalLastClickedIdx = null;

function modalStratSortBy(col) {
    if (_modalStratSort === col) _modalStratSortAsc = !_modalStratSortAsc;
    else { _modalStratSort = col; _modalStratSortAsc = true; }
    _modalLastClickedIdx = null;
    renderModalStrategiesTable();
}

function handleModalStratRowClick(e, idx) {
    if (e.shiftKey && _modalLastClickedIdx !== null) {
        e.preventDefault();
        const checkboxes = document.querySelectorAll('#new-strategy-list .modal-strat-checkbox');
        const start = Math.min(_modalLastClickedIdx, idx);
        const end = Math.max(_modalLastClickedIdx, idx);
        const allChecked = Array.from(checkboxes).slice(start, end + 1).every(cb => cb.checked);
        checkboxes.forEach((cb, i) => {
            if (i >= start && i <= end) cb.checked = !allChecked;
        });
    }
    _modalLastClickedIdx = idx;
}

function renderModalStrategiesTable() {
    const q = (document.getElementById("new-strategy-search")?.value || "").toLowerCase().trim();
    const checked = new Set([...document.querySelectorAll("#new-strategy-list input:checked")].map(el => el.value));
    let list = _allStrategies.filter(s => !q || `${s.id} ${s.name||""} ${s.symbol||""}`.toLowerCase().includes(q));
    list = [...list].sort((a, b) => {
        let va = a[_modalStratSort], vb = b[_modalStratSort];
        if (va == null) va = _modalStratSortAsc ? "\uffff" : "";
        if (vb == null) vb = _modalStratSortAsc ? "\uffff" : "";
        if (typeof va === "number" && typeof vb === "number") return _modalStratSortAsc ? va - vb : vb - va;
        return _modalStratSortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
    });
    const mth = (label, col) => {
        const arrow = _modalStratSort === col ? (_modalStratSortAsc ? " ↑" : " ↓") : "";
        return `<th class="sortable" onclick="modalStratSortBy('${col}')">${label}${arrow}</th>`;
    };
    const container = document.getElementById("new-strategy-list");
    if (!list.length) {
        container.innerHTML = '<p class="empty-state" style="padding:0.5rem">No strategies found.</p>';
        return;
    }
    const rows = list.map((s, idx) => `<tr onclick="event.stopPropagation();handleModalStratRowClick(event,${idx});this.querySelector('input').click()">
        <td style="width:2rem;text-align:center"><input type="checkbox" class="modal-strat-checkbox" value="${s.id}" ${checked.has(String(s.id)) ? "checked" : ""} onclick="event.stopPropagation()"></td>
        <td class="mono">${s.id}</td>
        <td>${s.name || "—"}</td>
        <td>${s.symbol || "—"}</td>
        <td>${s.timeframe || "—"}</td>
        <td>${s.trade_duration || "—"}</td>
    </tr>`).join("");
    container.innerHTML = `<table class="data-table" style="width:100%">
        <thead><tr>
            <th style="width:2rem;text-align:center"><input type="checkbox" id="modal-strat-select-all" onclick="toggleAllModalStrategies(this)"></th>
            ${mth("ID","id")}${mth("Name","name")}${mth("Symbol","symbol")}
            ${mth("TF","timeframe")}${mth("Type","trade_duration")}
        </tr></thead>
        <tbody>${rows}</tbody>
    </table>`;

    const checkboxes = container.querySelectorAll('.modal-strat-checkbox');
    const selectAllCheckbox = document.getElementById('modal-strat-select-all');
    if (checkboxes.length > 0 && Array.from(checkboxes).every(cb => cb.checked)) {
        selectAllCheckbox.checked = true;
    }
}

function toggleAllModalStrategies(source) {
    const checkboxes = document.querySelectorAll('#new-strategy-list .modal-strat-checkbox');
    checkboxes.forEach(cb => {
        cb.checked = source.checked;
    });
}

// ── Portfolio page charts & tables ──────────────────────────────────────────

let equityChart = null;
let _allEquityPoints = [];
let _equityPeriod = "all";

const STRAT_COLORS = [
    "#60a5fa","#f472b6","#a78bfa","#34d399","#fb923c",
    "#facc15","#38bdf8","#f87171","#4ade80","#e879f9",
];

function filterEquityPoints(pts, period) {
    if (period === "all" || !pts.length) return pts;
    const months = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12 }[period] || 0;
    const cutoff = new Date();
    cutoff.setMonth(cutoff.getMonth() - months);
    return pts.filter(p => new Date(p.timestamp) >= cutoff);
}

function setEquityPeriod(period) {
    _equityPeriod = period;
    document.querySelectorAll(".period-tab[data-ep]").forEach(b =>
        b.classList.toggle("active", b.dataset.ep === period));
    if (_allEquityPoints.length) {
        renderEquityChart(_allEquityPoints, {}, period);
    }
}

function renderEquityChart(totalPoints, strategiesMap, period) {
    const ctx = document.getElementById("equity-chart").getContext("2d");
    const filtered = filterEquityPoints(totalPoints, period);
    if (!filtered.length) {
        ctx.canvas.parentElement.innerHTML = '<p class="empty-state" style="padding:2rem 0">No equity data yet.</p>';
        return;
    }

    const isDark = document.documentElement.getAttribute("data-theme") !== "light";
    const tickColor = isDark ? "#64748b" : "#94a3b8";
    const gridColor = isDark ? "#334155" : "#e2e8f0";
    const legendColor = isDark ? "#94a3b8" : "#475569";

    const cutoff = period !== "all" ? (() => {
        const d = new Date();
        d.setMonth(d.getMonth() - ({"1M":1,"3M":3,"6M":6,"1Y":12}[period]||0));
        return d;
    })() : null;

    const labels = filtered.map(p => {
        const d = new Date(p.timestamp);
        return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });
    });
    const tsSet = new Set(filtered.map(p => p.timestamp));

    const datasets = [{
        label: "Portfolio Total",
        data: filtered.map(p => p.equity),
        segment: { borderColor: c => c.p1.parsed.y >= 0 ? "#10b981" : "#ef4444" },
        borderColor: "#10b981",
        backgroundColor: "rgba(16,185,129,0.06)",
        fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2.5,
        order: 0,
    }];

    let colorIdx = 0;
    for (const [sid, info] of Object.entries(strategiesMap)) {
        const pts = (info.points || []).filter(p => tsSet.has(p.timestamp) || !cutoff || new Date(p.timestamp) >= cutoff);
        const color = STRAT_COLORS[colorIdx++ % STRAT_COLORS.length];
        datasets.push({
            label: info.name || sid,
            data: pts.map(p => p.equity),
            borderColor: color,
            backgroundColor: "transparent",
            fill: false, tension: 0.3, pointRadius: 0, borderWidth: 1.2,
            borderDash: [4, 3],
            hidden: true,
            order: colorIdx,
        });
    }

    if (equityChart) equityChart.destroy();
    equityChart = new Chart(ctx, {
        type: "line",
        data: { labels, datasets },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: {
                    display: false,
                },
                tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${fmt(c.parsed.y)}` } },
                zoom: {
                    zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: "x" },
                    pan:  { enabled: true, mode: "x" },
                },
            },
            scales: {
                x: { ticks: { maxTicksLimit: 12, color: tickColor }, grid: { color: gridColor } },
                y: { ticks: { color: tickColor }, grid: { color: gridColor } },
            },
        },
    });
}

// ── Profit Calendar ────────────────────────────────────────────────────────────

let _dailyData = {};
let _calYear   = new Date().getFullYear();
let _calMonth  = new Date().getMonth();

function shiftMonth(delta) {
    _calMonth += delta;
    if (_calMonth > 11) { _calMonth = 0; _calYear++; }
    if (_calMonth < 0)  { _calMonth = 11; _calYear--; }
    renderCalendar();
}

function renderCalendar() {
    const DAYS = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
    const monthName = new Date(_calYear, _calMonth, 1)
        .toLocaleDateString("en-GB", { month: "long", year: "numeric" });
    document.getElementById("calendar-title").textContent = monthName;

    const firstDay  = new Date(_calYear, _calMonth, 1);
    const totalDays = new Date(_calYear, _calMonth + 1, 0).getDate();
    const startOffset = firstDay.getDay();
    const today = new Date().toISOString().slice(0, 10);

    let html = `<div class="cal-grid">`;
    DAYS.forEach(d => { html += `<div class="cal-header">${d}</div>`; });
    for (let i = 0; i < startOffset; i++) html += `<div class="cal-cell cal-empty"></div>`;
    for (let day = 1; day <= totalDays; day++) {
        const dateStr = `${_calYear}-${String(_calMonth+1).padStart(2,"0")}-${String(day).padStart(2,"0")}`;
        const data = _dailyData[dateStr];
        const dow = new Date(_calYear, _calMonth, day).getDay();
        const isWeekend = dow === 0 || dow === 6;
        const isFuture  = dateStr > today;
        let cls = "cal-cell", valHtml = "";
        if (data !== undefined) {
            const np = data.profit;
            const count = data.count;
            cls += np > 0 ? " cal-profit" : np < 0 ? " cal-loss" : " cal-zero";
            valHtml = `
                <div style="flex:1; display:flex; flex-direction:column; justify-content:center; align-items:center; margin-top:-0.5rem">
                    <span class="cal-value" style="align-self:center; font-size:0.95rem">${np > 0 ? "+" : ""}${fmt(np, 2)}</span>
                    <span style="font-size:0.62rem; font-weight:600; text-transform:uppercase; color:var(--text); margin-top:2px">${count} ${count === 1 ? 'trade' : 'trades'}</span>
                </div>`;
        }
        if (dateStr === today) cls += " cal-today";
        if (isWeekend || isFuture) cls += " cal-inactive";
        html += `<div class="${cls}"><span class="cal-day">${day}</span>${valHtml}</div>`;
    }
    html += `</div>`;

    const prefix = `${_calYear}-${String(_calMonth+1).padStart(2,"0")}`;
    const monthDates = Object.keys(_dailyData).filter(d => d.startsWith(prefix));
    const monthTotal = monthDates.reduce((s, d) => s + _dailyData[d].profit, 0);
    const winDays = monthDates.filter(d => _dailyData[d].profit > 0).length;
    const lossDays = monthDates.filter(d => _dailyData[d].profit < 0).length;
    const totalCls   = monthTotal >= 0 ? "profit-positive" : "profit-negative";
    html += `<div class="cal-summary">
        <span>Month total: <strong class="${totalCls}">${monthTotal >= 0 ? "+" : ""}${fmt(monthTotal, 2)}</strong></span>
        <span class="text-muted">·</span>
        <span class="profit-positive">${winDays} winning days</span>
        <span class="text-muted">·</span>
        <span class="profit-negative">${lossDays} losing days</span>
    </div>`;
    document.getElementById("calendar-container").innerHTML = html;
}

// ── Portfolio strategies table ─────────────────────────────────────────────────

let _portStratSortCol = "net_profit";
let _portStratSortAsc = false;
let _portStratPage = 1;
let _portStratList = [];

function renderPortfolioStrategies() {
    const container = document.getElementById("strategies-container");
    const ps = parseInt(document.getElementById("port-strat-page-size")?.value || "25");
    const q = (document.getElementById("port-strat-search")?.value || "").toLowerCase().trim();
    let list = _portStratList.filter(s => !q || `${s.id} ${s.name||""} ${s.symbol||""}`.toLowerCase().includes(q));

    const _retdd = s => {
        const np = s.net_profit, dd = s.max_drawdown, ib = s.initial_balance;
        if (np == null || dd == null || dd <= 0 || ib == null || ib <= 0) return null;
        const val = np / (dd * ib);
        return val;
    };

    if (_portStratSortCol) {
        list.sort((a, b) => {
            let va, vb;
            if (_portStratSortCol === "retdd") {
                va = _retdd(a);
                vb = _retdd(b);
            } else if (_portStratSortCol === "max_drawdown") {
                // Sort by absolute drawdown amount
                va = a.max_drawdown != null && a.initial_balance != null ? a.max_drawdown * a.initial_balance : null;
                vb = b.max_drawdown != null && b.initial_balance != null ? b.max_drawdown * b.initial_balance : null;
            } else {
                va = a[_portStratSortCol];
                vb = b[_portStratSortCol];
            }
            if (va == null) va = _portStratSortAsc ? Infinity : -Infinity;
            if (vb == null) vb = _portStratSortAsc ? Infinity : -Infinity;
            return _portStratSortAsc ? (va > vb ? 1 : -1) : (va < vb ? 1 : -1);
        });
    }

    const total = list.length;
    const totalPages = Math.ceil(total / ps);
    if (_portStratPage > totalPages) _portStratPage = 1;
    const pageList = list.slice((_portStratPage - 1) * ps, _portStratPage * ps);

    const th = (label, c) => {
        const arrow = _portStratSortCol === c ? (_portStratSortAsc ? " ↑" : " ↓") : "";
        return `<th class="sortable" onclick="portStratSortBy('${c}')">${label}${arrow}</th>`;
    };

    const rows = pageList.map(s => {
        const np = s.net_profit;
        const npCls = np == null ? "" : (np >= 0 ? "profit-positive" : "profit-negative");
        const dd = s.max_drawdown;
        const ib = s.initial_balance;
        const ddAmount = dd != null && ib != null ? dd * ib : null;
        const ddStr = ddAmount != null ? fmt(ddAmount) : "—";
        const ddCls = dd != null && dd > 0 ? "profit-negative" : "";
        const retDDVal = _retdd(s);
        const retDD = retDDVal != null ? retDDVal.toFixed(2) : "—";
        const retDDCls = retDDVal == null ? "" : retDDVal >= 0 ? "profit-positive" : "profit-negative";
        return `<tr class="clickable-row" onclick="window.location='/strategy/${s.id}'">
            <td class="mono">${s.id}</td>
            <td>${s.name || "—"}</td>
            <td>${s.symbol || "—"}</td>
            <td>${s.timeframe || "—"}</td>
            <td>${s.trade_duration || "—"}</td>
            <td>${s.trades_count != null ? s.trades_count : "—"}</td>
            <td class="${npCls}" style="font-variant-numeric:tabular-nums">${np != null ? fmt(np, 2) : "—"}</td>
            <td class="${ddCls}" style="font-variant-numeric:tabular-nums">${ddStr}</td>
            <td class="${retDDCls}" style="font-variant-numeric:tabular-nums">${retDD}</td>
        </tr>`;
    }).join("");

    container.innerHTML = `<table class="data-table">
        <thead><tr>
            ${th("ID","id")}${th("Name","name")}${th("Symbol","symbol")}
            ${th("TF","timeframe")}${th("Type","trade_duration")}
            ${th("Trades","trades_count")}${th("Net Profit","net_profit")}
            ${th("Drawdown","max_drawdown")}${th("Ret/DD","retdd")}
        </tr></thead>
        <tbody>${rows}</tbody>
    </table>`;

    const pg = document.getElementById("port-strat-pagination");
    if (totalPages <= 1) { pg.innerHTML = ""; return; }
    pg.innerHTML = `
        <button onclick="portStratGoPage(${_portStratPage - 1})" ${_portStratPage <= 1 ? "disabled" : ""}>← Previous</button>
        <span>Page ${_portStratPage} of ${totalPages}</span>
        <button onclick="portStratGoPage(${_portStratPage + 1})" ${_portStratPage >= totalPages ? "disabled" : ""}>Next →</button>`;
}

function portStratSortBy(col) {
    if (_portStratSortCol === col) _portStratSortAsc = !_portStratSortAsc;
    else { _portStratSortCol = col; _portStratSortAsc = col !== "net_profit"; }
    _portStratPage = 1;
    renderPortfolioStrategies();
}

function portStratGoPage(p) { _portStratPage = p; renderPortfolioStrategies(); }

function exportPortfolioStrategiesCSV() {
    if (!_portStratList.length) return;
    const headers = ["ID","Name","Symbol","TF","Type","Trades","Net Profit","Drawdown","Ret/DD"];
    const rows = _portStratList.map(s => {
        const dd = s.max_drawdown;
        const ib = s.initial_balance;
        const ddAmount = dd != null && ib != null ? dd * ib : null;
        const ddStr = ddAmount != null ? ddAmount.toFixed(2) : "";
        let retDD = "";
        if (s.net_profit != null && dd != null && dd > 0 && ib != null && ib > 0) {
            const val = s.net_profit / (dd * ib);
            retDD = val.toFixed(2);
        }
        return [s.id, s.name||"", s.symbol||"", s.timeframe||"", s.trade_duration||"", s.trades_count??"",(s.net_profit??""),(ddStr),(retDD)].join(",");
    });
    const csv = [headers.join(","), ...rows].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], {type:"text/csv"}));
    a.download = `portfolio_${PORTFOLIO_ID}_strategies.csv`;
    a.click();
}

// ── Edit strategies table (portfolio.html) ────────────────────────────────────

let _editStratSort = "id", _editStratSortAsc = true;

function editStratSortBy(col) {
    if (_editStratSort === col) _editStratSortAsc = !_editStratSortAsc;
    else { _editStratSort = col; _editStratSortAsc = true; }
    renderEditStrategiesTable();
}

function renderEditStrategiesTable() {
    const container = document.getElementById("edit-strategy-list");
    const selectedInputs = [...document.querySelectorAll("#edit-strategy-list input:checked")].map(el => el.value);
    const portfolioStrategyIds = typeof _portfolio !== "undefined" && _portfolio && Array.isArray(_portfolio.strategy_ids)
        ? _portfolio.strategy_ids
        : [];
    const selected = new Set(
        selectedInputs.length ? selectedInputs : portfolioStrategyIds
    );
    const col = _editStratSort;
    const asc = _editStratSortAsc;
    const sorted = [..._allStrategies].sort((a, b) => {
        let va = a[col] ?? "", vb = b[col] ?? "";
        if (typeof va === "number" && typeof vb === "number") return asc ? va - vb : vb - va;
        return asc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
    });
    const arrow = c => _editStratSort === c ? (_editStratSortAsc ? " ↑" : " ↓") : "";
    const th = (label, c) =>
        `<th class="sortable" style="padding:0.3rem 0.5rem;white-space:nowrap;cursor:pointer" onclick="editStratSortBy('${c}')">${label}${arrow(c)}</th>`;
    const rows = sorted.map(s => {
        const chk = selected.has(s.id) ? "checked" : "";
        const np = s.net_profit;
        const npCls = np == null ? "" : np >= 0 ? "profit-positive" : "profit-negative";
        return `<tr style="cursor:pointer" onclick="this.querySelector('input').click()">
            <td style="padding:0.25rem 0.5rem;text-align:center"><input type="checkbox" value="${s.id}" ${chk} onclick="event.stopPropagation()"></td>
            <td class="mono" style="padding:0.25rem 0.5rem">${s.id}</td>
            <td style="padding:0.25rem 0.5rem">${s.name || "—"}</td>
            <td style="padding:0.25rem 0.5rem">${s.symbol || "—"}</td>
            <td style="padding:0.25rem 0.5rem">${s.timeframe || "—"}</td>
            <td style="padding:0.25rem 0.5rem">${s.trade_duration || "—"}</td>
            <td class="${npCls}" style="padding:0.25rem 0.5rem;font-variant-numeric:tabular-nums">${np != null ? fmt(np, 2) : "—"}</td>
        </tr>`;
    }).join("");
    container.innerHTML = `<table class="data-table" style="width:100%;font-size:0.82rem">
        <thead><tr>
            <th style="padding:0.3rem 0.5rem;width:32px"></th>
            ${th("ID","id")}${th("Name","name")}${th("Symbol","symbol")}
            ${th("TF","timeframe")}${th("Type","trade_duration")}${th("Net Profit","net_profit")}
        </tr></thead>
        <tbody>${rows}</tbody>
    </table>`;
}
