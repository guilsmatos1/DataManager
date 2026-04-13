let _symbolStrategies = [];
let _symbolSortCol = "id";
let _symbolSortAsc = true;

function symbolSortBy(col) {
    if (_symbolSortCol === col) _symbolSortAsc = !_symbolSortAsc;
    else { _symbolSortCol = col; _symbolSortAsc = true; }
    renderSymbolStrategies();
}

function renderSymbolStrategies() {
    const arrow = (col) => _symbolSortCol === col ? (_symbolSortAsc ? " ↑" : " ↓") : "";
    const thead = document.querySelector("#symbol-strategies-card thead");
    if (thead) thead.innerHTML = `
        <tr>
            <th class="sortable" onclick="symbolSortBy('id')">ID${arrow("id")}</th>
            <th class="sortable" onclick="symbolSortBy('name')">Name${arrow("name")}</th>
            <th class="sortable" onclick="symbolSortBy('symbol')">Symbol${arrow("symbol")}</th>
            <th class="sortable" onclick="symbolSortBy('account_name')">Account${arrow("account_name")}</th>
            <th class="sortable" onclick="symbolSortBy('live')">Status${arrow("live")}</th>
        </tr>`;

    const tbody = document.getElementById("symbol-strategies-body");
    const list = [..._symbolStrategies].sort((a, b) => {
        let va = a[_symbolSortCol];
        let vb = b[_symbolSortCol];
        if (va == null) va = _symbolSortAsc ? "\uffff" : "";
        if (vb == null) vb = _symbolSortAsc ? "\uffff" : "";
        if (typeof va === "number" && typeof vb === "number") {
            return _symbolSortAsc ? va - vb : vb - va;
        }
        return _symbolSortAsc
            ? String(va).localeCompare(String(vb))
            : String(vb).localeCompare(String(va));
    });

    tbody.innerHTML = "";
    list.forEach((s) => {
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
