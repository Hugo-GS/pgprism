// Global state
let envInfo = {
    project_root: "/path/to/mcp-postgresql",
    python_executable: "python3",
    cli_command: "mcp-postgresql",
    server_module: "src.server",
    active_profile: null,
    active_database: null,
};

let currentCategory = 'all';

function showAlert(msg, isError = false) {
    const el = document.getElementById('alertBox');
    el.className = isError ? 'error' : 'ok';
    el.textContent = (isError ? '[ERROR] ' : '[OK] ') + msg;
    el.style.display = 'block';
    setTimeout(() => {
        el.className = '';
        el.style.display = 'none';
    }, 4000);
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
        if (data.length === 0) {
            container.innerHTML = query.trim()
                ? `<div class="empty-state">No profiles matching "${query.trim()}".</div>`
                : '<div class="empty-state">No profiles configured. Add one on the left.</div>';
            if (!query.trim()) updateActiveProfileHeader(null);
            return;
        }

        const activeProfile = data.find(p => p.is_active);
        if (activeProfile || !query.trim()) {
            updateActiveProfileHeader(activeProfile);
        }

        container.innerHTML = data.map(p => `
            <div class="profile-card ${p.is_active ? 'active-profile' : ''}">
                <div>
                    <div class="profile-name">
                        <span class="profile-indicator ${p.is_active ? '' : 'idle'}">${p.is_active ? '▶' : '·'}</span>
                        <span>${p.name}</span>
                    </div>
                    <div class="profile-uri">${p.username}@${p.host}:${p.port}/${p.database} &middot; ssl=${p.sslmode} &middot; timeout=${p.statement_timeout_ms || 30000}ms</div>
                </div>
                <div class="actions">
                    ${p.is_active ? '<span class="status-current">current</span>' : `<button onclick="activateProfile(${p.id})" class="btn-action">Select</button>`}
                    <button onclick="deleteProfile(${p.id})" class="btn-action btn-delete">Delete</button>
                </div>
            </div>
        `).join('');
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

// Navigation Tabs
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
                btn.classList.add('active');
                panel.style.display = 'block';
            } else {
                btn.classList.remove('active');
                panel.style.display = 'none';
            }
        }
    });
    window.location.hash = targetTab;
}

// Client Config switching inside Connection Guide
function switchClientConfig(clientKey) {
    const clients = ['claude', 'cursor', 'antigravity', 'vscode', 'cli'];
    const tabs = document.querySelectorAll('.client-tab');
    tabs.forEach(tab => tab.classList.remove('active'));

    clients.forEach(c => {
        const pane = document.getElementById(`config-${c}`);
        if (pane) {
            pane.style.display = (c === clientKey) ? 'block' : 'none';
        }
    });

    if (window.event && window.event.currentTarget) {
        window.event.currentTarget.classList.add('active');
    }
}

function updateActiveProfileHeader(profile) {
    const contextEl = document.getElementById('headerContextVal');
    const bannerTextEl = document.getElementById('activeProfileText');

    if (profile) {
        if (contextEl) contextEl.textContent = `${profile.name} / ${profile.database}`;
        if (bannerTextEl) {
            bannerTextEl.innerHTML = `${profile.name} &middot; <code>${profile.database}</code> @ <code>${profile.host}:${profile.port}</code>`;
        }
    } else {
        if (contextEl) contextEl.textContent = 'none';
        if (bannerTextEl) {
            bannerTextEl.innerHTML = `none &mdash; configure and select in <a href="#profiles" onclick="switchTab('profiles')">Profiles</a>`;
        }
    }
}

// Load dynamic server & environment metadata
async function loadEnvInfo() {
    try {
        const res = await fetch('/api/info');
        if (res.ok) {
            envInfo = await res.json();
            renderConfigSnippets();
            if (envInfo.active_profile) {
                updateActiveProfileHeader({
                    name: envInfo.active_profile,
                    database: envInfo.active_database || 'postgres',
                    host: 'localhost',
                    port: 5432
                });
            }
        }
    } catch (err) {
        console.error("Error loading server info:", err);
        renderConfigSnippets();
    }
}

function renderConfigSnippets() {
    const py = envInfo.python_executable;
    const cwd = envInfo.project_root;

    // Claude Desktop
    const claudeJson = {
        mcpServers: {
            postgresql: {
                command: py,
                args: ["-m", "src.server"],
                cwd: cwd
            }
        }
    };
    const elClaude = document.getElementById('snippet-claude');
    if (elClaude) elClaude.textContent = JSON.stringify(claudeJson, null, 2);

    // Cursor
    const cursorJson = {
        mcpServers: {
            postgresql: {
                command: py,
                args: ["-m", "src.server"],
                cwd: cwd
            }
        }
    };
    const elCursor = document.getElementById('snippet-cursor');
    if (elCursor) elCursor.textContent = JSON.stringify(cursorJson, null, 2);

    // Antigravity
    const antigravityJson = {
        mcpServers: {
            postgresql: {
                command: py,
                args: ["-m", "src.server"],
                cwd: cwd
            }
        }
    };
    const elAntigravity = document.getElementById('snippet-antigravity');
    if (elAntigravity) elAntigravity.textContent = JSON.stringify(antigravityJson, null, 2);

    // VS Code / Cline
    const vscodeJson = {
        mcpServers: {
            postgresql: {
                command: py,
                args: ["-m", "src.server"],
                cwd: cwd
            }
        }
    };
    const elVscode = document.getElementById('snippet-vscode');
    if (elVscode) elVscode.textContent = JSON.stringify(vscodeJson, null, 2);

    // Direct CLI
    const elCli = document.getElementById('snippet-cli');
    if (elCli) {
        elCli.textContent = `# 1. Enter project workspace:\ncd ${cwd}\n\n# 2. Launch stdio MCP server:\n${py} -m src.server\n\n# Or using installed binary entrypoint:\n${envInfo.cli_command}`;
    }
}

// Copy snippet to clipboard
async function copySnippet(elementId) {
    const codeEl = document.getElementById(elementId);
    if (!codeEl) return;
    const text = codeEl.textContent;
    try {
        await navigator.clipboard.writeText(text);
        const btn = window.event ? window.event.currentTarget : null;
        if (btn) {
            const originalHTML = btn.innerHTML;
            btn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg> Copied!`;
            btn.classList.add('copied');
            setTimeout(() => {
                btn.innerHTML = originalHTML;
                btn.classList.remove('copied');
            }, 2000);
        }
    } catch (err) {
        console.error("Clipboard copy failed:", err);
        showAlert("Failed to copy to clipboard", true);
    }
}

// Category filter
function setCategoryFilter(category) {
    currentCategory = category;
    const pills = document.querySelectorAll('.cat-pill');
    pills.forEach(p => {
        if (p.textContent.toLowerCase().includes(category)) {
            p.classList.add('active');
        } else {
            p.classList.remove('active');
        }
    });
    filterTools();
}

// Documentation search/filter
function filterTools() {
    const query = (document.getElementById('toolFilter').value || '').toLowerCase().trim();
    const cards = document.querySelectorAll('.tool-card');
    cards.forEach(card => {
        const text = card.textContent.toLowerCase();
        const cardCat = card.getAttribute('data-category');
        const matchesCategory = (currentCategory === 'all' || cardCat === currentCategory);
        const matchesText = text.includes(query);
        card.style.display = (matchesCategory && matchesText) ? 'flex' : 'none';
    });
}

// Profile Form submit
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

// Initialization
initTabs();
loadProfiles();
loadEnvInfo();
