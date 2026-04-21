// --- USER ACCOUNT MGMT ---
function saveEmail() {
    const email = document.getElementById('userEmail').value.trim();
    if (!email) return alert("Please enter an email");
    localStorage.setItem('opandz_email', email);
    location.reload();
}

function getSavedEmail() {
    return localStorage.getItem('opandz_email');
}

// --- VAULT LISTING ---
async function fetchVault() {
    const email = getSavedEmail();
    const container = document.getElementById('vaultList');
    
    if (!email) {
        if (container) container.innerHTML = `<p class="p-4 bg-blue-50 text-blue-700 rounded">Please set your email in the sidebar.</p>`;
        return;
    }

    container.innerHTML = `<div class="animate-pulse text-slate-400">Loading your vault...</div>`;

    const VAULT_REQUEST_TIMEOUT_MS = 30000;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), VAULT_REQUEST_TIMEOUT_MS);

    try {
        // Relative path hits your src.api.vault router
        const res = await fetch(`/vault/${encodeURIComponent(email)}`, {
            signal: controller.signal
        });
        if (!res.ok) {
            let detail = `HTTP ${res.status}`;
            try {
                const payload = await res.json();
                detail = payload.detail || detail;
            } catch (_) {}
            throw new Error(detail);
        }
        const data = await res.json();
        
        if (!container) return;

        if (data.length === 0) {
            container.innerHTML = `<p class="text-slate-400">Your vault is empty.</p>`;
            return;
        }

        container.innerHTML = data.map(item => `
            <div class="bg-white p-4 rounded-xl border flex justify-between items-center shadow-sm hover:shadow-md transition">
                <div>
                    <h4 class="font-bold text-slate-800">${item.display_name}</h4>
                    <p class="text-xs text-slate-400">Status: <span class="uppercase font-bold">${item.status}</span></p>
                </div>
                <div class="flex gap-2">
                    <a href="/view/${item.request_id}" class="bg-slate-900 text-white px-4 py-2 rounded-lg text-sm">View</a>
                    <button onclick="deleteDoc('${item.request_id}')" class="text-slate-300 hover:text-red-500">🗑️</button>
                </div>
            </div>
        `).join('');
    } catch (err) {
        console.error("Vault Load Error:", err);
        if (container) {
            const message = err.name === 'AbortError'
                ? `Vault request timed out after ${VAULT_REQUEST_TIMEOUT_MS / 1000} seconds. The Supabase query or network is hanging.`
                : err.message;

            container.innerHTML = `
                <div class="bg-red-50 border border-red-200 text-red-700 p-4 rounded-lg">
                    <p class="font-semibold">Could not load your vault.</p>
                    <p class="text-sm mt-1">${message}</p>
                    <button onclick="fetchVault()" class="mt-3 bg-red-600 text-white px-3 py-2 rounded-lg text-sm">Try again</button>
                </div>
            `;
        }
    } finally {
        clearTimeout(timeoutId);
    }
}

// --- DELETE LOGIC ---
async function deleteDoc(id) {
    if (!confirm("Are you sure you want to delete this extraction?")) return;
    try {
        const res = await fetch(`/vault/${id}`, { method: 'DELETE' });
        if (res.ok) {
            fetchVault();
        }
    } catch (err) {
        alert("Delete failed. Check console.");
    }
}

// Initialize based on which page we are on
document.addEventListener('DOMContentLoaded', () => {
    const email = getSavedEmail();
    const emailInput = document.getElementById('userEmail');
    if (email && emailInput) {
        emailInput.value = email;
    }
    if (document.getElementById('vaultList')) {
        fetchVault();
    }
});
