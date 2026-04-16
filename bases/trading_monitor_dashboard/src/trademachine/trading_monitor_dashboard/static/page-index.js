/* ── index.html page-specific logic ─────────────────────────────────────────── */

let _editingSymbolId = null;

/* ── Tab switching ── */
function showTab(tab) {
    const tabs = ["strategies","portfolios","accounts","symbols"];
    tabs.forEach(t => {
        document.getElementById(`tab-${t}`).style.display = t === tab ? "" : "none";
    });
    document.querySelectorAll(".section-tab").forEach((btn, i) => {
        btn.classList.toggle("active", tabs[i] === tab);
    });
    if (tab === "accounts") loadAccounts();
    if (tab === "symbols") loadSymbols();
}

function setPortfolioMetricMode(mode) {
    window._portfolioMetricMode = mode;
    document.querySelectorAll(".period-tab").forEach(btn => {
        if (btn.dataset.pm === mode) {
            btn.classList.add("active");
        } else {
            btn.classList.remove("active");
        }
    });
    loadPortfolios();
}

/* ── Filtering shortcuts ── */
function filterPortfolioTable() { renderPortfoliosTable(); }
function filterAccountsTable()  { renderAccountsTable(); }
function filterModalStrategies() { _modalLastClickedIdx = null; renderModalStrategiesTable(); }

/* ── Modals ── */
let _editingPortfolioId = null;

async function openCreateModal() {
    _editingPortfolioId = null;
    document.getElementById("portfolio-modal-title").textContent = "New Portfolio";
    document.getElementById("portfolio-modal-submit-btn").textContent = "Create Portfolio";
    document.getElementById("new-name").value = "";
    document.getElementById("new-description").value = "";
    document.getElementById("new-initial-balance").value = "";
    document.getElementById("new-strategy-search").value = "";
    _modalLastClickedIdx = null;
    document.getElementById("create-status").textContent = "";
    document.getElementById("modal-overlay").style.display = "flex";
    if (!_allStrategies.length) {
        const res = await fetch("/api/strategies");
        _allStrategies = await res.json();
    }
    renderModalStrategiesTable();
}

async function openEditPortfolioModal(portfolio) {
    _editingPortfolioId = portfolio.id;
    document.getElementById("portfolio-modal-title").textContent = "Edit Portfolio";
    document.getElementById("portfolio-modal-submit-btn").textContent = "Save Changes";
    document.getElementById("new-name").value = portfolio.name || "";
    document.getElementById("new-description").value = portfolio.description || "";
    document.getElementById("new-initial-balance").value = portfolio.initial_balance != null ? portfolio.initial_balance : "";
    document.getElementById("new-strategy-search").value = "";
    _modalLastClickedIdx = null;
    document.getElementById("create-status").textContent = "";
    document.getElementById("modal-overlay").style.display = "flex";
    if (!_allStrategies.length) {
        const res = await fetch("/api/strategies");
        _allStrategies = await res.json();
    }
    renderModalStrategiesTable();
    // Pre-check the portfolio's strategies after render
    const checked = new Set(portfolio.strategy_ids || []);
    setTimeout(() => {
        document.querySelectorAll('#new-strategy-list .modal-strat-checkbox').forEach(cb => {
            cb.checked = checked.has(cb.value);
        });
    }, 0);
}

function openEditPortfolioModalById(id) {
    const portfolio = _allPortfolios.find(p => String(p.id) === String(id));
    if (portfolio) {
        openEditPortfolioModal(portfolio);
    }
}

function closeCreateModal() { document.getElementById("modal-overlay").style.display = "none"; _editingPortfolioId = null; }
function closeModal(e) { if (e.target.id === "modal-overlay") closeCreateModal(); }

function openAddSymbolModal() {
    _editingSymbolId = null;
    document.getElementById("symbol-modal-title").textContent = "New Symbol";
    document.getElementById("sym-name").value = "";
    document.getElementById("sym-market").value = "";
    document.getElementById("sym-lot").value = "";
    document.getElementById("sym-status").textContent = "";
    document.getElementById("modal-symbol-overlay").style.display = "flex";
}

function closeSymbolModal() {
    document.getElementById("modal-symbol-overlay").style.display = "none";
    _editingSymbolId = null;
}

/* ── Inline editing ── */

/**
 * Generic inline-edit helper. Replaces a cell with an input/select,
 * wires blur/enter/escape, and calls saveFn on commit.
 *
 * @param {HTMLElement} td
 * @param {object}      opts
 * @param {*}           opts.currentValue  - Normalised old value (for equality check)
 * @param {Function}    opts.renderInput   - (td) => void — inject input/select into td
 * @param {Function}    opts.parseInput    - (inputEl) => newVal
 * @param {Function}    opts.saveFn        - (newVal) => Promise
 * @param {Function}    opts.reloadFn      - () => Promise
 */
function startInlineEdit(td, { currentValue, renderInput, parseInput, saveFn, reloadFn }) {
    if (!td.isConnected) return;
    const originalHTML = td.innerHTML;

    renderInput(td);
    const input = td.querySelector("input, select");
    input.focus();
    if (input.select && input.tagName === "INPUT") input.select();

    let done = false;
    const restore = () => { if (td.isConnected) td.innerHTML = originalHTML; };

    const save = async () => {
        if (done) return;
        done = true;
        await new Promise(r => setTimeout(r, 0));
        if (!td.isConnected) return;
        const newVal = parseInput(input);
        if (newVal === currentValue) { restore(); return; }
        try {
            await saveFn(newVal);
            await reloadFn();
        } catch (e) {
            restore();
        }
    };

    if (input.tagName === "SELECT") {
        input.addEventListener("change", save);
    }
    input.addEventListener("blur", save);
    input.addEventListener("keydown", e => {
        if (e.key === "Enter") { e.preventDefault(); save(); }
        if (e.key === "Escape") { done = true; restore(); }
    });
}

function _textInput(td, value) {
    td.innerHTML = `<input class="inline-edit-input" type="text" value="${String(value).replace(/"/g, "&quot;")}">`;
}

function _numberInput(td, value) {
    td.innerHTML = `<input class="inline-edit-input" type="number" step="any" value="${String(value ?? "")}">`;
}

function _parseText(input) { return input.value.trim() || null; }

function _parseNumber(input) {
    const trimmed = input.value.trim();
    const parsed = parseFloat(trimmed);
    return trimmed === "" || Number.isNaN(parsed) ? null : parsed;
}

function _cellValue(td) {
    const raw = td.textContent.trim();
    return raw === "—" ? "" : raw;
}

function startEdit(td) {
    const stratId = td.dataset.stratId;
    const field = td.dataset.field;
    const isNumber = td.dataset.type === "number";
    const strat = _allStrategies.find(s => s.id === stratId);
    const raw = strat ? (strat[field] ?? "") : "";
    const currentValue = isNumber
        ? (raw === "" || raw == null ? null : parseFloat(raw))
        : (raw || null);

    startInlineEdit(td, {
        currentValue,
        renderInput: isNumber ? (el) => _numberInput(el, raw) : (el) => _textInput(el, raw),
        parseInput: isNumber ? _parseNumber : _parseText,
        saveFn: (val) => patchStrategy(stratId, { [field]: val }),
        reloadFn: () => loadStrategies(true),
    });
}

function startStratAccountEdit(td) {
    const accountId = td.dataset.accountId;
    if (!accountId) return;
    const currentValue = _cellValue(td) || null;

    startInlineEdit(td, {
        currentValue,
        renderInput: (el) => _textInput(el, _cellValue(td)),
        parseInput: _parseText,
        saveFn: (val) => patchAccount(accountId, { account_type: val }),
        reloadFn: () => loadStrategies(true),
    });
}

function startPortfolioEdit(td) {
    const portfolioId = td.dataset.portfolioId;
    const field = td.dataset.field;
    const isNumber = td.dataset.type === "number";
    const cellText = _cellValue(td);
    const rawValue = isNumber ? cellText.replace(/[^0-9.\-]/g, "") : cellText;
    const currentValue = isNumber
        ? (rawValue ? parseFloat(rawValue) : null)
        : (cellText || null);

    startInlineEdit(td, {
        currentValue,
        renderInput: isNumber ? (el) => _numberInput(el, rawValue) : (el) => _textInput(el, cellText),
        parseInput: isNumber ? _parseNumber : _parseText,
        saveFn: (val) => patchPortfolio(portfolioId, { [field]: val }),
        reloadFn: () => loadPortfolios(),
    });
}

function startAccountEdit(td) {
    const accountId = td.dataset.accountId;
    const field = td.dataset.field;
    const currentValue = _cellValue(td) || null;

    startInlineEdit(td, {
        currentValue,
        renderInput: (el) => _textInput(el, _cellValue(td)),
        parseInput: _parseText,
        saveFn: (val) => patchAccount(accountId, { [field]: val }),
        reloadFn: () => loadAccounts(),
    });
}

function startSymbolEdit(td) {
    const symId = td.dataset.symId;
    const field = td.dataset.field;
    const isNumber = td.dataset.type === "number";
    const cellText = _cellValue(td);
    const rawValue = isNumber ? cellText.replace(/[^0-9.\-]/g, "") : cellText;

    const isMarket = field === "market";
    const currentValue = isMarket
        ? (cellText || null)
        : isNumber ? (rawValue ? parseFloat(rawValue) : null) : (cellText || null);

    const renderMarketSelect = (el) => {
        const options = ["", "Forex", "Crypto", "Futures", "Indices", "Stocks", "Commodities", "Other"];
        el.innerHTML = `<select class="inline-edit-input">
            ${options.map(opt => `<option value="${opt}" ${opt === cellText ? "selected" : ""}>${opt || "— Select —"}</option>`).join("")}
        </select>`;
    };

    const renderFn = isMarket
        ? renderMarketSelect
        : isNumber ? (el) => _numberInput(el, rawValue) : (el) => _textInput(el, cellText);
    const parseFn = isMarket
        ? (input) => input.value || null
        : isNumber ? _parseNumber : _parseText;

    startInlineEdit(td, {
        currentValue,
        renderInput: renderFn,
        parseInput: parseFn,
        saveFn: (val) => fetchJson(`/api/symbols/${symId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ [field]: val }),
        }),
        reloadFn: () => loadSymbols(true),
    });
}

async function toggleStratLive(stratId, currentLive) {
    try {
        await patchStrategy(stratId, { live: !currentLive });
        await loadStrategies(true);
    } catch (e) {}
}

async function togglePortfolioLive(portfolioId, currentLive) {
    const nextLive = !currentLive;
    const portfolio = _allPortfolios.find(p => String(p.id) === String(portfolioId));
    const previousLive = portfolio ? portfolio.live : currentLive;

    if (portfolio) {
        portfolio.live = nextLive;
        renderPortfoliosTable();
    }

    try {
        await patchPortfolio(portfolioId, { live: nextLive });
        loadPortfolios();
    } catch (e) {
        if (portfolio) {
            portfolio.live = previousLive;
            renderPortfoliosTable();
        }
    }
}

async function toggleAccountType(accountId, currentType) {
    const newType = currentType?.toLowerCase().includes("real") ? "Demo" : "Real";
    try {
        await patchAccount(accountId, { account_type: newType });
        await loadAccounts();
    } catch (e) {}
}

/* ── CSV Export ── */
function exportTableCSV(type) {
    let headers, rows;
    if (type === "strategies") {
        headers = ["ID","Name","Symbol","TF","Style","Duration","NP Backtest","NP Demo","NP Real","Live"];
        rows = _allStrategies.map(s => [
            s.id, s.name||"", s.symbol||"", s.timeframe||"", s.operational_style||"", s.trade_duration||"",
            s.backtest_net_profit??"",(s.real_account?"":(s.net_profit??"")),
            (s.real_account?(s.net_profit??""):""), s.live?"Live":"Incubation"
        ]);
    } else if (type === "portfolios") {
        headers = ["ID","Name","Description","Strategies","Initial Balance","NP Backtest","NP Demo","NP Real","Status"];
        rows = _allPortfolios.map(p => [
            p.id, p.name||"", p.description||"", p.strategy_ids.length,
            p.initial_balance??"", p.backtest_net_profit??"", p.demo_net_profit??"",
            p.real_net_profit??"", p.live?"Live":"Incubation"
        ]);
    } else if (type === "accounts") {
        headers = ["ID","Name","Broker","Type","Currency","Balance","Free Margin"];
        rows = _allAccounts.map(a => [
            a.id, a.name||"", a.broker||"", a.account_type||"", a.currency||"",
            a.balance??"", a.free_margin??""
        ]);
    } else if (type === "symbols") {
        headers = ["ID","Name","Market","Lot"];
        rows = _allSymbols.map(s => [s.id, s.name, s.market||"", s.lot??""]);
    } else return;

    const escape = v => `"${String(v).replace(/"/g,'""')}"`;
    const csv = [headers.map(escape).join(","), ...rows.map(r => r.map(escape).join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${type}.csv`; a.click();
    URL.revokeObjectURL(url);
}

/* ── WebSocket event handling ── */
window.addEventListener("ws-event", function(e) {
    const { topic } = e.detail;
    if (topic === "DEAL" || topic === "EQUITY" || topic === "ACCOUNT" || topic === "BACKTEST_END") {
        loadSummary(true);
        loadStrategies(true);
        loadPortfolios();
        const acctTabVisible = document.getElementById("tab-accounts")?.style.display !== "none";
        if (acctTabVisible && (topic === "ACCOUNT" || topic === "DEAL")) loadAccounts();
    }
});

window.addEventListener("tm-theme-change", function() {
    loadSummary();
});

/* ── Page init ── */
loadSummary();
loadStrategies();
loadPortfolios();
