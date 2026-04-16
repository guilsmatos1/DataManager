let _corrData = {};
let _stratNames = {};
let _corrPeriod = "daily";
let _strategyIds = [];

const GREEN_PALETTE = [
    "rgba(16,185,129,0.05)", "rgba(16,185,129,0.13)", "rgba(16,185,129,0.21)",
    "rgba(16,185,129,0.30)", "rgba(16,185,129,0.39)", "rgba(16,185,129,0.48)",
    "rgba(16,185,129,0.57)", "rgba(16,185,129,0.66)", "rgba(16,185,129,0.75)",
    "rgba(16,185,129,0.84)", "rgba(16,185,129,0.93)",
];

function corrColor(val, isDiag = false) {
    if (isDiag) return { bg: "rgba(59,130,246,0.35)", text: "#e2e8f0" };
    if (val === null) return { bg: "var(--surface-2)", text: "var(--text-muted)" };
    const v = Math.max(0, Math.min(1, val));
    const idx = Math.min(10, Math.floor(v * 10 + 0.001));
    return { bg: GREEN_PALETTE[idx], text: idx >= 6 ? "#fff" : "var(--text)" };
}

function label(id) {
    const name = _stratNames[id];
    if (name && name !== id) return name.length > 24 ? name.slice(0, 23) + "\u2026" : name;
    return "\u2026" + String(id).slice(-6);
}

function buildHeatmap(strategies, matrix, colorFn) {
    const n = strategies.length;
    const labels = strategies.map(id => label(id));
    let html = '<div class="heatmap-scroll"><table class="heatmap-table"><thead><tr><th></th>';
    labels.forEach((l, i) => { html += `<th title="${strategies[i]}">${l}</th>`; });
    html += "</tr></thead><tbody>";
    for (let i = 0; i < n; i++) {
        html += `<tr><th title="${strategies[i]}">${labels[i]}</th>`;
        for (let j = 0; j < n; j++) {
            const val = matrix[i][j];
            const { bg } = colorFn(val, i === j);
            const display = val === null ? "\u2014" : val.toFixed(2);
            html += `<td style="background:${bg};color:#ffffff;text-shadow:0px 1px 2px rgba(0,0,0,0.7);font-weight:700;" title="${strategies[i]} \u00d7 ${strategies[j]}: ${display}">${display}</td>`;
        }
        html += "</tr>";
    }
    html += "</tbody></table></div>";
    return html;
}

function renderCorrInsights(data) {
    const ins = data.insights;
    if (!ins) return;
    const avgCls = ins.avg_correlation >= 0 ? "profit-positive" : "profit-negative";
    let html = `<div class="insight-card">
        <span class="insight-label">Avg pairwise correlation</span>
        <span class="insight-value ${avgCls}">${ins.avg_correlation != null ? ins.avg_correlation.toFixed(2) : "\u2014"}</span>
    </div>`;
    if (ins.most_positive.length) {
        const [a, b, v] = ins.most_positive[0];
        html += `<div class="insight-card insight-warning">
            <span class="insight-label">Most correlated pair</span>
            <span class="insight-value">${label(a)} & ${label(b)}</span>
            <span class="insight-sub profit-positive">${v.toFixed(2)}</span>
        </div>`;
    }
    if (ins.most_negative.length) {
        const [a, b, v] = ins.most_negative[0];
        html += `<div class="insight-card insight-good">
            <span class="insight-label">Most anti-correlated pair</span>
            <span class="insight-value">${label(a)} & ${label(b)}</span>
            <span class="insight-sub profit-negative">${v.toFixed(2)}</span>
        </div>`;
    }
    const avg = ins.avg_correlation;
    let riskMsg = "", riskCls = "";
    if (avg !== null) {
        if (avg > 0.7) { riskMsg = "High correlation \u2014 strategies tend to win/lose together. Consider diversifying."; riskCls = "risk-high"; }
        else if (avg > 0.3) { riskMsg = "Moderate correlation \u2014 some diversification benefit present."; riskCls = "risk-medium"; }
        else if (avg > -0.2) { riskMsg = "Low correlation \u2014 good diversification across strategies."; riskCls = "risk-low"; }
        else { riskMsg = "Negative correlation \u2014 strategies act as natural hedges."; riskCls = "risk-low"; }
        html += `<div class="insight-card insight-full ${riskCls}"><span>${riskMsg}</span></div>`;
    }
    document.getElementById("corr-insights").innerHTML = html;
}

async function loadCorrelation(period) {
    if (_corrData[period]) { renderCorrelation(period); return; }
    document.getElementById("corr-container").innerHTML = '<div class="loading">Computing\u2026</div>';
    document.getElementById("corr-insights").innerHTML = "";
    const params = new URLSearchParams();
    _strategyIds.forEach(id => params.append("strategy_ids", id));
    params.set("period", period);
    try {
        const data = await fetchJson(`/api/correlation?${params.toString()}`);
        _corrData[period] = data;
        renderCorrelation(period);
    } catch (e) {
        document.getElementById("corr-container").innerHTML = '<p class="error">Failed to load correlation data.</p>';
    }
}

function renderCorrelation(period) {
    const data = _corrData[period];
    const container = document.getElementById("corr-container");
    if (data.error) {
        container.innerHTML = `<p class="empty-state">${data.error}</p>`;
        document.getElementById("corr-desc").textContent = "";
        return;
    }
    const from = data.date_range[0] ? data.date_range[0].slice(0, 10) : "\u2014";
    const to = data.date_range[1] ? data.date_range[1].slice(0, 10) : "\u2014";
    document.getElementById("corr-desc").textContent =
        `Based on ${data.data_points} ${period} periods \u00b7 ${from} \u2192 ${to}`;
    container.innerHTML = buildHeatmap(data.strategies, data.matrix, corrColor);
    renderCorrInsights(data);
}

function setPeriod(period) {
    _corrPeriod = period;
    document.querySelectorAll(".period-tabs .period-tab[data-period]").forEach(b => {
        b.classList.toggle("active", b.dataset.period === period);
    });
    loadCorrelation(period);
}

(async () => {
    const params = new URLSearchParams(window.location.search);
    _strategyIds = params.getAll("strategy_ids");
    if (_strategyIds.length < 2) {
        document.getElementById("corr-container").innerHTML =
            '<p class="empty-state">Need at least 2 strategies for correlation analysis.</p>';
        return;
    }
    document.getElementById("strategy-count").textContent = `${_strategyIds.length} strategies`;
    const strats = await fetchJson("/api/strategies");
    strats.forEach(s => { _stratNames[s.id] = s.name || s.id; });
    await loadCorrelation("daily");
})();
