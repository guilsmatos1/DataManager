function benchmarkStatusText(benchmark) {
    if (benchmark.last_error) return benchmark.last_error;
    if (benchmark.last_synced_at) return `Synced ${formatDateTime(benchmark.last_synced_at)}`;
    return "Not synced yet";
}

function fillBenchmarkForm(row) {
    document.getElementById("benchmark-name").value = row.asset;
    document.getElementById("benchmark-source").value = row.source;
    document.getElementById("benchmark-asset").value = row.asset;
    document.getElementById("benchmark-timeframe").value = row.timeframe;
    const status = document.getElementById("benchmarks-status");
    status.textContent = `Loaded ${row.source}/${row.asset}/${row.timeframe} into the form.`;
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function renderBenchmarks(list) {
    const container = document.getElementById("benchmarks-table");
    if (!list.length) {
        container.innerHTML = '<p class="empty-state">No benchmarks configured.</p>';
        return;
    }

    const rows = list.map((b) => `
        <tr>
            <td>${b.name}</td>
            <td class="mono">${b.source}</td>
            <td class="mono">${b.asset}</td>
            <td class="mono">${b.timeframe}</td>
            <td>${b.local_points || 0}</td>
            <td>${b.is_default ? '<span class="badge badge-live">Default</span>' : '<span class="badge badge-neutral">Optional</span>'}</td>
            <td>${benchmarkStatusText(b)}</td>
            <td style="display:flex;gap:0.5rem">
                <button class="btn btn-ghost btn-sm" onclick="syncBenchmark(${b.id})">Sync</button>
                <button class="btn btn-ghost btn-sm" onclick="setDefaultBenchmark(${b.id})">Set Default</button>
                <button class="btn btn-sm" style="background:rgba(239,68,68,0.15);color:#ef4444;border:1px solid rgba(239,68,68,0.3)" onclick='deleteBenchmark(${b.id}, ${JSON.stringify(b.name)})'>Delete</button>
            </td>
        </tr>
    `).join("");

    container.innerHTML = `<table class="data-table">
        <thead><tr><th>Name</th><th>Source</th><th>Asset</th><th>TF</th><th>Points</th><th>Default</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody>${rows}</tbody>
    </table>`;
}

function renderRemoteBenchmarks(list) {
    const container = document.getElementById("benchmarks-remote-table");
    if (!list.length) {
        container.innerHTML = '<p class="empty-state">No remote databases found.</p>';
        return;
    }

    const rows = list.map((row) => `
        <tr>
            <td class="mono">${row.source}</td>
            <td class="mono">${row.asset}</td>
            <td class="mono">${row.timeframe}</td>
            <td>${row.rows ?? "—"}</td>
            <td>${row.last_timestamp || "—"}</td>
            <td>
                <button
                    class="btn btn-ghost btn-sm benchmark-use-btn"
                    data-source="${escapeHtml(row.source)}"
                    data-asset="${escapeHtml(row.asset)}"
                    data-timeframe="${escapeHtml(row.timeframe)}"
                >
                    Use
                </button>
            </td>
        </tr>
    `).join("");

    container.innerHTML = `<table class="data-table">
        <thead><tr><th>Source</th><th>Asset</th><th>TF</th><th>Rows</th><th>Last Timestamp</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
    </table>`;
}

function renderBenchmarksUnavailable() {
    document.getElementById("benchmarks-table").innerHTML =
        '<p class="empty-state">No benchmarks configured.</p>';
}

function renderRemoteBenchmarksUnavailable() {
    document.getElementById("benchmarks-remote-table").innerHTML =
        '<p class="empty-state">No remote databases found.</p>';
}

function isDataManagerUnavailable(error) {
    return String(error?.message || "").includes("HTTP 503: DataManager service is unavailable");
}

async function loadBenchmarksPage() {
    const status = document.getElementById("benchmarks-status");
    status.textContent = "";

    const [benchmarksResult, remoteResult] = await Promise.allSettled([
        fetchJson("/api/benchmarks"),
        fetchJson("/api/benchmarks/available-from-datamanager"),
    ]);

    if (benchmarksResult.status === "fulfilled") {
        renderBenchmarks(benchmarksResult.value);
    } else {
        renderBenchmarksUnavailable();
        status.textContent = `Error: ${benchmarksResult.reason.message}`;
    }

    if (remoteResult.status === "fulfilled") {
        renderRemoteBenchmarks(remoteResult.value);
    } else {
        renderRemoteBenchmarksUnavailable();
        if (isDataManagerUnavailable(remoteResult.reason)) {
            if (!status.textContent) {
                status.textContent = "DataManager unavailable. Showing local benchmarks only.";
            }
        } else if (!status.textContent) {
            status.textContent = `Error: ${remoteResult.reason.message}`;
        }
    }
}

async function createBenchmark() {
    const status = document.getElementById("benchmarks-status");
    status.textContent = "Saving...";
    const payload = {
        name: document.getElementById("benchmark-name").value.trim(),
        source: document.getElementById("benchmark-source").value.trim(),
        asset: document.getElementById("benchmark-asset").value.trim(),
        timeframe: document.getElementById("benchmark-timeframe").value.trim(),
        description: document.getElementById("benchmark-description").value.trim() || null,
        enabled: document.getElementById("benchmark-enabled").checked,
        is_default: document.getElementById("benchmark-default").checked,
    };

    try {
        await fetchJson("/api/benchmarks", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        status.textContent = "Benchmark added.";
        loadBenchmarksPage();
    } catch (e) {
        status.textContent = `Error: ${e.message}`;
    }
}

async function syncBenchmark(id) {
    const status = document.getElementById("benchmarks-status");
    status.textContent = "Syncing benchmark...";
    try {
        const result = await fetchJson(`/api/benchmarks/${id}/sync`, { method: "POST" });
        status.textContent = result.message || "Benchmark synced.";
        loadBenchmarksPage();
    } catch (e) {
        status.textContent = `Error: ${e.message}`;
    }
}

async function setDefaultBenchmark(id) {
    const status = document.getElementById("benchmarks-status");
    status.textContent = "Updating default benchmark...";
    try {
        await fetchJson(`/api/benchmarks/${id}/set-default`, { method: "POST" });
        status.textContent = "Default benchmark updated.";
        loadBenchmarksPage();
    } catch (e) {
        status.textContent = `Error: ${e.message}`;
    }
}

async function deleteBenchmark(id, name) {
    const benchmarkName = name || `#${id}`;
    const confirmed = await showConfirmModal(
        "Delete Benchmark",
        `Delete benchmark <strong>"${benchmarkName}"</strong>?<br><br>This will permanently remove the benchmark and all synced price history.`,
        { confirmLabel: "Delete", confirmClass: "btn-danger" }
    );
    if (!confirmed) return;

    const status = document.getElementById("benchmarks-status");
    status.textContent = "Deleting benchmark...";
    try {
        await fetchJson(`/api/benchmarks/${id}`, { method: "DELETE" });
        status.textContent = "Benchmark deleted.";
        loadBenchmarksPage();
    } catch (e) {
        status.textContent = `Error: ${e.message}`;
    }
}

document.addEventListener("click", (event) => {
    const button = event.target.closest(".benchmark-use-btn");
    if (!button) return;
    fillBenchmarkForm({
        source: button.dataset.source || "",
        asset: button.dataset.asset || "",
        timeframe: button.dataset.timeframe || "",
    });
});

document.addEventListener("DOMContentLoaded", loadBenchmarksPage);
