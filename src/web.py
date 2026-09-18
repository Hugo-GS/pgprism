"""Local Web Configuration UI for PostgreSQL MCP Server."""

from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
import uvicorn
from src.database import DatabaseManager
from src.storage import Profile, ProfileCreate, ProfileStorage


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MCP PostgreSQL - Configuration</title>
    <style>
        :root {
            --bg: #0a0a0a;
            --surface: #121212;
            --surface-hover: #181818;
            --border: #262626;
            --border-focus: #525252;
            --text: #ededed;
            --text-muted: #888888;
            --text-dim: #555555;
            --font-mono: ui-monospace, "SF Mono", Menlo, Monaco, Consolas, "Liberation Mono", monospace;
            --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background-color: var(--bg);
            color: var(--text);
            font-family: var(--font-sans);
            font-size: 13px;
            line-height: 1.5;
            padding: 32px 20px;
        }

        .container {
            max-width: 900px;
            margin: 0 auto;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            border-bottom: 1px solid var(--border);
            padding-bottom: 16px;
            margin-bottom: 24px;
        }

        h1 {
            font-size: 16px;
            font-weight: 600;
            letter-spacing: -0.01em;
        }

        .tag {
            font-family: var(--font-mono);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            border: 1px solid var(--border);
            padding: 2px 6px;
            border-radius: 2px;
        }

        .tag.active {
            color: #4ade80;
            border-color: #166534;
            background: rgba(22, 101, 52, 0.15);
        }

        .grid {
            display: grid;
            grid-template-columns: 340px 1fr;
            gap: 32px;
        }

        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
        }

        h2 {
            font-size: 13px;
            font-weight: 600;
            color: var(--text);
            margin-bottom: 16px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .field {
            margin-bottom: 12px;
        }

        .field-row {
            display: grid;
            grid-template-columns: 1fr 100px;
            gap: 8px;
        }

        label {
            display: block;
            font-size: 11px;
            font-family: var(--font-mono);
            color: var(--text-muted);
            margin-bottom: 4px;
            text-transform: uppercase;
        }

        input, select {
            width: 100%;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 3px;
            padding: 7px 9px;
            color: var(--text);
            font-family: var(--font-mono);
            font-size: 12px;
            outline: none;
            transition: border-color 0.1s ease;
        }

        input:focus, select:focus {
            border-color: var(--border-focus);
        }

        .btn-group {
            display: flex;
            gap: 8px;
            margin-top: 18px;
        }

        button {
            font-family: var(--font-mono);
            font-size: 12px;
            padding: 8px 12px;
            border-radius: 3px;
            cursor: pointer;
            transition: all 0.1s ease;
            border: 1px solid transparent;
        }

        .btn-primary {
            background: #ededed;
            color: #0a0a0a;
            font-weight: 500;
            flex: 1;
        }

        .btn-primary:hover {
            background: #ffffff;
        }

        .btn-secondary {
            background: transparent;
            border-color: var(--border);
            color: var(--text);
        }

        .btn-secondary:hover {
            background: var(--surface-hover);
            border-color: var(--border-focus);
        }

        .btn-action {
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text-muted);
            padding: 3px 8px;
            font-size: 11px;
        }

        .btn-action:hover {
            color: var(--text);
            border-color: var(--border-focus);
            background: var(--surface-hover);
        }

        .btn-delete:hover {
            color: #f87171;
            border-color: #7f1d1d;
            background: rgba(127, 29, 29, 0.1);
        }

        .profile-card {
            border: 1px solid var(--border);
            border-radius: 3px;
            padding: 12px;
            margin-bottom: 8px;
            background: var(--surface);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .profile-card.active-profile {
            border-color: #404040;
            background: #141414;
        }

        .profile-name {
            font-weight: 600;
            font-size: 13px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .profile-uri {
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--text-muted);
            margin-top: 4px;
        }

        .actions {
            display: flex;
            gap: 6px;
        }

        #alertBox {
            display: none;
            padding: 8px 12px;
            font-family: var(--font-mono);
            font-size: 11px;
            border-radius: 3px;
            margin-bottom: 16px;
            border: 1px solid var(--border);
        }

        #alertBox.ok {
            display: block;
            background: #0f1c13;
            border-color: #1e3a24;
            color: #86efac;
        }

        #alertBox.error {
            display: block;
            background: #201111;
            border-color: #451a1a;
            color: #fca5a5;
        }

        .empty-state {
            color: var(--text-dim);
            font-family: var(--font-mono);
            font-size: 12px;
            padding: 24px;
            text-align: center;
            border: 1px dashed var(--border);
            border-radius: 3px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1>MCP PostgreSQL</h1>
            </div>
            <span class="tag">Read-Only Engine</span>
        </header>

        <div id="alertBox"></div>

        <div class="grid">
            <!-- Left Form -->
            <section>
                <h2>New Profile</h2>
                <form id="profileForm">
                    <div class="field">
                        <label>Profile Name</label>
                        <input id="name" required placeholder="local-dev" autocomplete="off">
                    </div>

                    <div class="field field-row">
                        <div>
                            <label>Host</label>
                            <input id="host" value="localhost" autocomplete="off">
                        </div>
                        <div>
                            <label>Port</label>
                            <input id="port" type="number" value="5432">
                        </div>
                    </div>

                    <div class="field">
                        <label>Database (Optional)</label>
                        <input id="database" placeholder="postgres (default)" autocomplete="off">
                    </div>

                    <div class="field">
                        <label>Username</label>
                        <input id="username" required placeholder="postgres" autocomplete="off">
                    </div>

                    <div class="field">
                        <label>Password</label>
                        <input id="password" type="password" placeholder="••••••••">
                    </div>

                    <div class="field">
                        <label>SSL Mode</label>
                        <select id="sslmode">
                            <option value="prefer">prefer</option>
                            <option value="require">require</option>
                            <option value="disable">disable</option>
                            <option value="allow">allow</option>
                        </select>
                    </div>

                    <div class="btn-group">
                        <button type="button" onclick="testConnection()" class="btn-secondary">Test</button>
                        <button type="submit" class="btn-primary">Save Profile</button>
                    </div>
                </form>
            </section>

            <!-- Right Profile List -->
            <section>
                <h2>Configured Profiles (SQLite)</h2>
                <div id="profilesList">
                    <div class="empty-state">Loading profiles...</div>
                </div>
            </section>
        </div>
    </div>

    <script>
        function showAlert(msg, isError = false) {
            const el = document.getElementById('alertBox');
            el.className = isError ? 'error' : 'ok';
            el.textContent = (isError ? '[ERROR] ' : '[OK] ') + msg;
            setTimeout(() => { el.className = ''; el.style.display = 'none'; }, 4000);
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
            };
        }

        async function loadProfiles() {
            const res = await fetch('/api/profiles');
            const data = await res.json();
            const container = document.getElementById('profilesList');
            if (data.length === 0) {
                container.innerHTML = '<div class="empty-state">No profiles configured. Add one on the left.</div>';
                return;
            }
            container.innerHTML = data.map(p => `
                <div class="profile-card ${p.is_active ? 'active-profile' : ''}">
                    <div>
                        <div class="profile-name">
                            <span>${p.name}</span>
                            ${p.is_active ? '<span class="tag active">ACTIVE</span>' : ''}
                        </div>
                        <div class="profile-uri">${p.username}@${p.host}:${p.port}/${p.database} &middot; ssl=${p.sslmode}</div>
                    </div>
                    <div class="actions">
                        ${!p.is_active ? `<button onclick="activateProfile(${p.id})" class="btn-action">Activate</button>` : ''}
                        <button onclick="deleteProfile(${p.id})" class="btn-action btn-delete">Delete</button>
                    </div>
                </div>
            `).join('');
        }

        async function activateProfile(id) {
            const res = await fetch(`/api/profiles/${id}/activate`, { method: 'POST' });
            if (res.ok) {
                showAlert('Active profile switched.');
                loadProfiles();
            } else {
                showAlert('Failed to activate profile.', true);
            }
        }

        async function deleteProfile(id) {
            if (!confirm('Delete this connection profile?')) return;
            const res = await fetch(`/api/profiles/${id}`, { method: 'DELETE' });
            if (res.ok) {
                showAlert('Profile removed.');
                loadProfiles();
            } else {
                showAlert('Failed to delete profile.', true);
            }
        }

        async function testConnection() {
            const data = getFormData();
            showAlert('Testing connection...', false);
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
                showAlert('Network failure: ' + err.message, true);
            }
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
                    showAlert('Profile saved successfully.');
                    document.getElementById('profileForm').reset();
                    document.getElementById('host').value = 'localhost';
                    document.getElementById('port').value = 5432;
                    loadProfiles();
                } else {
                    const err = await res.json();
                    showAlert(err.detail || 'Save failed', true);
                }
            } catch (err) {
                showAlert('Network failure: ' + err.message, true);
            }
        });

        loadProfiles();
    </script>
</body>
</html>
"""


def create_app(storage: Optional[ProfileStorage] = None) -> FastAPI:
    """Creates the FastAPI configuration app."""
    store = storage if storage is not None else ProfileStorage()
    app = FastAPI(title="MCP PostgreSQL Configuration")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTML_TEMPLATE

    @app.get("/api/profiles", response_model=List[Profile])
    def list_profiles():
        return store.list_profiles()

    @app.post("/api/profiles", response_model=Profile, status_code=status.HTTP_201_CREATED)
    def create_profile(payload: ProfileCreate):
        existing = store.get_profile_by_name(payload.name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Profile with name '{payload.name}' already exists.",
            )
        return store.save_profile(payload)

    @app.post("/api/profiles/{profile_id}/activate", response_model=Profile)
    def activate_profile(profile_id: int):
        profile = store.set_active_profile(profile_id)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile with id {profile_id} not found.",
            )
        return profile

    @app.delete("/api/profiles/{profile_id}")
    def delete_profile(profile_id: int):
        success = store.delete_profile(profile_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile with id {profile_id} not found.",
            )
        return {"success": True}

    @app.get("/api/profiles/{profile_id}/databases", response_model=List[str])
    def list_profile_databases(profile_id: int):
        profile = store.get_profile(profile_id)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile with id {profile_id} not found.",
            )
        db = DatabaseManager(profile)
        try:
            return db.list_databases()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to query server databases: {e}",
            )

    @app.post("/api/profiles/test")
    def test_profile_connection(payload: ProfileCreate):
        # Create temporary Profile instance to test
        temp_profile = Profile(
            id=0,
            name=payload.name,
            host=payload.host,
            port=payload.port,
            database=payload.database,
            username=payload.username,
            password=payload.password,
            sslmode=payload.sslmode,
            is_active=False,
            created_at="",
            updated_at="",
        )
        db = DatabaseManager(temp_profile)
        success, msg = db.test_connection()
        return {"success": success, "message": msg}

    return app


app = create_app()


def main():
    """Runs the local web configuration server on localhost:8000."""
    uvicorn.run("src.web:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
