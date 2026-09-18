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
    <title>MCP PostgreSQL - Local Configuration</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background-color: #0f172a; color: #f8fafc; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; }
    </style>
</head>
<body class="p-6 md:p-12">
    <div class="max-w-4xl mx-auto space-y-8">
        <!-- Header -->
        <header class="flex items-center justify-between border-b border-slate-700 pb-4">
            <div>
                <h1 class="text-2xl md:text-3xl font-bold tracking-tight text-white">PostgreSQL MCP Profiles</h1>
                <p class="text-sm text-slate-400 mt-1">Local credential and connection management (SQLite)</p>
            </div>
            <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                Strict Read-Only Mode
            </span>
        </header>

        <!-- Message Box -->
        <div id="alertBox" class="hidden p-4 rounded-lg text-sm transition-all duration-200"></div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-8">
            <!-- Form Section -->
            <section class="md:col-span-1 bg-slate-800/60 border border-slate-700 rounded-xl p-6 shadow-sm">
                <h2 class="text-lg font-semibold text-white mb-4">Add Connection Profile</h2>
                <form id="profileForm" class="space-y-4">
                    <div>
                        <label class="block text-xs font-medium text-slate-300 mb-1">Profile Name</label>
                        <input id="name" required placeholder="e.g. local-dev" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-sm text-white focus:outline-none focus:border-indigo-500">
                    </div>
                    <div class="grid grid-cols-2 gap-2">
                        <div>
                            <label class="block text-xs font-medium text-slate-300 mb-1">Host</label>
                            <input id="host" value="localhost" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-sm text-white focus:outline-none focus:border-indigo-500">
                        </div>
                        <div>
                            <label class="block text-xs font-medium text-slate-300 mb-1">Port</label>
                            <input id="port" type="number" value="5432" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-sm text-white focus:outline-none focus:border-indigo-500">
                        </div>
                    </div>
                    <div>
                        <label class="block text-xs font-medium text-slate-300 mb-1">Database</label>
                        <input id="database" required placeholder="e.g. postgres" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-sm text-white focus:outline-none focus:border-indigo-500">
                    </div>
                    <div>
                        <label class="block text-xs font-medium text-slate-300 mb-1">Username</label>
                        <input id="username" required placeholder="e.g. postgres" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-sm text-white focus:outline-none focus:border-indigo-500">
                    </div>
                    <div>
                        <label class="block text-xs font-medium text-slate-300 mb-1">Password</label>
                        <input id="password" type="password" placeholder="••••••••" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-sm text-white focus:outline-none focus:border-indigo-500">
                    </div>
                    <div>
                        <label class="block text-xs font-medium text-slate-300 mb-1">SSL Mode</label>
                        <select id="sslmode" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-sm text-white focus:outline-none focus:border-indigo-500">
                            <option value="prefer">prefer</option>
                            <option value="require">require</option>
                            <option value="disable">disable</option>
                            <option value="allow">allow</option>
                        </select>
                    </div>
                    <div class="pt-2 flex flex-col gap-2">
                        <button type="button" onclick="testConnection()" class="w-full py-2 px-4 bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm font-medium rounded-md transition-colors">
                            Test Connection
                        </button>
                        <button type="submit" class="w-full py-2 px-4 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-md shadow transition-colors">
                            Save Profile
                        </button>
                    </div>
                </form>
            </section>

            <!-- Profiles List Section -->
            <section class="md:col-span-2 bg-slate-800/60 border border-slate-700 rounded-xl p-6 shadow-sm">
                <h2 class="text-lg font-semibold text-white mb-4">Saved Profiles</h2>
                <div id="profilesList" class="space-y-3">
                    <p class="text-sm text-slate-400">Loading profiles...</p>
                </div>
            </section>
        </div>
    </div>

    <script>
        function showAlert(msg, isError = false) {
            const el = document.getElementById('alertBox');
            el.className = isError 
                ? 'p-4 rounded-lg text-sm bg-rose-500/10 text-rose-300 border border-rose-500/20' 
                : 'p-4 rounded-lg text-sm bg-emerald-500/10 text-emerald-300 border border-emerald-500/20';
            el.textContent = msg;
            el.classList.remove('hidden');
            setTimeout(() => el.classList.add('hidden'), 5000);
        }

        function getFormData() {
            return {
                name: document.getElementById('name').value.trim(),
                host: document.getElementById('host').value.trim(),
                port: parseInt(document.getElementById('port').value, 10),
                database: document.getElementById('database').value.trim(),
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
                container.innerHTML = '<p class="text-sm text-slate-400">No profiles configured yet. Create one to get started.</p>';
                return;
            }
            container.innerHTML = data.map(p => `
                <div class="flex items-center justify-between p-4 rounded-lg border ${p.is_active ? 'border-indigo-500 bg-indigo-500/10' : 'border-slate-700 bg-slate-900/50'}">
                    <div class="space-y-1">
                        <div class="flex items-center gap-2">
                            <span class="font-semibold text-sm text-white">${p.name}</span>
                            ${p.is_active ? '<span class="text-xs px-2 py-0.5 rounded bg-indigo-500 text-white font-medium">Active</span>' : ''}
                        </div>
                        <p class="text-xs text-slate-400">${p.username}@${p.host}:${p.port}/${p.database} (${p.sslmode})</p>
                    </div>
                    <div class="flex items-center gap-2">
                        ${!p.is_active ? `<button onclick="activateProfile(${p.id})" class="text-xs px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded text-slate-200">Activate</button>` : ''}
                        <button onclick="deleteProfile(${p.id})" class="text-xs px-3 py-1.5 bg-rose-900/30 hover:bg-rose-900/60 text-rose-300 rounded border border-rose-700/40">Delete</button>
                    </div>
                </div>
            `).join('');
        }

        async function activateProfile(id) {
            const res = await fetch(`/api/profiles/${id}/activate`, { method: 'POST' });
            if (res.ok) {
                showAlert('Active profile updated successfully.');
                loadProfiles();
            } else {
                showAlert('Failed to activate profile.', true);
            }
        }

        async function deleteProfile(id) {
            if (!confirm('Are you sure you want to delete this profile?')) return;
            const res = await fetch(`/api/profiles/${id}`, { method: 'DELETE' });
            if (res.ok) {
                showAlert('Profile deleted.');
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
                    showAlert('Connection successful! ' + result.message);
                } else {
                    showAlert('Connection failed: ' + result.message, true);
                }
            } catch (err) {
                showAlert('Network error: ' + err.message, true);
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
                    showAlert('Error saving profile: ' + (err.detail || 'Unknown error'), true);
                }
            } catch (err) {
                showAlert('Network error: ' + err.message, true);
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
