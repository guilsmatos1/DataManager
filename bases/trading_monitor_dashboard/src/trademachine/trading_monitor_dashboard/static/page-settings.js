    const API_KEY = document.querySelector('meta[name="api-key"]').content;

    // ── Tab Management ───────────────────────────────────────────────────────

    function showSettingsTab(tabId) {
        // Update tab buttons
        document.querySelectorAll('.section-tab').forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('onclick').includes(tabId));
        });
        // Update content sections
        document.querySelectorAll('.settings-tab-content').forEach(section => {
            section.style.display = section.id === `tab-${tabId}` ? 'block' : 'none';
        });
        // Store preference
        localStorage.setItem('tm-settings-tab', tabId);
    }

    // Restore last active tab
    document.addEventListener('DOMContentLoaded', () => {
        const lastTab = localStorage.getItem('tm-settings-tab');
        if (lastTab) {
            // Check if lastTab matches old PT keys and map them
            const tabMapping = {
                'geral': 'general',
                'integracoes': 'integrations',
                'importacao': 'import',
                'visualizacao': 'visualization',
                'sistema': 'system'
            };
            showSettingsTab(tabMapping[lastTab] || lastTab);
        }
    });

    // ── Telegram & Global Settings ───────────────────────────────────────────

    async function loadSettings() {
        try {
            const response = await fetch('/api/settings/telegram', {
                headers: { 'X-API-Key': API_KEY }
            });
            if (response.ok) {
                const data = await response.json();
                const botTokenInput = document.getElementById('bot_token');
                const chatIdInput = document.getElementById('chat_id');
                const botTokenHint = document.getElementById('bot_token_hint');
                const chatIdHint = document.getElementById('chat_id_hint');

                botTokenInput.value = data.bot_token || '';
                chatIdInput.value = data.chat_id || '';
                botTokenInput.placeholder = 'e.g.: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz';
                chatIdInput.placeholder = 'e.g.: -100123456789';

                botTokenHint.textContent = data.bot_token_configured
                    ? 'Saved token loaded from settings.'
                    : 'No token saved yet.';
                chatIdHint.textContent = data.chat_id_configured
                    ? 'Saved chat ID loaded from settings.'
                    : 'No chat ID saved yet.';

                document.getElementById('notify_closed_trades').checked = Boolean(data.notify_closed_trades);
                document.getElementById('notify_system_errors').checked = Boolean(data.notify_system_errors);
                document.getElementById('var_95_threshold').value = data.var_95_threshold || '';
                document.getElementById('default_initial_balance').value = data.default_initial_balance || 100000;
                document.getElementById('real_page_mode').value = data.real_page_mode || 'real';
            }
        } catch (error) {
            console.error('Error loading settings:', error);
        }
    }

    async function saveSettings(event) {
        event.preventDefault();

        // Determine which status spans to update
        const statuses = ['settings-status', 'general-status', 'visualization-status'];
        statuses.forEach(sId => {
            const el = document.getElementById(sId);
            if (el) {
                el.innerText = 'Saving...';
                el.style.color = 'var(--text-muted)';
                el.style.display = 'inline-block';
            }
        });

        const payload = {
            bot_token: document.getElementById('bot_token').value,
            chat_id: document.getElementById('chat_id').value,
            notify_closed_trades: document.getElementById('notify_closed_trades').checked,
            notify_system_errors: document.getElementById('notify_system_errors').checked,
            var_95_threshold: parseFloat(document.getElementById('var_95_threshold').value) || 0,
            default_initial_balance: parseFloat(document.getElementById('default_initial_balance').value) || 100000,
            real_page_mode: document.getElementById('real_page_mode').value || 'real'
        };

        try {
            const response = await fetch('/api/settings/telegram', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-API-Key': API_KEY
                },
                body: JSON.stringify(payload)
            });

            if (response.ok) {
                statuses.forEach(sId => {
                    const el = document.getElementById(sId);
                    if (el) {
                        el.innerText = '✅ Saved!';
                        el.style.color = 'var(--green)';
                        setTimeout(() => { el.style.display = 'none'; }, 3000);
                    }
                });
            } else {
                throw new Error('Failed to save');
            }
        } catch (error) {
            statuses.forEach(sId => {
                const el = document.getElementById(sId);
                if (el) {
                    el.innerText = '❌ Error saving.';
                    el.style.color = 'var(--red)';
                }
            });
        }
    }

    async function testTelegram() {
        const btn = document.getElementById('test-telegram-btn');
        const status = document.getElementById('test-telegram-status');
        btn.disabled = true;
        status.textContent = 'Sending...';
        status.style.color = 'var(--text-muted)';
        try {
            const res = await fetch('/api/settings/telegram/test', {
                method: 'POST',
                headers: { 'X-API-Key': API_KEY }
            });
            if (res.ok) {
                status.textContent = '✅ Message sent!';
                status.style.color = 'var(--green)';
            } else {
                const err = await res.json();
                status.textContent = '❌ ' + (err.detail || 'Error');
                status.style.color = 'var(--red)';
            }
        } catch(e) {
            status.textContent = '❌ Connection error';
            status.style.color = 'var(--red)';
        } finally {
            btn.disabled = false;
        }
    }

    document.addEventListener('DOMContentLoaded', loadSettings);

    // ── DataManager Settings ────────────────────────────────────────────────

    async function loadDmSettings() {
        try {
            const res = await fetch('/api/settings/datamanager', { headers: { 'X-API-Key': API_KEY } });
            if (res.ok) {
                const data = await res.json();
                document.getElementById('dm_url').value = data.url || '';
                const keyInput = document.getElementById('dm_api_key');
                keyInput.value = data.api_key || '';
                keyInput.placeholder = 'Enter API key';
                document.getElementById('dm_timeout').value = data.timeout || 30;
            }
        } catch (e) { console.error('Error loading DM settings:', e); }
    }

    async function saveDmSettings(event) {
        event.preventDefault();
        const btn = document.getElementById('dm-save-btn');
        const status = document.getElementById('dm-status');
        btn.disabled = true; btn.innerText = 'Saving...'; status.style.display = 'none';

        try {
            const res = await fetch('/api/settings/datamanager', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
                body: JSON.stringify({
                    url: document.getElementById('dm_url').value,
                    api_key: document.getElementById('dm_api_key').value,
                    timeout: parseFloat(document.getElementById('dm_timeout').value) || 30,
                })
            });
            if (res.ok) {
                status.innerText = 'Settings saved!';
                status.style.color = 'var(--green)';
            } else { throw new Error('Failed to save'); }
        } catch (e) {
            status.innerText = 'Error saving.';
            status.style.color = 'var(--red)';
        } finally {
            status.style.display = 'block';
            btn.disabled = false; btn.innerText = 'Save';
        }
    }

    async function testDmConnection() {
        const btn = document.getElementById('dm-test-btn');
        const status = document.getElementById('dm-test-status');
        btn.disabled = true;
        status.textContent = 'Testing...';
        status.style.color = 'var(--text-muted)';
        try {
            const res = await fetch('/api/settings/datamanager/test', {
                method: 'POST', headers: { 'X-API-Key': API_KEY }
            });
            if (res.ok) {
                const data = await res.json();
                status.textContent = `✅ Connected! ${data.databases_count} database(s) found.`;
                status.style.color = 'var(--green)';
            } else {
                const err = await res.json();
                status.textContent = '❌ ' + (err.detail || 'Error');
                status.style.color = 'var(--red)';
            }
        } catch (e) {
            status.textContent = '❌ Connection error';
            status.style.color = 'var(--red)';
        } finally { btn.disabled = false; }
    }

    document.addEventListener('DOMContentLoaded', loadDmSettings);

    // ── Benchmark Auto-Sync Scheduler ────────────────────────────────────────

    async function loadBschedSettings() {
        try {
            const res = await fetch('/api/settings/benchmark-scheduler', { headers: { 'X-API-Key': API_KEY } });
            if (res.ok) {
                const data = await res.json();
                document.getElementById('bsched_enabled').checked = Boolean(data.enabled);
                document.getElementById('bsched_interval_hours').value = data.interval_hours ?? 24;
            }
        } catch (e) { console.error('Error loading benchmark scheduler settings:', e); }
    }

    async function saveBschedSettings() {
        const btn = document.getElementById('bsched-save-btn');
        const status = document.getElementById('bsched-status');
        btn.disabled = true; btn.innerText = 'Saving...'; status.style.display = 'none';
        try {
            const res = await fetch('/api/settings/benchmark-scheduler', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
                body: JSON.stringify({
                    enabled: document.getElementById('bsched_enabled').checked,
                    interval_hours: parseFloat(document.getElementById('bsched_interval_hours').value) || 24,
                })
            });
            if (res.ok) {
                status.innerText = 'Settings saved!';
                status.style.color = 'var(--green)';
            } else { throw new Error('Failed to save'); }
        } catch (e) {
            status.innerText = 'Error saving.';
            status.style.color = 'var(--red)';
        } finally {
            status.style.display = 'block';
            btn.disabled = false; btn.innerText = 'Save';
        }
    }

    async function syncAllBenchmarksNow() {
        const btn = document.getElementById('bsched-sync-btn');
        const status = document.getElementById('bsched-sync-status');
        btn.disabled = true;
        status.textContent = 'Syncing...';
        status.style.color = 'var(--text-muted)';
        try {
            const res = await fetch('/api/benchmarks/sync-all', {
                method: 'POST', headers: { 'X-API-Key': API_KEY }
            });
            if (res.ok) {
                const data = await res.json();
                status.textContent = `✅ ${data.synced} synced, ${data.skipped} skipped, ${data.failed} failed.`;
                status.style.color = data.failed > 0 ? 'var(--yellow, #f59e0b)' : 'var(--green)';
            } else {
                const err = await res.json();
                status.textContent = '❌ ' + (err.detail || 'Error');
                status.style.color = 'var(--red)';
            }
        } catch (e) {
            status.textContent = '❌ Connection error';
            status.style.color = 'var(--red)';
        } finally { btn.disabled = false; }
    }

    document.addEventListener('DOMContentLoaded', loadBschedSettings);

    // ── CSV Mapping ──────────────────────────────────────────────────────────

    let _magicMapping = {}; // { filename: magicNumber }

    function csvMappingLoad(input) {
        const file = input.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = function(e) {
            const lines = e.target.result.split(/\r?\n/).filter(l => l.trim());
            if (!lines.length) return;
            // detect separator from first line
            const firstLine = lines[0];
            const sep = firstLine.includes(';') ? ';' : ',';
            // detect if first line is a header (contains non-numeric text in col 1)
            const firstCols = firstLine.split(sep).map(c => c.trim().toLowerCase());
            const hasHeader = firstCols.includes('file') || firstCols.includes('arquivo') || firstCols.includes('magicnumber');
            // determine column indices
            let iArq = 0, iMag = 1; // default: col 0 = file, col 1 = magic
            let startLine = 0;
            if (hasHeader) {
                iArq = firstCols.indexOf('file') !== -1 ? firstCols.indexOf('file') : (firstCols.indexOf('arquivo') !== -1 ? firstCols.indexOf('arquivo') : 0);
                iMag = firstCols.indexOf('magicnumber') !== -1 ? firstCols.indexOf('magicnumber') : 1;
                startLine = 1;
            }
            _magicMapping = {};
            const tbody = document.getElementById('csv-mapping-tbody');
            tbody.innerHTML = '';
            for (let i = startLine; i < lines.length; i++) {
                const parts = lines[i].split(sep);
                const arq = parts[iArq]?.trim();
                const mag = parts[iMag]?.trim();
                if (arq && mag) {
                    // store with .html extension always, so lookup works regardless of input format
                    const key = arq.toLowerCase().endsWith('.html') ? arq : arq + '.html';
                    _magicMapping[key] = mag;
                    const tr = document.createElement('tr');
                    tr.innerHTML = `<td style="font-size:0.82rem">${key}</td><td style="font-size:0.82rem">${mag}</td>`;
                    tbody.appendChild(tr);
                }
            }
            const count = Object.keys(_magicMapping).length;
            document.getElementById('csv-mapping-status').textContent = `✅ ${count} mapping(s) loaded`;
            document.getElementById('csv-mapping-preview').style.display = count ? 'block' : 'none';
            document.getElementById('csv-mapping-clear').style.display = 'inline-flex';
        };
        reader.readAsText(file);
    }

    function csvMappingClear() {
        _magicMapping = {};
        document.getElementById('csv-mapping-status').textContent = '';
        document.getElementById('csv-mapping-preview').style.display = 'none';
        document.getElementById('csv-mapping-clear').style.display = 'none';
        document.getElementById('csv-mapping-input').value = '';
        document.getElementById('csv-mapping-tbody').innerHTML = '';
    }

    function downloadCsvMappingExample() {
        const headers = ["file", "MagicNumber"];
        const rows = [
            ["general_report.html", "12345"],
            ["backtest_EURUSD.html", "67890"],
            ["strategy_xp.html", "11111"],
        ];
        const escape = v => `"${String(v).replace(/"/g, '""')}"`;
        const csv = [headers.map(escape).join(","), ...rows.map(r => r.map(escape).join(","))].join("\n");
        const blob = new Blob([csv], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "example_mapping.csv";
        a.click();
        URL.revokeObjectURL(url);
    }

    // ── Backtest Upload ──────────────────────────────────────────────────────

    let _btFiles = [];

    function btDragOver(e) {
        e.preventDefault();
        const z = document.getElementById('bt-drop-zone');
        z.style.borderColor = 'var(--accent)';
        z.style.background = 'rgba(59,130,246,0.05)';
    }
    function btDragLeave(e) {
        const z = document.getElementById('bt-drop-zone');
        z.style.borderColor = 'var(--border)';
        z.style.background = '';
    }
    function btDrop(e) {
        e.preventDefault();
        btDragLeave(e);
        btFilesSelected(e.dataTransfer.files);
    }
    function btFilesSelected(fileList) {
        const existing = new Set(_btFiles.map(f => f.name));
        for (const f of fileList) {
            if (!existing.has(f.name)) _btFiles.push(f);
        }
        btRenderFileList();
    }
    function btRemoveFile(name) {
        _btFiles = _btFiles.filter(f => f.name !== name);
        btRenderFileList();
    }
    function btRenderFileList() {
        const el = document.getElementById('bt-file-list');
        const btn = document.getElementById('bt-upload-btn');
        if (!_btFiles.length) { el.innerHTML = ''; btn.disabled = true; return; }
        el.innerHTML = `<div style="display:flex; flex-direction:column; gap:0.3rem;">` +
            _btFiles.map(f =>
                `<div style="display:flex; align-items:center; gap:0.5rem; font-size:0.85rem; color:var(--text-muted);">
                    <span style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${f.name}</span>
                    <span style="font-size:0.75rem;">(${(f.size/1024).toFixed(0)} KB)</span>
                    <button onclick="btRemoveFile('${f.name}')" style="background:none; border:none; color:var(--red); cursor:pointer; font-size:0.9rem; padding:0 0.25rem;">✕</button>
                </div>`
            ).join('') + '</div>';
        btn.disabled = false;
    }

    const STATUS_COLORS = { ok: 'var(--green)', skipped: 'var(--text-muted)', error: 'var(--red)' };
    const STATUS_LABELS = { ok: 'Imported', skipped: 'Skipped/Duplicate', error: 'Error' };

    function btSetProgress(current, total, filename) {
        const pct = total ? Math.round((current / total) * 100) : 0;
        document.getElementById('bt-progress-bar').style.width = pct + '%';
        document.getElementById('bt-progress-pct').textContent = pct + '%';
        document.getElementById('bt-progress-label').textContent =
            filename ? `File ${current} of ${total}: ${filename}` : `Completed — ${total} file(s)`;
    }

    function btAppendResult(r) {
        const tbody = document.getElementById('bt-results-body');
        const row = document.createElement('tr');
        row.innerHTML = `
            <td style="max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${r.filename}">${r.filename}</td>
            <td><span style="color:${STATUS_COLORS[r.status] || 'var(--text)'}; font-weight:600;">${STATUS_LABELS[r.status] || r.status}</span></td>
            <td>${r.backtest_id != null ? `<a href="/strategy/${r.backtest_id}" style="color:var(--accent);">#${r.backtest_id}</a>` : '—'}</td>
            <td>${r.deals_imported || '—'}</td>
            <td style="color:var(--text-muted); font-size:0.82rem;">${r.error || ''}</td>`;
        tbody.appendChild(row);
        document.getElementById('bt-results').style.display = 'block';
    }

    async function btUpload() {
        if (!_btFiles.length) return;
        const btn = document.getElementById('bt-upload-btn');
        const status = document.getElementById('bt-upload-status');
        const progressWrap = document.getElementById('bt-progress-wrap');
        const total = _btFiles.length;

        btn.disabled = true;
        status.textContent = '';
        document.getElementById('bt-results').style.display = 'none';
        document.getElementById('bt-results-body').innerHTML = '';
        progressWrap.style.display = 'block';
        btSetProgress(0, total, _btFiles[0]?.name);

        let okCount = 0, errCount = 0;

        for (let i = 0; i < _btFiles.length; i++) {
            const file = _btFiles[i];
            btSetProgress(i + 1, total, file.name);

            const form = new FormData();
            form.append('files', file);
            const lookupName = file.name.toLowerCase().endsWith('.html') ? file.name : file.name + '.html';
            const override = _magicMapping[lookupName];
            if (override) form.append('magic_number_override', override);

            let results;
            try {
                const res = await fetch('/api/backtests/upload-html', {
                    method: 'POST',
                    headers: { 'X-API-Key': API_KEY },
                    body: form,
                });
                results = await res.json();
            } catch (e) {
                results = [{ filename: file.name, status: 'error', backtest_id: null, deals_imported: 0, error: e.message }];
            }

            for (const r of results) {
                btAppendResult(r);
                if (r.status === 'ok') okCount++;
                else if (r.status === 'error') errCount++;
            }
        }

        btSetProgress(total, total, null);
        status.textContent = `${okCount} imported, ${errCount} error(s).`;
        btn.disabled = false;

        _btFiles = [];
        btRenderFileList();
        document.getElementById('bt-file-input').value = '';
    }

    async function loadDeadLetters() {
        const list = document.getElementById("dl-list");
        try {
            const res = await fetch("/api/ingestion-errors?limit=50", { headers: { "X-API-Key": API_KEY } });
            const data = await res.json();
            document.getElementById("dl-count").textContent = `${data.length} errors`;
            if (!data.length) {
                list.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem">No errors recorded.</p>';
                return;
            }
            list.innerHTML = data.map(e => `
                <div style="background:var(--surface-2);border:1px solid var(--border);border-radius:0.4rem;padding:0.6rem 0.75rem;font-size:0.8rem">
                    <div style="display:flex;gap:0.75rem;margin-bottom:0.25rem">
                        <span class="badge badge-neutral">${e.topic || "—"}</span>
                        <span style="color:var(--text-muted)">${formatDateTime(e.timestamp)}</span>
                    </div>
                    <div style="color:#f97316;margin-bottom:0.2rem">${e.error_message || ""}</div>
                    <details><summary style="color:var(--text-muted);cursor:pointer">Raw message</summary>
                        <pre style="margin-top:0.3rem;overflow:auto;font-size:0.75rem;color:var(--text-muted);white-space:pre-wrap">${(e.raw_message || "").slice(0, 500)}</pre>
                    </details>
                </div>`).join("");
        } catch(e) {
            list.innerHTML = '<p style="color:#ef4444">Error loading.</p>';
        }
    }

    async function clearDeadLetters() {
        const confirmed = await showConfirmModal(
            "Clear Ingestion Errors",
            "This will permanently remove all recorded ingestion errors. Are you sure?",
            { confirmLabel: "Clear All", confirmClass: "btn-danger" }
        );
        if (!confirmed) return;
        await fetch("/api/ingestion-errors", { method: "DELETE", headers: { "X-API-Key": API_KEY } });
        loadDeadLetters();
    }

    document.addEventListener("DOMContentLoaded", loadDeadLetters);
