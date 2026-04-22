/* DataManager Dashboard — Assets page */

var _activeAssetOps = new Set();

function showDownloadForm() {
    document.getElementById("download-form").style.display = "block";
}

function hideDownloadForm() {
    document.getElementById("download-form").style.display = "none";
}

async function submitDownload(event) {
    event.preventDefault();
    if (_activeAssetOps.has("download")) return false;
    _activeAssetOps.add("download");

    var form = document.getElementById("download-data-form");
    var submitBtn = form.querySelector('button[type="submit"]');
    btnLoading(submitBtn);
    var fd = new FormData(form);

    var resp = await dmPost("/ui/api/download", fd);
    if (resp) {
        var data = await resp.json();
        var tids = data.task_ids || [];
        if (tids.length === 0) { _activeAssetOps.delete("download"); btnReset(submitBtn); }
        tids.forEach(function (tid) {
            TaskProgress.subscribe(tid, data.message, "#asset-table-body", function () {
                _activeAssetOps.delete("download");
                btnReset(submitBtn);
            });
        });
        hideDownloadForm();
        form.reset();
    } else {
        _activeAssetOps.delete("download");
        btnReset(submitBtn);
    }
    return false;
}

async function updateAsset(source, asset, timeframe, btn) {
    var key = "update:" + source + ":" + asset + ":" + timeframe;
    if (_activeAssetOps.has(key)) return;
    _activeAssetOps.add(key);
    btnLoading(btn);

    var fd = formDataFromObj({ source: source, asset: asset, timeframe: timeframe });
    var resp = await dmPost("/ui/api/update", fd);
    if (resp) {
        var data = await resp.json();
        var tids = data.task_ids || [];
        if (tids.length === 0) { _activeAssetOps.delete(key); btnReset(btn); return; }
        tids.forEach(function (tid) {
            TaskProgress.subscribe(tid, data.message, "#asset-table-body", function () {
                _activeAssetOps.delete(key);
                btnReset(btn);
            });
        });
    } else {
        _activeAssetOps.delete(key);
        btnReset(btn);
    }
}

function confirmDeleteAsset(source, asset, timeframe) {
    showConfirm(
        "Delete Asset Data",
        "Delete " + asset + " (" + timeframe + ") from " + source + "? This cannot be undone.",
        function () { doDeleteAsset(source, asset, timeframe); }
    );
}

async function doDeleteAsset(source, asset, timeframe) {
    var fd = formDataFromObj({ source: source, asset: asset, timeframe: timeframe });
    var resp = await dmPost("/ui/api/delete", fd);
    if (resp) {
        var html = await resp.text();
        var tmp = document.createElement("div");
        tmp.innerHTML = html;
        tmp.querySelectorAll("script").forEach(function (s) { eval(s.textContent); });
        refreshTable("#asset-table-body");
    }
}

/* ── Bulk Operations ── */

function toggleSelectAll(master, checkboxClass) {
    var boxes = document.querySelectorAll(checkboxClass);
    boxes.forEach(function (cb) { cb.checked = master.checked; });
    updateBulkBar(checkboxClass, "#bulk-actions", "#bulk-count", "#select-all-assets");
}

function updateBulkBar(checkboxClass, barSelector, countSelector, masterSelector) {
    var boxes = document.querySelectorAll(checkboxClass);
    var checked = document.querySelectorAll(checkboxClass + ":checked");
    var bar = document.querySelector(barSelector);
    var countEl = document.querySelector(countSelector);
    var master = document.querySelector(masterSelector);

    if (checked.length > 0) {
        bar.style.display = "flex";
        countEl.textContent = checked.length + " selected";
    } else {
        bar.style.display = "none";
    }
    if (master) master.checked = checked.length === boxes.length && boxes.length > 0;
}

function getSelectedAssets() {
    var checked = document.querySelectorAll(".asset-select:checked");
    var items = [];
    checked.forEach(function (cb) {
        items.push({
            source: cb.getAttribute("data-source"),
            asset: cb.getAttribute("data-asset"),
            timeframe: cb.getAttribute("data-timeframe")
        });
    });
    return items;
}

function bulkUpdate() {
    var items = getSelectedAssets();
    if (items.length === 0) return;
    items.forEach(function (item) {
        updateAsset(item.source, item.asset, item.timeframe, null);
    });
    bulkClear();
}

function bulkDelete() {
    var items = getSelectedAssets();
    if (items.length === 0) return;
    showConfirm(
        "Delete " + items.length + " Asset(s)",
        "Delete " + items.length + " selected asset(s)? This cannot be undone.",
        function () {
            items.forEach(function (item) {
                doDeleteAsset(item.source, item.asset, item.timeframe);
            });
            bulkClear();
        }
    );
}

function bulkClear() {
    document.querySelectorAll(".asset-select").forEach(function (cb) { cb.checked = false; });
    var master = document.getElementById("select-all-assets");
    if (master) master.checked = false;
    document.getElementById("bulk-actions").style.display = "none";
}
