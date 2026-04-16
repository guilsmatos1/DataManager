// equityChart, _allEquityPoints, _equityPeriod declared by table-renderer.js
let _advancedAllStrategies = [];
let _analysisRequestToken = 0;
let _strategyLoadToken = 0;
let _advancedSide = "both";
let _analysisEquityScale = localStorage.getItem("tm-advanced-equity-scale") || "monetary";
let _analysisEquityPoints = [];
let _analysisComparisonPoints = [];
let _analysisBenchmark = null;
let _advMonthlyChart = null;
let _advAnnualChart = null;
let _advDistHourChart = null;
let _advDistDowChart = null;
let _advUnderwaterChart = null;
let _advOverlayChart = null;
let _overlayScale = localStorage.getItem("tm-advanced-overlay-scale") || "pct";
let _advPerStrategyEquity = [];

function setAdvancedSide(side) {
    _advancedSide = side;
    document.querySelectorAll("#param-side-tabs .period-tab").forEach(b =>
        b.classList.toggle("active", b.dataset.side === side));
}

function setAnalysisEquityScale(scale) {
    _analysisEquityScale = scale;
    localStorage.setItem("tm-advanced-equity-scale", scale);
    document.querySelectorAll("#analysis-equity-scale-tabs .period-tab").forEach((button) =>
        button.classList.toggle("active", button.dataset.aes === scale)
    );
    if (_analysisEquityPoints.length || _analysisComparisonPoints.length) {
        renderAnalysisChart(_analysisEquityPoints, _analysisComparisonPoints, _analysisBenchmark);
        renderAnalysisUnderwaterChart(_analysisEquityPoints);
    }
}

function setAnalysisStatus(message = "", tone = "") {
    const status = document.getElementById("analysis-status");
    status.textContent = message;
    status.className = "analysis-status";
    if (tone) status.classList.add(`is-${tone}`);
}

function showAnalysisError(message) {
    const box = document.getElementById("analysis-error");
    document.getElementById("analysis-error-message").textContent = message;
    box.hidden = false;
}

function clearAnalysisError() {
    document.getElementById("analysis-error").hidden = true;
    document.getElementById("analysis-error-message").textContent = "";
}

function selectAllAdvancedStrategies() {
    document
        .querySelectorAll("#new-strategy-list .modal-strat-checkbox")
        .forEach((checkbox) => {
            checkbox.checked = true;
        });

    const selectAll = document.getElementById("modal-strat-select-all");
    if (selectAll) {
        selectAll.checked = true;
    }
}

function extractErrorMessage(error, fallback) {
    const msg = String(error?.message || "").trim();
    if (!msg) return fallback;
    return msg.startsWith("HTTP ") ? msg.replace(/^HTTP\s+\d+:\s*/, "") : msg;
}

function setAnalysisLoading(isLoading) {
    const button = document.getElementById("analysis-update-btn");
    button.disabled = isLoading;
    button.textContent = isLoading ? "Updating..." : "Update";
}

function setStrategiesLoading(message = "Loading strategies...") {
    document.getElementById("new-strategy-list").innerHTML = `<div class="loading" style="padding:0.5rem">${message}</div>`;
}

function showStrategiesError(message) {
    document.getElementById("new-strategy-list").innerHTML = `<p class="error" style="padding:0.75rem">${message}</p>`;
}

function resetAnalysisOutput() {
    _allEquityPoints = [];
    _analysisEquityPoints = [];
    _analysisComparisonPoints = [];
    _analysisBenchmark = null;
    equityChart = destroyChart(equityChart);
    positiveContribChart = destroyChart(positiveContribChart);
    negativeContribChart = destroyChart(negativeContribChart);
    _advMonthlyChart = destroyChart(_advMonthlyChart);
    _advAnnualChart = destroyChart(_advAnnualChart);
    _advDistHourChart = destroyChart(_advDistHourChart);
    _advDistDowChart = destroyChart(_advDistDowChart);
    _advUnderwaterChart = destroyChart(_advUnderwaterChart);
    _advOverlayChart = destroyChart(_advOverlayChart);
    _advPerStrategyEquity = [];
    document.getElementById("equity-section").style.display = "none";
    document.getElementById("underwater-section").style.display = "none";
    document.getElementById("metrics-section").style.display = "none";
    document.getElementById("positive-contrib-section").style.display = "none";
    document.getElementById("negative-contrib-section").style.display = "none";
    document.getElementById("overlay-section").style.display = "none";
    document.getElementById("monthly-section").style.display = "none";
    document.getElementById("distribution-section").style.display = "none";
    document.getElementById("correlation-link").style.display = "none";
    document.querySelector("#equity-section .chart-wrapper").innerHTML = '<canvas id="equity-chart"></canvas>';
    document.getElementById("analysis-metrics").innerHTML = "";
    document.getElementById("analysis-range").textContent = "";
}

function setDefaultDateRange() {
    const today = new Date();
    const yearAgo = new Date(today);
    yearAgo.setFullYear(yearAgo.getFullYear() - 2);
    const dateTo = document.getElementById("param-date-to");
    const dateFrom = document.getElementById("param-date-from");

    if (!dateTo.value) {
        dateTo.value = today.toISOString().slice(0, 10);
    }

    if (!dateFrom.value) {
        dateFrom.value = yearAgo.toISOString().slice(0, 10);
    }
}

async function loadAdvancedDefaults() {
    try {
        const settings = await fetchJson("/api/settings/telegram");
        const initialBalance = Number(settings?.default_initial_balance);
        if (Number.isFinite(initialBalance) && !document.getElementById("param-initial-balance").value) {
            document.getElementById("param-initial-balance").value = initialBalance;
        }
    } catch (error) {
        console.error("Failed to load advanced-analysis defaults:", error);
    }
}

async function loadStrategiesOptions() {
    const requestToken = ++_strategyLoadToken;
    setStrategiesLoading();
    setAnalysisStatus("Loading strategies...", "loading");
    try {
        const historyType = document.getElementById("param-history-type").value;
        const strategies = await fetchJson(`/api/strategies?history_type=${encodeURIComponent(historyType)}`);
        if (requestToken !== _strategyLoadToken) return;
        _advancedAllStrategies = strategies;
        _allStrategies = _advancedAllStrategies;
        _modalLastClickedIdx = null;
        renderModalStrategiesTable();
        if (!strategies.length) {
            setAnalysisStatus(`No strategies available for ${historyType}.`, "error");
            showStrategiesError(`No strategies found for history type "${historyType}".`);
            return;
        }
        setAnalysisStatus(`Loaded ${strategies.length} strategies.`, "success");
    } catch (e) {
        if (requestToken !== _strategyLoadToken) return;
        _advancedAllStrategies = [];
        _allStrategies = [];
        const message = extractErrorMessage(e, "Failed to load strategies.");
        showStrategiesError(message);
        setAnalysisStatus(message, "error");
    }
}

function filterModalStrategies() {
    _modalLastClickedIdx = null;
    renderModalStrategiesTable();
}

function strategyMatchesAdvancedHistoryType(strategy, historyType) {
    const accountType = String(strategy.account_type || "").trim().toLowerCase();
    if (historyType === "backtest") return true;
    if (accountType.includes("demo")) return historyType === "demo";
    if (accountType.includes("real")) return historyType === "real";
    if (historyType === "real") return Boolean(strategy.real_account);
    if (historyType === "demo") return !Boolean(strategy.real_account);
    return true;
}

function applyAdvancedStrategyFilter() {
    const historyType = document.getElementById("param-history-type").value;
    _allStrategies = _advancedAllStrategies.filter((strategy) =>
        strategyMatchesAdvancedHistoryType(strategy, historyType)
    );
    _modalLastClickedIdx = null;
    renderModalStrategiesTable();
}

async function loadBenchmarksOptions() {
    const select = document.getElementById("param-benchmark");
    select.innerHTML = '<option value="">Loading benchmarks...</option>';
    try {
        const benchmarks = await fetchJson("/api/benchmarks");
        const options = ['<option value="">Default / None</option>'];
        benchmarks.forEach((b) => {
            const selected = b.is_default ? "selected" : "";
            const suffix = b.is_default ? " [default]" : "";
            options.push(`<option value="${b.id}" ${selected}>${b.name}${suffix}</option>`);
        });
        select.innerHTML = options.join("");
    } catch (e) {
        select.innerHTML = '<option value="">Default / None</option>';
        setAnalysisStatus(extractErrorMessage(e, "Failed to load benchmarks."), "error");
    }
}

function getSelectedStrategies() {
    return [...document.querySelectorAll("#new-strategy-list input.modal-strat-checkbox:checked")].map(el => el.value);
}

let positiveContribChart = null;
let negativeContribChart = null;

const CONTRIB_COLORS = [
    "#10b981", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6",
    "#ec4899", "#14b8a6", "#f97316", "#06b6d4", "#84cc16",
    "#6366f1", "#d946ef", "#0ea5e9", "#22c55e", "#eab308",
];

function renderContributionCharts(contributions) {
    const posSection = document.getElementById("positive-contrib-section");
    const negSection = document.getElementById("negative-contrib-section");
    const posWrap = document.querySelector("#positive-contrib-section .chart-wrapper");
    const negWrap = document.querySelector("#negative-contrib-section .chart-wrapper");

    if (!contributions || !contributions.length) {
        positiveContribChart = destroyChart(positiveContribChart);
        negativeContribChart = destroyChart(negativeContribChart);
        posSection.style.display = "none";
        negSection.style.display = "none";
        return;
    }

    const isDark = document.documentElement.getAttribute("data-theme") !== "light";
    const textColor = isDark ? "#e2e8f0" : "#334155";

    const positive = contributions.filter(c => c.profit > 0);
    const negative = contributions.filter(c => c.profit < 0);

    // ── Positive pie ────────────────────────────────────
    if (positive.length) {
        posSection.style.display = "block";
        const totalPos = positive.reduce((s, c) => s + c.profit, 0);
        const positiveLabels = positive.map((c) => {
            const pct = totalPos > 0 ? ((c.profit / totalPos) * 100).toFixed(1) : "0.0";
            return `${c.name} (${pct}%)`;
        });
        positiveContribChart = destroyChart(positiveContribChart);
        posWrap.innerHTML = '<canvas id="positive-contrib-chart"></canvas>';
        const ctx = document.getElementById("positive-contrib-chart").getContext("2d");

        positiveContribChart = new Chart(ctx, {
            type: "pie",
            data: {
                labels: positiveLabels,
                datasets: [{
                    data: positive.map(c => c.profit),
                    backgroundColor: positive.map((_, i) => CONTRIB_COLORS[i % CONTRIB_COLORS.length]),
                    borderWidth: 1,
                    borderColor: isDark ? "#1e293b" : "#ffffff",
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: { position: "right", labels: { color: textColor, padding: 12, font: { size: 12 } } },
                    tooltip: {
                        callbacks: {
                            label: (c) => {
                                const pct = ((c.parsed / totalPos) * 100).toFixed(1);
                                return ` ${c.label}: ${fmt(c.parsed)} (${pct}%)`;
                            },
                        },
                    },
                },
            },
        });
    } else {
        positiveContribChart = destroyChart(positiveContribChart);
        posWrap.innerHTML = '<p class="empty-state" style="padding:2rem 0">No positive contribution in this range.</p>';
        posSection.style.display = "none";
    }

    // ── Negative pie ────────────────────────────────────
    if (negative.length) {
        negSection.style.display = "block";
        const totalNeg = negative.reduce((s, c) => s + Math.abs(c.profit), 0);
        const negativeLabels = negative.map((c) => {
            const pct = totalNeg > 0 ? ((Math.abs(c.profit) / totalNeg) * 100).toFixed(1) : "0.0";
            return `${c.name} (${pct}%)`;
        });
        negativeContribChart = destroyChart(negativeContribChart);
        negWrap.innerHTML = '<canvas id="negative-contrib-chart"></canvas>';
        const ctx = document.getElementById("negative-contrib-chart").getContext("2d");

        negativeContribChart = new Chart(ctx, {
            type: "pie",
            data: {
                labels: negativeLabels,
                datasets: [{
                    data: negative.map(c => Math.abs(c.profit)),
                    backgroundColor: negative.map((_, i) => CONTRIB_COLORS[i % CONTRIB_COLORS.length]),
                    borderWidth: 1,
                    borderColor: isDark ? "#1e293b" : "#ffffff",
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: { position: "right", labels: { color: textColor, padding: 12, font: { size: 12 } } },
                    tooltip: {
                        callbacks: {
                            label: (c) => {
                                const pct = ((c.parsed / totalNeg) * 100).toFixed(1);
                                return ` ${c.label}: -${fmt(c.parsed)} (${pct}%)`;
                            },
                        },
                    },
                },
            },
        });
    } else {
        negativeContribChart = destroyChart(negativeContribChart);
        negWrap.innerHTML = '<p class="empty-state" style="padding:2rem 0">No negative contribution in this range.</p>';
        negSection.style.display = "none";
    }
}

const ANALYSIS_METRIC_CATEGORIES = [
    {
        title: "Summary",
        keys: ["total trades", "profit", "avg profit", "return (%)", "return on capital (%)"],
    },
    {
        title: "Profitability",
        keys: ["profit factor", "win rate (%)", "gross profit", "gross loss"],
    },
    {
        title: "Risk-Adjusted Returns",
        keys: ["risk-reward ratio", "sharpe ratio", "sortino ratio", "calmar ratio", "ret/dd"],
    },
    {
        title: "Drawdown & Risk",
        keys: ["drawdown", "var 95% (daily)", "cvar 95% (daily)", "z-score"],
    },
    {
        title: "Streaks",
        keys: ["consecutive wins", "consecutive losses"],
    },
    {
        title: "Trade Breakdown",
        keys: ["long trades", "long trades (%)", "short trades", "short trades (%)"],
    },
];

function renderAnalysisMetrics(metrics) {
    const container = document.getElementById("analysis-metrics");
    const section = document.getElementById("metrics-section");

    if (metrics.error) {
        container.innerHTML = `<p class="empty-state">${metrics.error}</p>`;
        section.style.display = "block";
        return;
    }

    container.innerHTML = "";
    container.classList.remove("metrics-grid");
    container.classList.add("metrics-categories");
    const gridOptions = {
        advancedKeys: [],
        integerKeys: ["total trades", "consecutive wins", "consecutive losses", "long trades", "short trades"],
    };

    const metricEntries = Object.entries(metrics);
    const lookup = new Map(metricEntries.map(([key, value]) => [key.toLowerCase(), { key, value }]));
    const used = new Set();

    ANALYSIS_METRIC_CATEGORIES.forEach((category) => {
        const categoryMetrics = {};
        category.keys.forEach((keyLower) => {
            const entry = lookup.get(keyLower);
            if (entry && !used.has(keyLower)) {
                categoryMetrics[entry.key] = entry.value;
                used.add(keyLower);
            }
        });
        if (!Object.keys(categoryMetrics).length) return;

        const group = document.createElement("div");
        group.className = "metrics-category";
        const heading = document.createElement("h3");
        heading.className = "metrics-category-title";
        heading.textContent = category.title;
        const grid = document.createElement("div");
        grid.className = "metrics-grid";
        renderMetricsGrid(grid, categoryMetrics, gridOptions);
        group.appendChild(heading);
        group.appendChild(grid);
        container.appendChild(group);
    });

    const remaining = {};
    metricEntries.forEach(([key, value]) => {
        if (!used.has(key.toLowerCase())) remaining[key] = value;
    });
    if (Object.keys(remaining).length) {
        const group = document.createElement("div");
        group.className = "metrics-category";
        const heading = document.createElement("h3");
        heading.className = "metrics-category-title";
        heading.textContent = "Other";
        const grid = document.createElement("div");
        grid.className = "metrics-grid";
        renderMetricsGrid(grid, remaining, gridOptions);
        group.appendChild(heading);
        group.appendChild(grid);
        container.appendChild(group);
    }

    section.style.display = "block";
}

function buildAnalysisSeries(points, getter) {
    const baselinePoint = points.find((point) => {
        const value = getter(point);
        return value != null && Number.isFinite(Number(value));
    });
    if (!baselinePoint) return points.map(() => null);

    const baseline = Number(getter(baselinePoint)) || 1;
    return points.map((point) => {
        const value = getter(point);
        if (value == null || !Number.isFinite(Number(value))) return null;

        const numericValue = Number(value);
        if (_analysisEquityScale === "pct") {
            return parseFloat((((numericValue / baseline) - 1) * 100).toFixed(4));
        }
        return parseFloat((numericValue - baseline).toFixed(4));
    });
}

function renderAnalysisChart(equityPoints, comparisonPoints, benchmark) {
    const canvasWrap = document.getElementById("equity-chart").parentElement;
    const hasComparison = Array.isArray(comparisonPoints) && comparisonPoints.length > 0;
    const hasEquity = Array.isArray(equityPoints) && equityPoints.length > 0;
    if (!hasComparison && !hasEquity) {
        canvasWrap.innerHTML = '<p class="empty-state" style="padding:2rem 0">No equity data yet.</p>';
        document.getElementById("equity-section").style.display = "block";
        return;
    }

    canvasWrap.innerHTML = '<canvas id="equity-chart"></canvas>';
    const ctx = document.getElementById("equity-chart").getContext("2d");
    const isPct = _analysisEquityScale === "pct";
    const { tickColor } = getEquityChartColors();
    const labelsSource = hasComparison ? comparisonPoints : equityPoints;
    const labels = buildEquityChartLabels(labelsSource);

    const seriesData = hasComparison
        ? buildAnalysisSeries(comparisonPoints, (point) => point.portfolio)
        : buildAnalysisSeries(equityPoints, (point) => point.equity);
    const lastValue = seriesData.filter(v => v != null).pop() ?? 0;
    const palette = getProfitPalette(lastValue);

    const datasets = [{
        label: "Portfolio / Strategies",
        data: seriesData,
        borderColor: palette.borderColor,
        backgroundColor: palette.backgroundColor,
        fill: true,
        tension: 0.3,
        pointRadius: 0,
        borderWidth: 2.5,
    }];

    if (benchmark && hasComparison && comparisonPoints.some((p) => p.benchmark != null)) {
        datasets.push({
            label: benchmark.name,
            data: buildAnalysisSeries(comparisonPoints, (point) => point.benchmark),
            borderColor: "#f59e0b",
            backgroundColor: "transparent",
            fill: false,
            tension: 0.25,
            pointRadius: 0,
            borderWidth: 2,
            borderDash: [6, 4],
        });
    }

    destroyChart(equityChart);
    equityChart = createEquityLineChart(ctx, {
        labels,
        datasets,
        isPct,
        zoom: false,
        legend: { display: true, labels: { color: tickColor } },
        yTitle: isPct ? "Return" : "Accumulated Capital",
        tooltipLabel: (c) => {
            if (c.parsed.y == null) return null;
            const prefix = c.datasetIndex > 0 ? ` ${c.dataset.label}: ` : " Portfolio: ";
            return `${prefix}${isPct ? `${Number(c.parsed.y).toFixed(2)}%` : fmt(c.parsed.y)}`;
        },
    });
    document.getElementById("equity-section").style.display = "block";
}

function renderAnalysisUnderwaterChart(equityPoints) {
    const section = document.getElementById("underwater-section");
    const canvasId = "analysis-underwater-chart";
    const wrapper = document.querySelector("#underwater-section .chart-wrapper");

    if (!equityPoints || !equityPoints.length) {
        _advUnderwaterChart = destroyChart(_advUnderwaterChart);
        section.style.display = "none";
        return;
    }

    wrapper.innerHTML = `<canvas id="${canvasId}"></canvas>`;
    const canvas = document.getElementById(canvasId);
    const isPct = _analysisEquityScale === "pct";
    const seriesValues = buildRebasedEquitySeries(
        equityPoints, _analysisEquityScale, (p) => p.equity
    );

    let peak = -Infinity;
    const ddValues = seriesValues.map(v => {
        if (v > peak) peak = v;
        return parseFloat((v - peak).toFixed(4));
    });

    const labels = buildEquityChartLabels(equityPoints);
    const { tickColor, gridColor } = getEquityChartColors();
    const ddTickCb = isPct ? v => `${v.toFixed(1)}%` : v => fmt(v);
    const ddTooltipCb = isPct
        ? c => ` DD: ${c.parsed.y.toFixed(2)}%`
        : c => ` DD: ${fmt(c.parsed.y)}`;

    destroyChart(_advUnderwaterChart);
    _advUnderwaterChart = new Chart(canvas.getContext("2d"), {
        type: "line",
        data: {
            labels,
            datasets: [{
                label: isPct ? "Drawdown %" : "Drawdown $",
                data: ddValues,
                borderColor: CHART_COLORS.underwaterBorder,
                backgroundColor: CHART_COLORS.underwaterFill,
                fill: true,
                tension: 0.2,
                pointRadius: 0,
                borderWidth: 1.5,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: ddTooltipCb } },
            },
            scales: {
                x: { ticks: { maxTicksLimit: 12, color: tickColor }, grid: { color: gridColor } },
                y: {
                    ticks: { color: tickColor, callback: ddTickCb },
                    grid: { color: gridColor },
                    max: 0,
                },
            },
        },
    });
    section.style.display = "block";
}

function setOverlayScale(scale) {
    _overlayScale = scale;
    localStorage.setItem("tm-advanced-overlay-scale", scale);
    document.querySelectorAll("#overlay-scale-tabs .period-tab").forEach((button) =>
        button.classList.toggle("active", button.dataset.os === scale)
    );
    if (Array.isArray(_advPerStrategyEquity) && _advPerStrategyEquity.length) {
        renderStrategyOverlay(_advPerStrategyEquity);
    }
}

function renderStrategyOverlay(perStrategyEquity) {
    const section = document.getElementById("overlay-section");
    _advPerStrategyEquity = perStrategyEquity || [];

    if (!perStrategyEquity || perStrategyEquity.length < 2) {
        _advOverlayChart = destroyChart(_advOverlayChart);
        section.style.display = "none";
        return;
    }

    const wrapper = document.querySelector("#overlay-section .chart-wrapper");
    wrapper.innerHTML = '<canvas id="overlay-chart"></canvas>';
    const canvas = document.getElementById("overlay-chart");
    const { tickColor } = getEquityChartColors();
    const isPct = _overlayScale === "pct";

    const longestSeries = perStrategyEquity.reduce(
        (longest, s) => s.points.length > longest.points.length ? s : longest,
        perStrategyEquity[0]
    );
    const labels = buildEquityChartLabels(longestSeries.points);

    const initialBalance = parseFloat(document.getElementById("param-initial-balance").value) || null;
    const datasets = perStrategyEquity.map((s, i) => {
        const color = CONTRIB_COLORS[i % CONTRIB_COLORS.length];
        const pctOptions = (isPct && initialBalance)
            ? { pctBaseline: 0, pctDenominator: initialBalance }
            : {};
        const values = buildRebasedEquitySeries(s.points, _overlayScale, (p) => p.equity, pctOptions);
        return {
            label: s.name,
            data: values,
            borderColor: color,
            backgroundColor: "transparent",
            fill: false,
            tension: 0.3,
            pointRadius: 0,
            borderWidth: 2,
        };
    });

    destroyChart(_advOverlayChart);
    _advOverlayChart = createEquityLineChart(canvas.getContext("2d"), {
        labels,
        datasets,
        isPct,
        zoom: false,
        legend: { display: true, labels: { color: tickColor, boxWidth: 12, padding: 10 } },
        yTitle: isPct ? "Return %" : "Return",
        tooltipLabel: (c) => {
            if (c.parsed.y == null) return null;
            const formatted = isPct
                ? `${Number(c.parsed.y).toFixed(2)}%`
                : fmt(c.parsed.y);
            return ` ${c.dataset.label}: ${formatted}`;
        },
    });
    section.style.display = "block";
}

function updateCorrelationLink(strategyIds) {
    const link = document.getElementById("correlation-link");
    if (strategyIds.length < 2) {
        link.style.display = "none";
        return;
    }
    const params = new URLSearchParams();
    strategyIds.forEach(id => params.append("strategy_ids", id));
    link.href = `/correlation?${params.toString()}`;
    link.style.display = "";
}

function renderAdvancedPnlAndDistribution(dailyPnl, tradeStats) {
    const monthlySection = document.getElementById("monthly-section");
    const distSection = document.getElementById("distribution-section");

    if (dailyPnl.length) {
        const { labels, values } = aggregateMonthlyPnl(dailyPnl);
        _advMonthlyChart = renderPnlBarChart(
            "monthly-pnl-chart", "monthly-pnl-wrapper",
            monthLabelsForDisplay(labels), values, _advMonthlyChart
        );
        const annual = aggregateAnnualPnl(labels, values);
        _advAnnualChart = renderPnlBarChart(
            "annual-pnl-chart", "annual-pnl-wrapper",
            annual.labels, annual.values, _advAnnualChart
        );
        monthlySection.style.display = "block";
    }

    if (tradeStats.by_hour) {
        _advDistHourChart = renderDistBarChart(
            "dist-hour-chart", "dist-hour-wrapper",
            tradeStats.by_hour.map(r => r.hour + ":00"),
            tradeStats.by_hour.map(r => r.net_profit),
            _advDistHourChart
        );
        _advDistDowChart = renderDistBarChart(
            "dist-dow-chart", "dist-dow-wrapper",
            tradeStats.by_dow.map(r => r.label),
            tradeStats.by_dow.map(r => r.net_profit),
            _advDistDowChart
        );
        distSection.style.display = "block";
    }
}

async function runAdvancedAnalysis() {
    const requestToken = ++_analysisRequestToken;
    const strategyIds = getSelectedStrategies();
    if (!strategyIds.length) {
        clearAnalysisError();
        setAnalysisStatus("Select at least one strategy.", "error");
        return;
    }

    clearAnalysisError();
    setAnalysisLoading(true);
    setAnalysisStatus("Running analysis...", "loading");
    const params = new URLSearchParams();
    strategyIds.forEach((id) => params.append("strategy_ids", id));
    params.set("history_type", document.getElementById("param-history-type").value);

    const dateFrom = document.getElementById("param-date-from").value;
    const dateTo = document.getElementById("param-date-to").value;
    const initialBalance = document.getElementById("param-initial-balance").value;
    const benchmarkId = document.getElementById("param-benchmark").value;
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (initialBalance) params.set("initial_balance", initialBalance);
    if (benchmarkId) params.set("benchmark_id", benchmarkId);
    if (_advancedSide !== "both") params.set("side", _advancedSide);

    try {
        const data = await fetchJson(`/api/advanced-analysis?${params.toString()}`);
        if (requestToken !== _analysisRequestToken) return;

        _analysisEquityPoints = data.equity_curve || [];
        _analysisComparisonPoints = data.comparison_curve || [];
        _analysisBenchmark = data.benchmark || null;
        _allEquityPoints = _analysisEquityPoints;
        renderAnalysisChart(
            _analysisEquityPoints,
            _analysisComparisonPoints,
            _analysisBenchmark
        );

        renderAnalysisUnderwaterChart(_analysisEquityPoints);
        renderAnalysisMetrics(data.metrics || {});
        renderContributionCharts(data.strategy_contributions || []);
        renderStrategyOverlay(data.per_strategy_equity || []);
        renderAdvancedPnlAndDistribution(data.daily_pnl || [], data.trade_stats || {});
        updateCorrelationLink(strategyIds);

        const rangeText = dateFrom || dateTo
            ? `${dateFrom || "beginning"} → ${dateTo || "now"}`
            : "All time";
        const benchmarkText = data.benchmark ? ` · benchmark: ${data.benchmark.name}` : "";
        document.getElementById("analysis-range").textContent = `${rangeText}${benchmarkText}`;
        setAnalysisStatus("Analysis updated.", "success");
    } catch (e) {
        if (requestToken !== _analysisRequestToken) return;
        const message = extractErrorMessage(e, "Failed to update analysis.");
        resetAnalysisOutput();
        showAnalysisError(message);
        setAnalysisStatus(message, "error");
    } finally {
        if (requestToken === _analysisRequestToken) {
            setAnalysisLoading(false);
        }
    }
}

function parseUrlParams() {
    const params = new URLSearchParams(window.location.search);
    return {
        strategyIds: params.getAll("strategy_ids"),
        historyType: params.get("history_type"),
        dateFrom: params.get("date_from"),
        dateTo: params.get("date_to"),
        initialBalance: params.get("initial_balance"),
        benchmarkId: params.get("benchmark_id"),
        side: params.get("side"),
    };
}

function applyUrlStrategies(strategyIds) {
    if (!strategyIds.length) return false;
    const checkboxes = document.querySelectorAll("#new-strategy-list .modal-strat-checkbox");
    let anyChecked = false;
    checkboxes.forEach((cb) => {
        const checked = strategyIds.includes(cb.value);
        cb.checked = checked;
        if (checked) anyChecked = true;
    });
    const selectAll = document.getElementById("modal-strat-select-all");
    if (selectAll) {
        selectAll.checked = checkboxes.length > 0 && [...checkboxes].every((cb) => cb.checked);
    }
    return anyChecked;
}

document.addEventListener("DOMContentLoaded", async () => {
    const urlParams = parseUrlParams();

    setDefaultDateRange();
    document.getElementById("param-history-type").value = urlParams.historyType || "demo";
    if (urlParams.dateFrom) document.getElementById("param-date-from").value = urlParams.dateFrom;
    if (urlParams.dateTo) document.getElementById("param-date-to").value = urlParams.dateTo;
    if (urlParams.initialBalance) document.getElementById("param-initial-balance").value = urlParams.initialBalance;
    if (urlParams.side) setAdvancedSide(urlParams.side);
    setAnalysisEquityScale(_analysisEquityScale);
    setOverlayScale(_overlayScale);

    await Promise.all([
        loadAdvancedDefaults(),
        loadStrategiesOptions(),
        loadBenchmarksOptions(),
    ]);

    if (urlParams.benchmarkId) document.getElementById("param-benchmark").value = urlParams.benchmarkId;

    let hasStrategies = false;
    if (urlParams.strategyIds.length) {
        hasStrategies = applyUrlStrategies(urlParams.strategyIds);
    } else if (document.querySelector("#new-strategy-list .modal-strat-checkbox")) {
        selectAllAdvancedStrategies();
        hasStrategies = true;
    }

    if (hasStrategies) {
        await runAdvancedAnalysis();
    }

    document.getElementById("param-history-type").addEventListener("change", async () => {
        await loadStrategiesOptions();
        if (document.querySelector("#new-strategy-list .modal-strat-checkbox")) {
            selectAllAdvancedStrategies();
            await runAdvancedAnalysis();
        } else {
            resetAnalysisOutput();
        }
    });
});
