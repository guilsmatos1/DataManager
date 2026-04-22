/* DataManager Dashboard — global utilities */

/* ── Button loading state helpers ── */
function btnLoading(btn) {
    if (!btn) return;
    btn.disabled = true;
    btn.classList.add("btn-loading");
}
function btnReset(btn) {
    if (!btn) return;
    btn.disabled = false;
    btn.classList.remove("btn-loading");
}

/* ── Mobile nav toggle ── */
function toggleNav() {
    document.querySelector(".nav-links").classList.toggle("nav-open");
}

function toggleTheme() {
    const html = document.documentElement;
    const current = html.getAttribute("data-theme");
    const next = current === "dark" ? "light" : "dark";
    html.setAttribute("data-theme", next);
    localStorage.setItem("dm-theme", next);
    updateThemeIcons(next);
}

function updateThemeIcons(theme) {
    const dark = document.getElementById("theme-icon-dark");
    const light = document.getElementById("theme-icon-light");
    if (dark && light) {
        dark.style.display = theme === "dark" ? "block" : "none";
        light.style.display = theme === "light" ? "block" : "none";
    }
}

document.addEventListener("DOMContentLoaded", function () {
    const theme = localStorage.getItem("dm-theme") || "dark";
    updateThemeIcons(theme);

    // Reconnect to any tasks that were running before page navigation
    fetch("/ui/api/tasks/active")
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (tasks) {
            tasks.forEach(function (t) {
                TaskProgress.subscribe(t.task_id, t.description, null);
            });
        })
        .catch(function () {});

    // HTMX error recovery — show inline retry on failed table loads
    document.body.addEventListener("htmx:responseError", handleHtmxError);
    document.body.addEventListener("htmx:sendError", handleHtmxError);

    // Warn before leaving with active tasks
    window.addEventListener("beforeunload", function (e) {
        if (Object.keys(TaskProgress._sources).length > 0) {
            e.preventDefault();
        }
    });
});

/* Toast notifications */
function showToast(title, message, level) {
    level = level || "info";
    const container = document.getElementById("toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = "toast toast-" + level;
    toast.innerHTML =
        '<div class="toast-header">' +
        '<span class="toast-title">' + escapeHtml(title) + "</span>" +
        '<button class="toast-close" onclick="dismissToast(this)">&times;</button>' +
        "</div>" +
        '<div class="toast-message">' + escapeHtml(message) + "</div>";

    container.appendChild(toast);

    setTimeout(function () {
        dismissToast(toast.querySelector(".toast-close"));
    }, 5000);
}

function dismissToast(btn) {
    const toast = btn.closest ? btn.closest(".toast") : btn.parentElement.parentElement;
    if (!toast) return;
    toast.classList.add("toast-hiding");
    setTimeout(function () {
        toast.remove();
    }, 200);
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

/* Confirm modal */
function showConfirm(title, message, onConfirm) {
    const overlay = document.createElement("div");
    overlay.className = "confirm-modal-overlay";
    overlay.innerHTML =
        '<div class="confirm-modal">' +
        '<div class="confirm-modal-title">' + escapeHtml(title) + "</div>" +
        '<div class="confirm-modal-body">' + escapeHtml(message) + "</div>" +
        '<div class="confirm-modal-actions">' +
        '<button class="btn btn-ghost" id="confirm-cancel">Cancel</button>' +
        '<button class="btn btn-danger" id="confirm-ok">Confirm</button>' +
        "</div></div>";

    document.body.appendChild(overlay);

    overlay.querySelector("#confirm-cancel").onclick = function () {
        overlay.remove();
    };
    overlay.querySelector("#confirm-ok").onclick = function () {
        overlay.remove();
        onConfirm();
    };
    overlay.addEventListener("click", function (e) {
        if (e.target === overlay) overlay.remove();
    });
}

/* ── Table Refresh Helper ── */
function refreshTable(selector) {
    var el = document.querySelector(selector);
    if (!el) return;
    var url = el.getAttribute("hx-get");
    if (url) {
        htmx.ajax("GET", url, { target: selector, swap: "innerHTML" });
    }
}

/* ── HTMX Error Recovery ── */
function handleHtmxError(event) {
    var target = event.detail.target || (event.detail.elt && event.detail.elt);
    if (!target) return;

    // Only inject retry row inside table bodies
    var tbody = target.closest("tbody");
    if (!tbody) {
        showToast("Error", "Failed to load data. Please try again.", "error");
        return;
    }

    var colCount = 7;
    var headerRow = tbody.closest("table");
    if (headerRow) {
        var ths = headerRow.querySelectorAll("thead th");
        if (ths.length > 0) colCount = ths.length;
    }

    var retryUrl = target.getAttribute("hx-get") || tbody.getAttribute("hx-get") || "";

    tbody.innerHTML =
        '<tr class="htmx-error-row"><td colspan="' + colCount + '">' +
        'Failed to load data.' +
        (retryUrl
            ? ' <button class="btn btn-sm btn-ghost" onclick="htmxRetry(this, \'' + escapeHtml(retryUrl) + '\')">Retry</button>'
            : '') +
        '</td></tr>';
}

function htmxRetry(btn, url) {
    var tbody = btn.closest("tbody");
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:2rem;">Loading...</td></tr>';
    htmx.ajax("GET", url, { target: tbody, swap: "innerHTML" });
}


var TaskProgress = {
    _sources: {},  // task_id -> EventSource

    subscribe: function (taskId, description, tableSelector, onDone) {
        if (this._sources[taskId]) return;  // already subscribed

        this._ensurePanel();
        this._addBar(taskId, description);

        var self = this;
        var es = new EventSource("/ui/api/tasks/" + taskId + "/progress");
        this._sources[taskId] = es;

        es.onmessage = function (event) {
            var data = JSON.parse(event.data);

            if (data.status === "not_found") {
                es.close();
                self._removeBar(taskId);
                if (onDone) onDone("error");
                return;
            }

            self._updateBar(taskId, data);

            if (data.status === "completed") {
                es.close();
                delete self._sources[taskId];
                self._finishBar(taskId, "success");
                showToast("Completed", data.message || description, "success");
                if (tableSelector) refreshTable(tableSelector);
                if (onDone) onDone("success");
            } else if (data.status === "failed") {
                es.close();
                delete self._sources[taskId];
                self._finishBar(taskId, "error");
                showToast("Error", data.message || "Operation failed", "error");
                if (onDone) onDone("error");
            }
        };

        es.onerror = function () {
            es.close();
            delete self._sources[taskId];
            self._removeBar(taskId);
            if (onDone) onDone("error");
        };
    },

    _ensurePanel: function () {
        if (!document.getElementById("progress-panel")) {
            var panel = document.createElement("div");
            panel.id = "progress-panel";
            panel.className = "progress-panel";
            document.body.appendChild(panel);
        }
    },

    _addBar: function (taskId, description) {
        var panel = document.getElementById("progress-panel");
        if (!panel) return;
        var el = document.createElement("div");
        el.id = "task-" + taskId;
        el.className = "progress-item";
        el.innerHTML =
            '<div class="progress-info">' +
            '<span class="progress-desc">' + escapeHtml(description) + "</span>" +
            '<span class="progress-pct">0%</span>' +
            "</div>" +
            '<div class="progress-track">' +
            '<div class="progress-fill" style="width:0%"></div>' +
            "</div>";
        panel.appendChild(el);
    },

    _updateBar: function (taskId, data) {
        var el = document.getElementById("task-" + taskId);
        if (!el) return;
        var pct = Math.round((data.progress || 0) * 100);
        el.querySelector(".progress-pct").textContent = pct + "%";
        el.querySelector(".progress-fill").style.width = pct + "%";
        if (data.description) {
            el.querySelector(".progress-desc").textContent = data.description;
        }
    },

    _finishBar: function (taskId, level) {
        var el = document.getElementById("task-" + taskId);
        if (!el) return;
        el.classList.add("progress-" + level);
        el.querySelector(".progress-fill").style.width = "100%";
        el.querySelector(".progress-pct").textContent = "100%";
        var self = this;
        setTimeout(function () {
            el.classList.add("progress-hiding");
            setTimeout(function () {
                el.remove();
                self._removePanelIfEmpty();
            }, 300);
        }, 1500);
    },

    _removeBar: function (taskId) {
        var el = document.getElementById("task-" + taskId);
        if (el) el.remove();
        this._removePanelIfEmpty();
    },

    _removePanelIfEmpty: function () {
        var panel = document.getElementById("progress-panel");
        if (panel && panel.children.length === 0) panel.remove();
    }
};
