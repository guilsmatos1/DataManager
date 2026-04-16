let _accountStrategies = [];
let _accountSortCol = "id";
let _accountSortAsc = true;
let _accountStratPage = 1;

function accountSortBy(col) {
    ({ col: _accountSortCol, asc: _accountSortAsc } = toggleSort(_accountSortCol, _accountSortAsc, col));
    _accountStratPage = 1;
    renderAccountStrategies();
}

function renderAccountStrategies() {
    const q = (document.getElementById("account-strat-search")?.value || "").toLowerCase().trim();
    const list = _accountStrategies.filter((s) =>
        !q || `${s.id} ${s.name || ""} ${s.symbol || ""}`.toLowerCase().includes(q)
    );

    const thead = document.getElementById("account-strategies-head");
    if (thead) {
        const th = (label, col) => sortTh(label, col, _accountSortCol, _accountSortAsc, "accountSortBy");
        thead.innerHTML = `<tr>
            ${th("ID", "id")}${th("Name", "name")}${th("Symbol", "symbol")}${th("Status", "live")}
        </tr>`;
    }

    const sorted = sortList(list, _accountSortCol, _accountSortAsc);

    const ps = parseInt(document.getElementById("account-strat-page-size")?.value || "25");
    const totalPages = Math.max(1, Math.ceil(sorted.length / ps));
    if (_accountStratPage > totalPages) _accountStratPage = 1;
    const pageList = sorted.slice((_accountStratPage - 1) * ps, _accountStratPage * ps);

    const tbody = document.getElementById("account-strategies-body");
    tbody.innerHTML = "";
    pageList.forEach((strategy) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td><a href="/strategy/${strategy.id}" style="color:var(--accent)">${strategy.id}</a></td>
            <td>${strategy.name || "—"}</td>
            <td>${strategy.symbol || "—"}</td>
            <td><span class="badge ${strategy.live ? "badge-live" : "badge-incubation"}">${strategy.live ? "Live" : "Incubation"}</span></td>
        `;
        tbody.appendChild(tr);
    });

    renderPagination("account-strat-pagination", _accountStratPage, totalPages, (p) => {
        _accountStratPage = p;
        renderAccountStrategies();
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
