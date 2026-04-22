/* DataManager Dashboard — FRED Series page */

var _activeSeriesOps = new Set();

function showSeriesForm() {
    document.getElementById("series-form").style.display = "block";
}

function hideSeriesForm() {
    document.getElementById("series-form").style.display = "none";
}

async function submitSeriesDownload(event) {
    event.preventDefault();
    if (_activeSeriesOps.has("download")) return false;
    _activeSeriesOps.add("download");

    var form = document.getElementById("series-download-form");
    var submitBtn = form.querySelector('button[type="submit"]');
    btnLoading(submitBtn);
    var fd = new FormData(form);

    var resp = await dmPost("/ui/api/series/download", fd);
    if (resp) {
        var data = await resp.json();
        var tids = data.task_ids || [];
        if (tids.length === 0) { _activeSeriesOps.delete("download"); btnReset(submitBtn); }
        tids.forEach(function (tid) {
            TaskProgress.subscribe(tid, data.message, "#series-table-body", function () {
                _activeSeriesOps.delete("download");
                btnReset(submitBtn);
            });
        });
        hideSeriesForm();
        form.reset();
    } else {
        _activeSeriesOps.delete("download");
        btnReset(submitBtn);
    }
    return false;
}

async function updateSeries(source, seriesId, btn) {
    var key = "update:" + source + ":" + seriesId;
    if (_activeSeriesOps.has(key)) return;
    _activeSeriesOps.add(key);
    btnLoading(btn);

    var fd = formDataFromObj({ source: source, series_id: seriesId });
    var resp = await dmPost("/ui/api/series/update", fd);
    if (resp) {
        var data = await resp.json();
        var tids = data.task_ids || [];
        if (tids.length === 0) { _activeSeriesOps.delete(key); btnReset(btn); return; }
        tids.forEach(function (tid) {
            TaskProgress.subscribe(tid, data.message, "#series-table-body", function () {
                _activeSeriesOps.delete(key);
                btnReset(btn);
            });
        });
    } else {
        _activeSeriesOps.delete(key);
        btnReset(btn);
    }
}

function confirmDeleteSeries(source, seriesId) {
    showConfirm(
        "Delete Series",
        "Delete series " + seriesId + " from " + source + "? This cannot be undone.",
        function () { doDeleteSeries(source, seriesId); }
    );
}

async function doDeleteSeries(source, seriesId) {
    var fd = formDataFromObj({ source: source, series_id: seriesId });
    var resp = await dmPost("/ui/api/series/delete", fd);
    if (resp) {
        var html = await resp.text();
        var tmp = document.createElement("div");
        tmp.innerHTML = html;
        tmp.querySelectorAll("script").forEach(function (s) { eval(s.textContent); });
        refreshTable("#series-table-body");
    }
}

/* ── Bulk Operations ── */

function toggleSelectAllSeries(master) {
    var boxes = document.querySelectorAll(".series-select");
    boxes.forEach(function (cb) { cb.checked = master.checked; });
    updateSeriesBulkBar();
}

function updateSeriesBulkBar() {
    var boxes = document.querySelectorAll(".series-select");
    var checked = document.querySelectorAll(".series-select:checked");
    var bar = document.getElementById("series-bulk-actions");
    var countEl = document.getElementById("series-bulk-count");
    var master = document.getElementById("select-all-series");

    if (checked.length > 0) {
        bar.style.display = "flex";
        countEl.textContent = checked.length + " selected";
    } else {
        bar.style.display = "none";
    }
    if (master) master.checked = checked.length === boxes.length && boxes.length > 0;
}

function getSelectedSeries() {
    var checked = document.querySelectorAll(".series-select:checked");
    var items = [];
    checked.forEach(function (cb) {
        items.push({
            source: cb.getAttribute("data-source"),
            series_id: cb.getAttribute("data-series-id")
        });
    });
    return items;
}

function bulkUpdateSeries() {
    var items = getSelectedSeries();
    if (items.length === 0) return;
    items.forEach(function (item) {
        updateSeries(item.source, item.series_id, null);
    });
    bulkClearSeries();
}

function bulkDeleteSeries() {
    var items = getSelectedSeries();
    if (items.length === 0) return;
    showConfirm(
        "Delete " + items.length + " Series",
        "Delete " + items.length + " selected series? This cannot be undone.",
        function () {
            items.forEach(function (item) {
                doDeleteSeries(item.source, item.series_id);
            });
            bulkClearSeries();
        }
    );
}

function bulkClearSeries() {
    document.querySelectorAll(".series-select").forEach(function (cb) { cb.checked = false; });
    var master = document.getElementById("select-all-series");
    if (master) master.checked = false;
    document.getElementById("series-bulk-actions").style.display = "none";
}
