function showAlert(msg, isError = false) {
    const el = document.getElementById('alertBox');
    el.className = isError ? 'error' : 'ok';
    el.textContent = (isError ? '[ERROR] ' : '[OK] ') + msg;
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
