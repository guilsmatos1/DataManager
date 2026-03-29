/* ── portfolio.html page-specific initialization ──────────────────────────────── */

// Note: PORTFOLIO_ID is a Jinja variable injected by the template (not defined here).
// loadPortfolio, loadMetrics, loadEquity, loadCalendar are in api-client.js.
// loadStrategies, renderPortfolioStrategies, renderEquityChart, renderCalendar are in table-renderer.js.

window.addEventListener("ws-event", function(e) {
    const { topic } = e.detail;
    if (topic === "DEAL" || topic === "EQUITY") { loadMetrics(); loadEquity(); loadCalendar(); }
});

window.addEventListener("tm-theme-change", function() {
    loadEquity();
});

(async () => {
    await loadPortfolio();
    loadMetrics();
    loadEquity();
    loadCalendar();
    loadStrategies();
})();
