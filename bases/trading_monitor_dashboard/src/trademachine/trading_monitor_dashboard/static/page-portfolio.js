/* ── portfolio.html page-specific initialization ──────────────────────────────── */

// Note: PORTFOLIO_ID is a Jinja variable injected by the template (not defined here).
// loadPortfolio, loadMetrics, loadEquity, loadCalendar are in api-client.js.
// renderPortfolioStrategies, renderEquityChart, renderCalendar are in table-renderer.js.

window.addEventListener("ws-event", function(e) {
    const { topic } = e.detail;
    if (topic === "DEAL" || topic === "EQUITY") { loadMetrics(); loadEquity(); loadCalendar(); loadPortfolioStrategies(); }
});

window.addEventListener("tm-theme-change", function() {
    loadEquity();
});

async function loadPortfolioStrategies() {
    try {
        const res = await fetch(`/api/portfolios/${PORTFOLIO_ID}/strategies`);
        _portStratList = await res.json();
        renderPortfolioStrategies();
        document.getElementById("strategies-badge").textContent = `${_portStratList.length} strategies`;
    } catch(e) {
        console.error("Failed to load portfolio strategies:", e);
    }
}

(async () => {
    document.querySelectorAll(".period-tab[data-es]").forEach((button) =>
        button.classList.toggle("active", button.dataset.es === _equityScale)
    );
    await loadPortfolio();
    loadMetrics();
    loadEquity();
    loadCalendar();
    loadPortfolioStrategies();
})();
