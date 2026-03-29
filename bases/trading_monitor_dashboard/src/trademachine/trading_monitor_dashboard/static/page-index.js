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

/* ── Filtering shortcuts ── */
function filterPortfolioTable() { renderPortfoliosTable(); }
function filterAccountsTable()  { renderAccountsTable(); }
function filterModalStrategies() { renderModalStrategiesTable(); }

/* ── Modals ── */
async function openCreateModal() {
    document.getElementById("new-name").value = "";
    document.getElementById("new-description").value = "";
    document.getElementById("new-initial-balance").value = "";
    document.getElementById("new-strategy-search").value = "";
    document.getElementById("new-live").checked = false;
    document.getElementById("new-real").checked = false;
    document.getElementById("create-status").textContent = "";
    document.getElementById("modal-overlay").style.display = "flex";
    if (!_allStrategies.length) {
        const res = await fetch("/api/strategies");
        _allStrategies = await res.json();
    }
    renderModalStrategiesTable();
}

function closeCreateModal() { document.getElementById("modal-overlay").style.display = "none"; }
function closeModal(e) { if (e.target.id === "modal-overlay") closeCreateModal(); }

function openAddSymbolModal() {
    _editingSymbolId = null;
    document.getElementById("symbol-modal-title").textContent = "Add Symbol";
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
function startEdit(td) {
    const stratId = td.dataset.stratId;
    const field = td.dataset.field;
    const strat = _allStrategies.find(s => s.id === stratId);
    const currentValue = strat ? (strat[field] || "") : "";
    makeEditable(td, stratId, field, currentValue);
}

function startStratAccountEdit(td) {
    const accountId = td.dataset.accountId;
    if (!accountId) return;
    const original = td.textContent.trim();
    const currentValue = original === "—" ? "" : original;
    const originalHTML = td.innerHTML;
    td.innerHTML = `<input class="inline-edit-input" type="text" value="${currentValue.replace(/"/g, "&quot;")}">`;
    const input = td.querySelector("input");
    input.focus();
    input.select();
    let done = false;
    const save = async () => {
        if (done) return;
        done = true;
        const newVal = input.value.trim() || null;
        if (newVal === (currentValue || null)) { td.innerHTML = originalHTML; return; }
        try {
            await patchAccount(accountId, { account_type: newVal });
            await loadStrategies(true);
        } catch (e) {
            td.innerHTML = originalHTML;
        }
    };
    input.addEventListener("blur", save);
    input.addEventListener("keydown", e => {
        if (e.key === "Enter") { e.preventDefault(); input.blur(); }
        if (e.key === "Escape") { done = true; td.innerHTML = originalHTML; }
    });
}

function makeEditable(td, stratId, field, currentValue) {
    const original = td.innerHTML;
    td.innerHTML = `<input class="inline-edit-input" type="text" value="${currentValue.replace(/"/g, "&quot;")}">`;
    const input = td.querySelector("input");
    input.focus();
    input.select();
    let done = false;
    const save = async () => {
        if (done) return;
        done = true;
        const newVal = input.value.trim() || null;
        if (newVal === (currentValue || null)) { td.innerHTML = original; return; }
        try {
            await patchStrategy(stratId, { [field]: newVal });
            await loadStrategies(true);
        } catch (e) {
            td.innerHTML = original;
        }
    };
    input.addEventListener("blur", save);
    input.addEventListener("keydown", e => {
        if (e.key === "Enter") { e.preventDefault(); input.blur(); }
        if (e.key === "Escape") { done = true; td.innerHTML = original; }
    });
}

function startPortfolioEdit(td) {
    const portfolioId = td.dataset.portfolioId;
    const field = td.dataset.field;
    const isNumber = td.dataset.type === "number";
    const original = td.textContent.trim();
    const currentValue = original === "—" ? "" : original;
    const originalHTML = td.innerHTML;
    const inputType = isNumber ? "number" : "text";
    const rawValue = isNumber ? currentValue.replace(/[^0-9.\-]/g, "") : currentValue;
    td.innerHTML = `<input class="inline-edit-input" type="${inputType}" step="any" value="${rawValue.replace(/"/g, "&quot;")}">`;
    const input = td.querySelector("input");
    input.focus();
    input.select();
    let done = false;
    const save = async () => {
        if (done) return;
        done = true;
        let newVal;
        if (isNumber) {
            const parsed = parseFloat(input.value);
            newVal = isNaN(parsed) ? null : parsed;
            if (newVal === (rawValue ? parseFloat(rawValue) : null)) { td.innerHTML = originalHTML; return; }
        } else {
            newVal = input.value.trim() || null;
            if (newVal === (currentValue || null)) { td.innerHTML = originalHTML; return; }
        }
        try {
            await patchPortfolio(portfolioId, { [field]: newVal });
            await loadPortfolios();
        } catch (e) {
            td.innerHTML = originalHTML;
        }
    };
    input.addEventListener("blur", save);
    input.addEventListener("keydown", e => {
        if (e.key === "Enter") { e.preventDefault(); input.blur(); }
        if (e.key === "Escape") { done = true; td.innerHTML = originalHTML; }
    });
}

function startAccountEdit(td) {
    const accountId = td.dataset.accountId;
    const field = td.dataset.field;
    const original = td.textContent.trim();
    const currentValue = original === "—" ? "" : original;
    const originalHTML = td.innerHTML;
    td.innerHTML = `<input class="inline-edit-input" type="text" value="${currentValue.replace(/"/g, "&quot;")}">`;
    const input = td.querySelector("input");
    input.focus();
    input.select();
    let done = false;
    const save = async () => {
        if (done) return;
        done = true;
        const newVal = input.value.trim() || null;
        if (newVal === (currentValue || null)) { td.innerHTML = originalHTML; return; }
        try {
            await patchAccount(accountId, { [field]: newVal });
            await loadAccounts();
        } catch (e) {
            td.innerHTML = originalHTML;
        }
    };
    input.addEventListener("blur", save);
    input.addEventListener("keydown", e => {
        if (e.key === "Enter") { e.preventDefault(); input.blur(); }
        if (e.key === "Escape") { done = true; td.innerHTML = originalHTML; }
    });
}

function startSymbolEdit(td) {
    const symId = td.dataset.symId;
    const field = td.dataset.field;
    const isNumber = td.dataset.type === "number";
    const original = td.textContent.trim();
    const currentValue = original === "—" ? "" : original;
    const originalHTML = td.innerHTML;

    if (field === "market") {
        const options = ["", "Forex", "Crypto", "Futures", "Indices", "Stocks", "Commodities", "Other"];
        const selectHtml = `<select class="inline-edit-input">
            ${options.map(opt => `<option value="${opt}" ${opt === currentValue ? "selected" : ""}>${opt || "— Select —"}</option>`).join("")}
        </select>`;
        td.innerHTML = selectHtml;
    } else {
        const inputType = isNumber ? "number" : "text";
        const rawValue = isNumber ? currentValue.replace(/[^0-9.\-]/g, "") : currentValue;
        td.innerHTML = `<input class="inline-edit-input" type="${inputType}" step="any" value="${rawValue.replace(/"/g, "&quot;")}">`;
    }

    const input = td.querySelector("input, select");
    input.focus();
    if (input.tagName === "INPUT") {
        input.select();
    }

    let done = false;
    const save = async () => {
        if (done) return;
        done = true;
        let newVal;

        if (field === "market") {
            newVal = input.value || null;
            if (newVal === (currentValue || null)) { td.innerHTML = originalHTML; return; }
        } else if (isNumber) {
            const parsed = parseFloat(input.value);
            newVal = isNaN(parsed) ? null : parsed;
            const rawValue = isNumber ? currentValue.replace(/[^0-9.\-]/g, "") : currentValue;
            const oldVal = rawValue ? parseFloat(rawValue) : null;
            if (newVal === oldVal) { td.innerHTML = originalHTML; return; }
        } else {
            newVal = input.value.trim() || null;
            if (newVal === (currentValue || null)) { td.innerHTML = originalHTML; return; }
        }

        try {
            await fetchJson(`/api/symbols/${symId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ [field]: newVal }),
            });
            await loadSymbols(true);
        } catch(e) {
            console.error("Save failed:", e);
            td.innerHTML = originalHTML;
        }
    };

    if (input.tagName === "SELECT") {
        input.addEventListener("change", save);
        input.addEventListener("blur", save);
    } else {
        input.addEventListener("blur", save);
        input.addEventListener("keydown", e => {
            if (e.key === "Enter") {
                e.preventDefault();
                save();
            }
            if (e.key === "Escape") {
                done = true;
                td.innerHTML = originalHTML;
            }
        });
    }
}

async function toggleStratLive(stratId, currentLive) {
    try {
        await patchStrategy(stratId, { live: !currentLive });
        await loadStrategies(true);
    } catch (e) {}
}

/* ── CSV Export ── */
function exportTableCSV(type) {
    let headers, rows;
    if (type === "strategies") {
        headers = ["ID","Name","Symbol","TF","Duration","Acct Type","NP Backtest","NP Demo","NP Real","Live"];
        rows = _allStrategies.map(s => [
            s.id, s.name||"", s.symbol||"", s.timeframe||"", s.trade_duration||"",
            s.account_type||"", s.backtest_net_profit??"",(s.real_account?"":(s.net_profit??"")),
            (s.real_account?(s.net_profit??""):""), s.live?"Live":"Incubation"
        ]);
    } else if (type === "portfolios") {
        headers = ["ID","Name","Description","Strategies","Initial Balance","Net Profit","Drawdown %","Status","Account Type"];
        rows = _allPortfolios.map(p => [
            p.id, p.name||"", p.description||"", p.strategy_ids.length,
            p.initial_balance??"", p.net_profit??"",
            p.max_drawdown != null ? (p.max_drawdown*100).toFixed(1) : "",
            p.live?"Live":"Incubation", p.real_account?"Real":"Demo"
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
