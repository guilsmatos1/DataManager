let _symbolStrategies = [];
let _symbolSortCol = "id";
let _symbolSortAsc = true;
let _symbolStratPage = 1;

function symbolSortBy(col) {
    ({ col: _symbolSortCol, asc: _symbolSortAsc } = toggleSort(_symbolSortCol, _symbolSortAsc, col));
    _symbolStratPage = 1;
    renderSymbolStrategies();
}

function renderSymbolStrategies() {
    const q = (document.getElementById("symbol-strat-search")?.value || "").toLowerCase().trim();
    const list = _symbolStrategies.filter((s) =>
        !q || `${s.id} ${s.name || ""} ${s.symbol || ""} ${s.account_name || s.account_id || ""}`.toLowerCase().includes(q)
    );

    const thead = document.getElementById("symbol-strategies-head");
    if (thead) {
        const th = (label, col) => sortTh(label, col, _symbolSortCol, _symbolSortAsc, "symbolSortBy");
        thead.innerHTML = `<tr>
            ${th("ID", "id")}${th("Name", "name")}${th("Symbol", "symbol")}
            ${th("Account", "account_name")}${th("Status", "live")}
        </tr>`;
    }

    const sorted = sortList(list, _symbolSortCol, _symbolSortAsc);

    const ps = parseInt(document.getElementById("symbol-strat-page-size")?.value || "25");
    const totalPages = Math.max(1, Math.ceil(sorted.length / ps));
    if (_symbolStratPage > totalPages) _symbolStratPage = 1;
    const pageList = sorted.slice((_symbolStratPage - 1) * ps, _symbolStratPage * ps);

    const tbody = document.getElementById("symbol-strategies-body");
    tbody.innerHTML = "";
    pageList.forEach((s) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td><a href="/strategy/${s.id}" style="color:var(--accent)">${s.id}</a></td>
            <td>${s.name || "—"}</td>
            <td>${s.symbol || "—"}</td>
            <td>${s.account_name || s.account_id || "—"}</td>
            <td><span class="badge ${s.live ? "badge-live" : "badge-incubation"}">${s.live ? "Live" : "Incubation"}</span></td>
        `;
        tbody.appendChild(tr);
    });

    renderPagination("symbol-strat-pagination", _symbolStratPage, totalPages, (p) => {
        _symbolStratPage = p;
        renderSymbolStrategies();
    });
}

async function loadSymbolPage() {
    try {
        const [symbols, strategies] = await Promise.all([
            fetchJson("/api/symbols"),
            fetchJson("/api/strategies"),
        ]);

        const symbol = symbols.find((s) => String(s.name) === String(SYMBOL_NAME));
        if (!symbol) {
            document.getElementById("symbol-empty").style.display = "block";
            return;
        }

        const filteredStrategies = strategies.filter((s) => String(s.symbol || "") === String(SYMBOL_NAME));
        _symbolStrategies = filteredStrategies;

        document.getElementById("symbol-title").textContent = symbol.name;
        document.getElementById("symbol-market").textContent = symbol.market || "—";
        document.getElementById("symbol-lot").textContent = symbol.lot != null ? symbol.lot : "—";
        document.getElementById("symbol-strategy-count").textContent = filteredStrategies.length;
        document.getElementById("symbol-summary").style.display = "";

        renderSymbolStrategies();

        document.getElementById("symbol-strategies-badge").textContent = filteredStrategies.length;
        document.getElementById("symbol-strategies-card").style.display = "";
    } catch (e) {
        document.getElementById("symbol-empty").style.display = "block";
        document.getElementById("symbol-empty").innerHTML = `<p class="empty-state">Failed to load symbol: ${e.message}</p>`;
    }
}

loadSymbolPage();
