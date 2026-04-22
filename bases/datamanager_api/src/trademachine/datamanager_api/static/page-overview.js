/* DataManager Dashboard — Overview page charts */

function initOverviewCharts(sourceDistribution, coverageData) {
    var style = getComputedStyle(document.documentElement);
    var textMuted = style.getPropertyValue("--text-muted").trim();
    var border = style.getPropertyValue("--border").trim();
    var colors = [
        style.getPropertyValue("--accent").trim(),
        style.getPropertyValue("--green").trim(),
        style.getPropertyValue("--yellow").trim(),
        style.getPropertyValue("--purple").trim(),
        style.getPropertyValue("--red").trim(),
        style.getPropertyValue("--cyan").trim()
    ];

    /* Source distribution doughnut */
    var srcCanvas = document.getElementById("chart-sources");
    if (srcCanvas && sourceDistribution) {
        var labels = Object.keys(sourceDistribution);
        var data = Object.values(sourceDistribution);

        if (labels.length > 0) {
            new Chart(srcCanvas, {
                type: "doughnut",
                data: {
                    labels: labels,
                    datasets: [{
                        data: data,
                        backgroundColor: colors.slice(0, labels.length),
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: "bottom",
                            labels: { color: textMuted, font: { size: 12 }, padding: 16 }
                        }
                    },
                    cutout: "65%"
                }
            });
        }
    }

    /* Coverage bar chart */
    var covCanvas = document.getElementById("chart-coverage");
    if (covCanvas && coverageData) {
        var covLabels = Object.keys(coverageData);
        var covData = Object.values(coverageData);

        if (covLabels.length > 0) {
            new Chart(covCanvas, {
                type: "bar",
                data: {
                    labels: covLabels,
                    datasets: [{
                        label: "Assets",
                        data: covData,
                        backgroundColor: colors.slice(0, covLabels.length),
                        borderRadius: 4,
                        barPercentage: 0.6
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        x: {
                            ticks: { color: textMuted },
                            grid: { color: border }
                        },
                        y: {
                            beginAtZero: true,
                            ticks: { color: textMuted, precision: 0 },
                            grid: { color: border }
                        }
                    }
                }
            });
        }
    }
}
