let _corrData    = {};   // cache per period
let _concData    = null;
let _stratNames  = {};
let _corrPeriod  = "daily";
let _concMode    = "same_day";
let _windowDays  = 30;

/* ── Bootstrap ── */
(async () => {
    // Load strategy names
    const strats = await fetchJson("/api/strategies");
    strats.forEach(s => { _stratNames[s.id] = s.name || s.id; });

    // Portfolio name
    const p = await fetchJson(`/api/portfolios/${PORTFOLIO_ID}`);
    document.getElementById("portfolio-name").textContent = p.name || "";

    await Promise.all([
        loadCorrelation("daily"),
        loadDynamicCorrelation(30),
        loadConcurrency()
    ]);
})();

/* ── Correlation ── */
async function loadCorrelation(period) {
    if (_corrData[period]) { renderCorrelation(period); return; }
    document.getElementById("corr-container").innerHTML = '<div class="loading">Computing…</div>';
    document.getElementById("corr-insights").innerHTML = "";
    try {
        const data = await fetchJson(`/api/portfolios/${PORTFOLIO_ID}/correlation?period=${period}`);
        _corrData[period] = data;
        renderCorrelation(period);
    } catch(e) {
        document.getElementById("corr-container").innerHTML = '<p class="error">Failed to load correlation data.</p>';
    }
}

function setPeriod(period) {
    _corrPeriod = period;
    document.querySelectorAll(".period-tabs .period-tab[data-period]").forEach(b => {
        b.classList.toggle("active", b.dataset.period === period);
    });
    loadCorrelation(period);
}

function renderCorrelation(period) {
    const data = _corrData[period];
    const container = document.getElementById("corr-container");

    if (data.error) {
        container.innerHTML = `<p class="empty-state">${data.error}</p>`;
        document.getElementById("corr-desc").textContent = "";
        return;
    }

    const from = data.date_range[0] ? data.date_range[0].slice(0, 10) : "—";
    const to   = data.date_range[1] ? data.date_range[1].slice(0, 10) : "—";
    document.getElementById("corr-desc").textContent =
        `Based on ${data.data_points} ${period} periods · ${from} → ${to}`;

    container.innerHTML = buildHeatmap(data.strategies, data.matrix, v => corrColor(v));
    renderCorrInsights(data);
}

function renderCorrInsights(data) {
    const ins = data.insights;
    if (!ins) return;

    const avgCls = ins.avg_correlation >= 0 ? "profit-positive" : "profit-negative";
    let html = `<div class="insight-card">
        <span class="insight-label">Avg pairwise correlation</span>
        <span class="insight-value ${avgCls}">${ins.avg_correlation != null ? ins.avg_correlation.toFixed(2) : "—"}</span>
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

    // Risk interpretation
    const avg = ins.avg_correlation;
    let riskMsg = "", riskCls = "";
    if (avg === null)          { riskMsg = ""; }
    else if (avg > 0.7)        { riskMsg = "⚠️ High correlation — strategies tend to win/lose together. Consider diversifying."; riskCls = "risk-high"; }
    else if (avg > 0.3)        { riskMsg = "⚡ Moderate correlation — some diversification benefit present."; riskCls = "risk-medium"; }
    else if (avg > -0.2)       { riskMsg = "✅ Low correlation — good diversification across strategies."; riskCls = "risk-low"; }
    else                        { riskMsg = "✅ Negative correlation — strategies act as natural hedges."; riskCls = "risk-low"; }
    if (riskMsg) html += `<div class="insight-card insight-full ${riskCls}"><span>${riskMsg}</span></div>`;

    document.getElementById("corr-insights").innerHTML = html;
}

/* ── Dynamic Correlation ── */
async function loadDynamicCorrelation(days) {
    _windowDays = days;
    const container = document.getElementById("dynamic-corr-container");
    container.innerHTML = '<div class="loading">Computing…</div>';

    try {
        const data = await fetchJson(`/api/portfolios/${PORTFOLIO_ID}/correlation/dynamic?window_days=${days}`);

        if (data.error) {
            container.innerHTML = `<p class="empty-state">${data.error}</p>`;
            return;
        }

        container.innerHTML = buildHeatmap(data.strategies, data.matrix, v => corrColor(v));
    } catch(e) {
        container.innerHTML = '<p class="error">Failed to load dynamic correlation data.</p>';
    }
}

function setWindow(days) {
    document.querySelectorAll(".period-tabs .period-tab[data-window]").forEach(b => {
        b.classList.toggle("active", parseInt(b.dataset.window) === days);
    });
    loadDynamicCorrelation(days);
}

/* ── Concurrency ── */
async function loadConcurrency() {
    document.getElementById("conc-container").innerHTML = '<div class="loading">Computing…</div>';
    try {
        _concData = await fetchJson(`/api/portfolios/${PORTFOLIO_ID}/concurrency`);
        renderConcurrency("same_day");
    } catch(e) {
        document.getElementById("conc-container").innerHTML = '<p class="error">Failed to load concurrency data.</p>';
    }
}

function setConcMode(mode) {
    _concMode = mode;
    document.querySelectorAll(".period-tabs .period-tab[data-conc]").forEach(b => {
        b.classList.toggle("active", b.dataset.conc === mode);
    });
    renderConcurrency(mode);
}

function renderConcurrency(mode) {
    if (!_concData) return;
    const container = document.getElementById("conc-container");

    if (_concData.error) {
        container.innerHTML = `<p class="empty-state">${_concData.error}</p>`;
        return;
    }

    const matrix = _concData[mode];
    container.innerHTML = buildHeatmap(_concData.strategies, matrix, v => concColor(v), true);
    renderConcInsights(mode);
}

function renderConcInsights(mode) {
    const ins = _concData?.insights;
    if (!ins) return;
    const key = mode === "same_hour" ? "top_hour" : mode === "same_day" ? "top_day" : "top_week";
    const top = ins[key] || [];
    const modeLabel = mode === "same_hour" ? "hour" : mode === "same_day" ? "day" : "week";

    let html = "";
    top.forEach(([a, b, v]) => {
        const cls = v > 70 ? "insight-warning" : v > 40 ? "" : "insight-good";
        html += `<div class="insight-card ${cls}">
            <span class="insight-label">Same-${modeLabel} overlap</span>
            <span class="insight-value">${label(a)} & ${label(b)}</span>
            <span class="insight-sub">${v.toFixed(1)}%</span>
        </div>`;
    });

    const allPairs = [];
    const n = _concData.strategies.length;
    const mat = _concData[mode];
    for (let i = 0; i < n; i++)
        for (let j = i+1; j < n; j++)
            allPairs.push(mat[i][j]);
    const avg = allPairs.length ? (allPairs.reduce((s, v) => s + v, 0) / allPairs.length).toFixed(1) : null;

    let riskMsg = "", riskCls = "";
    if (avg !== null) {
        const a = parseFloat(avg);
        if      (a > 70)  { riskMsg = `⚠️ Strategies overlap ${avg}% of the same ${modeLabel}s — high simultaneous exposure.`; riskCls = "risk-high"; }
        else if (a > 40)  { riskMsg = `⚡ Moderate overlap (${avg}%) — some simultaneous risk.`; riskCls = "risk-medium"; }
        else              { riskMsg = `✅ Low overlap (${avg}%) — strategies operate independently on most ${modeLabel}s.`; riskCls = "risk-low"; }
        html += `<div class="insight-card insight-full ${riskCls}"><span>${riskMsg}</span></div>`;
    }
    document.getElementById("conc-insights").innerHTML = html;
}

/* ── Shared heatmap builder ── */
function buildHeatmap(strategies, matrix, colorFn, isPercent = false) {
    const n = strategies.length;
    const labels = strategies.map(id => label(id));

    let html = `<div class="heatmap-scroll"><table class="heatmap-table">
        <thead><tr><th></th>`;
    labels.forEach((l, i) => {
        html += `<th title="${strategies[i]}">${l}</th>`;
    });
    html += `</tr></thead><tbody>`;

    for (let i = 0; i < n; i++) {
        html += `<tr><th title="${strategies[i]}">${labels[i]}</th>`;
        for (let j = 0; j < n; j++) {
            const val = matrix[i][j];
            const isDiag = i === j;
            const { bg, text } = colorFn(val, isDiag);
            const display = val === null ? "—"
                : isPercent ? val.toFixed(1) + "%"
                : val.toFixed(2);
            html += `<td style="background:${bg};color:#ffffff;text-shadow:0px 1px 2px rgba(0,0,0,0.7);font-weight:700;" title="${strategies[i]} × ${strategies[j]}: ${display}">${display}</td>`;
        }
        html += `</tr>`;
    }
    html += `</tbody></table></div>`;
    return html;
}

/* ── Color functions ── */
// 11-step green palette: index 0 = lightest (≈0.0), index 10 = darkest (≈1.0)
const GREEN_PALETTE = [
    "rgba(16,185,129,0.05)",
    "rgba(16,185,129,0.13)",
    "rgba(16,185,129,0.21)",
    "rgba(16,185,129,0.30)",
    "rgba(16,185,129,0.39)",
    "rgba(16,185,129,0.48)",
    "rgba(16,185,129,0.57)",
    "rgba(16,185,129,0.66)",
    "rgba(16,185,129,0.75)",
    "rgba(16,185,129,0.84)",
    "rgba(16,185,129,0.93)",
];

function corrColor(val, isDiag = false) {
    if (isDiag) return { bg: "rgba(59,130,246,0.35)", text: "#e2e8f0" };
    if (val === null) return { bg: "var(--surface-2)", text: "var(--text-muted)" };
    // Map value to 0-1 range: negative values → lightest shade (index 0)
    const v = Math.max(0, Math.min(1, val));
    const idx = Math.min(10, Math.floor(v * 10 + 0.001));
    const textColor = idx >= 6 ? "#fff" : "var(--text)";
    return { bg: GREEN_PALETTE[idx], text: textColor };
}

function concColor(val, isDiag = false) {
    if (isDiag) return { bg: "rgba(59,130,246,0.35)", text: "#e2e8f0" };
    if (val === null || val === 0) return { bg: "var(--surface-2)", text: "var(--text-muted)" };
    const v = Math.min(100, val) / 100;
    const textColor = v > 0.55 ? "#fff" : "var(--text)";
    if (v > 0.5) return { bg: `rgba(245,158,11,${0.1 + v * 0.75})`, text: textColor };
    return { bg: `rgba(245,158,11,${0.05 + v * 0.45})`, text: textColor };
}

/* ── Label helper ── */
function label(id) {
    const name = _stratNames[id];
    if (name && name !== id) return name.length > 24 ? name.slice(0, 23) + "…" : name;
    return "…" + String(id).slice(-6);
}
