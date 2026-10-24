let envInfo = {
    project_root: "/path/to/pgprism",
    python_executable: "python3",
    cli_command: "pgprism",
    server_module: "src.server",
    active_profile: null,
    active_database: null,
};

let currentCategory = 'all';
let alertTimeout = null;

function showAlert(msg, isError = false) {
    const el = document.getElementById('alertBox');
    const msgEl = document.getElementById('alertMsg');
    const timerEl = document.getElementById('alertTimer');
    const copyBtn = document.getElementById('alertCopy');
    const closeBtn = document.getElementById('alertClose');

    el.dataset.variant = isError ? 'danger' : 'success';
    msgEl.textContent = (isError ? 'Error: ' : '') + msg;
    el.hidden = false;

    const duration = isError ? 15000 : 4000;
    el.style.setProperty('--toast-duration', duration + 'ms');

    // Restart the timer animation
    timerEl.style.animation = 'none';
    timerEl.offsetHeight; // force reflow
    timerEl.style.animation = '';

    clearTimeout(alertTimeout);
    alertTimeout = setTimeout(() => {
        el.hidden = true;
    }, duration);

    // Copy button
    copyBtn.onclick = () => {
        navigator.clipboard.writeText(msg).then(() => {
            copyBtn.style.opacity = '1';
            setTimeout(() => copyBtn.style.opacity = '', 400);
        });
    };

    // Close button — dismiss immediately
    closeBtn.onclick = () => {
        clearTimeout(alertTimeout);
        el.hidden = true;
    };
}

function initTheme() {
    const root = document.documentElement;
    const btn = document.getElementById('themeToggle');
    const label = document.getElementById('themeLabel');
    const render = () => {
        label.textContent = root.dataset.theme === 'light' ? 'Dark mode' : 'Light mode';
    };
    btn.addEventListener('click', () => {
        root.dataset.theme = root.dataset.theme === 'light' ? 'dark' : 'light';
        try {
            localStorage.setItem('pgprism-theme', root.dataset.theme);
        } catch (e) {}
        render();
    });
    render();
}

function getFormData() {
    return {
        name: document.getElementById('name').value.trim(),
        host: document.getElementById('host').value.trim(),
        port: parseInt(document.getElementById('port').value, 10),
        database: document.getElementById('database').value.trim() || 'postgres',
        username: document.getElementById('username').value.trim(),
        password: document.getElementById('password').value,
        sslmode: document.getElementById('sslmode').value,
        statement_timeout_ms: parseInt(document.getElementById('statement-timeout').value, 10) || 30000,
    };
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function truncate(str, max = 40) {
    if (!str || str.length <= max) return str || '';
    return str.slice(0, max - 3) + '...';
}

let profileSearchTimeout = null;

function handleProfileSearch(query) {
    clearTimeout(profileSearchTimeout);
    profileSearchTimeout = setTimeout(() => {
        loadProfiles(query);
    }, 200);
}

async function loadProfiles(query = '') {
    try {
        const url = query && query.trim() ? `/api/profiles?q=${encodeURIComponent(query.trim())}` : '/api/profiles';
        const res = await fetch(url);
        const data = await res.json();
        const container = document.getElementById('profilesList');
        const countEl = document.getElementById('profilesCount');
        countEl.textContent = `${data.length} ${data.length === 1 ? 'profile' : 'profiles'}`;
        if (data.length === 0) {
            container.innerHTML = query.trim()
                ? `<tr><td colspan="6" class="fc-empty"><strong>No matching profiles</strong>No profiles matching "${query.trim()}".</td></tr>`
                : '<tr><td colspan="6" class="fc-empty"><strong>No profiles configured</strong>Add one with the form below.</td></tr>';
            if (!query.trim()) updateActiveProfileHeader(null);
            return;
        }

        const activeProfile = data.find(p => p.is_active);
        if (activeProfile || !query.trim()) {
            updateActiveProfileHeader(activeProfile);
        }

        container.innerHTML = data.map(p => {
            const uri = `${p.username}@${p.host}:${p.port}/${p.database}`;
            const displayUri = truncate(uri, 40);
            const displayName = truncate(p.name, 40);
            return `
            <tr data-active="${p.is_active ? 'true' : 'false'}">
                <td><span class="profile-name" title="${escapeHtml(p.name)}">${escapeHtml(displayName)}</span></td>
                <td><span class="profile-uri" title="${escapeHtml(uri)}">${escapeHtml(displayUri)}</span></td>
                <td class="fc-mono">${escapeHtml(p.sslmode)}</td>
                <td class="num fc-mono">${p.statement_timeout_ms || 30000} ms</td>
                <td>${p.is_active ? '<span class="fc-badge fc-badge-success">Active</span>' : '<span class="fc-badge fc-badge-idle">Idle</span>'}</td>
                <td>
                    <div class="row-actions">
                        ${p.is_active ? '' : `<button type="button" onclick="activateProfile(${p.id})" class="fc-btn">Select</button>`}
                        <button type="button" onclick="deleteProfile(${p.id})" class="fc-btn fc-btn-ghost fc-btn-danger">Delete</button>
                    </div>
                </td>
            </tr>
        `;}).join('');
    } catch (err) {
        console.error("Error loading profiles:", err);
    }
}

async function activateProfile(id) {
    const res = await fetch(`/api/profiles/${id}/activate`, { method: 'POST' });
    if (res.ok) {
        showAlert('Active profile switched.');
        await loadProfiles();
        await loadEnvInfo();
    } else {
        showAlert('Activation failed.', true);
    }
}

async function deleteProfile(id) {
    if (!confirm('Delete profile?')) return;
    const res = await fetch(`/api/profiles/${id}`, { method: 'DELETE' });
    if (res.ok) {
        showAlert('Profile deleted.');
        await loadProfiles();
        await loadEnvInfo();
    } else {
        showAlert('Deletion failed.', true);
    }
}

async function testConnection() {
    const data = getFormData();
    showAlert('Connecting...', false);
    try {
        const res = await fetch('/api/profiles/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        const result = await res.json();
        if (result.success) {
            showAlert('Connected: ' + result.message);
        } else {
            showAlert(result.message, true);
        }
    } catch (err) {
        showAlert('Connection error: ' + err.message, true);
    }
}

function initTabs() {
    const tabs = ['profiles', 'connection', 'docs'];
    tabs.forEach(tab => {
        const btn = document.getElementById(`tabBtn-${tab}`);
        if (!btn) return;
        btn.addEventListener('click', () => switchTab(tab));
    });

    const hash = window.location.hash.replace('#', '');
    if (tabs.includes(hash)) {
        switchTab(hash);
    }
}

function switchTab(targetTab) {
    const tabs = ['profiles', 'connection', 'docs'];
    tabs.forEach(t => {
        const btn = document.getElementById(`tabBtn-${t}`);
        const panel = document.getElementById(`tab-${t}`);
        if (btn && panel) {
            if (t === targetTab) {
                btn.setAttribute('aria-current', 'page');
                panel.hidden = false;
            } else {
                btn.removeAttribute('aria-current');
                panel.hidden = true;
            }
        }
    });
    window.location.hash = targetTab;
}

function switchClientConfig(clientKey, tabBtn) {
    const clients = ['claude', 'cursor', 'antigravity', 'vscode', 'cli'];
    document.querySelectorAll('.client-tabs .fc-tab').forEach(tab => {
        tab.setAttribute('aria-selected', tab === tabBtn ? 'true' : 'false');
    });

    clients.forEach(c => {
        const pane = document.getElementById(`config-${c}`);
        if (pane) {
            pane.hidden = c !== clientKey;
        }
    });
}

function updateActiveProfileHeader(profile) {
    const contextEl = document.getElementById('headerContextVal');
    const bannerTextEl = document.getElementById('activeProfileText');
    const statusEl = document.getElementById('activeProfileStatus');

    if (profile) {
        if (contextEl) contextEl.textContent = `${profile.name} / ${profile.database}`;
        if (bannerTextEl) {
            bannerTextEl.textContent = `${profile.name} / ${profile.database} @ ${profile.host}:${profile.port}`;
        }
        if (statusEl) {
            statusEl.className = 'fc-badge fc-badge-success';
            statusEl.textContent = 'Active';
        }
    } else {
        if (contextEl) contextEl.textContent = 'none';
        if (bannerTextEl) {
            bannerTextEl.innerHTML = `None selected. Pick one in <a href="#profiles" onclick="switchTab('profiles')">Profiles</a>.`;
        }
        if (statusEl) {
            statusEl.className = 'fc-badge fc-badge-warning';
            statusEl.textContent = 'Not set';
        }
    }
}

async function loadEnvInfo() {
    try {
        const res = await fetch('/api/info');
        if (res.ok) {
            envInfo = await res.json();
            renderConfigSnippets();
        }
    } catch (err) {
        console.error("Error loading server info:", err);
        renderConfigSnippets();
    }
}

function renderConfigSnippets() {
    const py = envInfo.python_executable;
    const cwd = envInfo.project_root;

    const claudeJson = {
        mcpServers: {
            pgprism: {
                command: py,
                args: ["-m", "src.server"],
                cwd: cwd
            }
        }
    };
    const elClaude = document.getElementById('snippet-claude');
    if (elClaude) elClaude.textContent = JSON.stringify(claudeJson, null, 2);

    const cursorJson = {
        mcpServers: {
            pgprism: {
                command: py,
                args: ["-m", "src.server"],
                cwd: cwd
            }
        }
    };
    const elCursor = document.getElementById('snippet-cursor');
    if (elCursor) elCursor.textContent = JSON.stringify(cursorJson, null, 2);

    const antigravityJson = {
        mcpServers: {
            pgprism: {
                command: py,
                args: ["-m", "src.server"],
                cwd: cwd
            }
        }
    };
    const elAntigravity = document.getElementById('snippet-antigravity');
    if (elAntigravity) elAntigravity.textContent = JSON.stringify(antigravityJson, null, 2);

    const vscodeJson = {
        mcpServers: {
            pgprism: {
                command: py,
                args: ["-m", "src.server"],
                cwd: cwd
            }
        }
    };
    const elVscode = document.getElementById('snippet-vscode');
    if (elVscode) elVscode.textContent = JSON.stringify(vscodeJson, null, 2);

    const elCli = document.getElementById('snippet-cli');
    if (elCli) {
        elCli.textContent = `# 1. Enter project workspace:\ncd ${cwd}\n\n# 2. Launch stdio MCP server:\n${py} -m src.server\n\n# Or using installed binary entrypoint:\n${envInfo.cli_command}`;
    }
}

async function copySnippet(elementId, btn) {
    const codeEl = document.getElementById(elementId);
    if (!codeEl) return;
    const text = codeEl.textContent;
    try {
        await navigator.clipboard.writeText(text);
        if (btn) {
            const originalHTML = btn.innerHTML;
            btn.innerHTML = `<svg class="fc-icon" viewBox="0 0 24 24" aria-hidden="true"><polyline points="20 6 9 17 4 12"></polyline></svg> Copied!`;
            btn.dataset.copied = 'true';
            setTimeout(() => {
                btn.innerHTML = originalHTML;
                delete btn.dataset.copied;
            }, 2000);
        }
    } catch (err) {
        console.error("Clipboard copy failed:", err);
        showAlert("Failed to copy to clipboard", true);
    }
}

function setCategoryFilter(category) {
    currentCategory = category;
    document.querySelectorAll('.category-pills .fc-btn').forEach(p => {
        p.setAttribute('aria-pressed', p.dataset.category === category ? 'true' : 'false');
    });
    filterTools();
}

function filterTools() {
    const query = (document.getElementById('toolFilter').value || '').toLowerCase().trim();
    const rows = document.querySelectorAll('#toolsList tr[data-category]');
    let visible = 0;
    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        const rowCat = row.getAttribute('data-category');
        const matchesCategory = (currentCategory === 'all' || rowCat === currentCategory);
        const matchesText = text.includes(query);
        row.hidden = !(matchesCategory && matchesText);
        if (!row.hidden) visible++;
    });
    document.getElementById('toolsEmpty').hidden = visible > 0;
}

document.getElementById('profileForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = getFormData();
    try {
        const res = await fetch('/api/profiles', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (res.ok) {
            showAlert('Profile saved.');
            document.getElementById('profileForm').reset();
            document.getElementById('host').value = 'localhost';
            document.getElementById('port').value = 5432;
            document.getElementById('statement-timeout').value = 30000;
            await loadProfiles();
            await loadEnvInfo();
        } else {
            const err = await res.json();
            showAlert(err.detail || 'Save failed', true);
        }
    } catch (err) {
        showAlert('Connection error: ' + err.message, true);
    }
});

initTheme();
initTabs();
loadProfiles();
loadEnvInfo();
