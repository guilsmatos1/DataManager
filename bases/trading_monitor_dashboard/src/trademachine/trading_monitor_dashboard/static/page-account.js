let _accountStrategies = [];
let _accountSortCol = "id";
let _accountSortAsc = true;

function accountSortBy(col) {
    ({ col: _accountSortCol, asc: _accountSortAsc } = toggleSort(_accountSortCol, _accountSortAsc, col));
    renderAccountStrategies();
}

function renderAccountStrategies() {
    const arrow = (col) => _accountSortCol === col ? (_accountSortAsc ? " ↑" : " ↓") : "";
    const thead = document.querySelector("#account-strategies-card thead");
    if (thead) thead.innerHTML = `
        <tr>
            <th class="sortable" onclick="accountSortBy('id')">ID${arrow("id")}</th>
            <th class="sortable" onclick="accountSortBy('name')">Name${arrow("name")}</th>
            <th class="sortable" onclick="accountSortBy('symbol')">Symbol${arrow("symbol")}</th>
            <th class="sortable" onclick="accountSortBy('live')">Status${arrow("live")}</th>
        </tr>`;

    const tbody = document.getElementById("account-strategies-body");
    const list = [..._accountStrategies].sort((a, b) => {
        let va = a[_accountSortCol];
        let vb = b[_accountSortCol];
        if (va == null) va = _accountSortAsc ? "\uffff" : "";
        if (vb == null) vb = _accountSortAsc ? "\uffff" : "";
        if (typeof va === "number" && typeof vb === "number") {
            return _accountSortAsc ? va - vb : vb - va;
        }
        return _accountSortAsc
            ? String(va).localeCompare(String(vb))
            : String(vb).localeCompare(String(va));
    });

    tbody.innerHTML = "";
    list.forEach((strategy) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td><a href="/strategy/${strategy.id}" style="color:var(--accent)">${strategy.id}</a></td>
            <td>${strategy.name || "—"}</td>
            <td>${strategy.symbol || "—"}</td>
            <td><span class="badge ${strategy.live ? "badge-live" : "badge-incubation"}">${strategy.live ? "Live" : "Incubation"}</span></td>
        `;
        tbody.appendChild(tr);
    });
}

function buildMetaItem(label, value) {
    return `
        <div class="info-item">
            <span class="info-label">${label}</span>
            <span class="info-value">${value}</span>
        </div>
    `;
}

function fmtMoney(value, currency = "") {
    if (value == null) return "—";
    const prefix = currency ? `${currency} ` : "$ ";
    return prefix + fmt(Number(value));
}

async function loadAccountPage() {
    try {
        const [accounts, strategies] = await Promise.all([
            fetchJson("/api/accounts"),
            fetchJson("/api/strategies"),
        ]);

        const account = accounts.find((item) => String(item.id) === String(ACCOUNT_ID));
        if (!account) {
            document.getElementById("account-empty").style.display = "block";
            return;
        }

        const filteredStrategies = strategies.filter(
            (item) => String(item.account_id || "") === String(ACCOUNT_ID)
        );
        _accountStrategies = filteredStrategies;

        const cur = account.currency || "";
        document.getElementById("account-title").textContent = account.name || `Account ${account.id}`;
        document.getElementById("account-name").textContent = account.name || account.id;
        document.getElementById("account-broker").textContent = account.broker || "—";
        document.getElementById("account-balance").textContent = fmtMoney(account.balance, cur);
        document.getElementById("account-strategy-count").textContent = filteredStrategies.length;
        document.getElementById("account-summary").style.display = "";

        document.getElementById("account-meta").innerHTML = [
            buildMetaItem("Account ID", account.id || "—"),
            buildMetaItem("Broker", account.broker || "—"),
            buildMetaItem("Type", account.account_type || "—"),
            buildMetaItem("Currency", cur || "—"),
            buildMetaItem("Free Margin", fmtMoney(account.free_margin, cur)),
            buildMetaItem("Deposits", fmtMoney(account.total_deposits, cur)),
            buildMetaItem("Withdrawals", fmtMoney(account.total_withdrawals, cur)),
        ].join("");
        document.getElementById("account-details-card").style.display = "";

        renderAccountStrategies();
        document.getElementById("account-strategies-badge").textContent = filteredStrategies.length;
        document.getElementById("account-strategies-card").style.display = "";
    } catch (error) {
        showInlineError("account-empty", `Failed to load account: ${error.message}`);
    }
}

loadAccountPage();
