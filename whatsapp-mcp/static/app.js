document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    fetchState();
    
    // Check state periodically
    setInterval(fetchState, 10000);
});

// --- Tab Navigation ---
function initTabs() {
    const links = document.querySelectorAll('.nav-links li');
    links.forEach(link => {
        link.addEventListener('click', () => {
            links.forEach(l => l.classList.remove('active'));
            link.classList.add('active');
            
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            const targetId = link.getAttribute('data-target');
            document.getElementById(targetId).classList.add('active');
            
            if (targetId === 'memory-tab') fetchFacts();
            if (targetId === 'keys-tab') fetchEnv();
            if (targetId === 'logs-tab') fetchLogs();
        });
    });
}

// --- API Helpers ---
async function apiGet(endpoint) {
    const res = await fetch(`/api/${endpoint}`);
    return await res.json();
}
async function apiPost(endpoint, data) {
    const res = await fetch(`/api/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    return await res.json();
}
async function apiDelete(endpoint) {
    const res = await fetch(`/api/${endpoint}`, { method: 'DELETE' });
    return await res.json();
}

// --- State Management ---
let currentState = null;

async function fetchState() {
    currentState = await apiGet('state');
    renderState();
}

function renderState() {
    if (!currentState) return;
    
    // Status Indicator
    const dot = document.getElementById('bot-status-dot');
    const text = document.getElementById('bot-status-text');
    if (currentState.active) {
        dot.className = 'dot active';
        text.textContent = 'Bot is Active';
        document.getElementById('toggle-active').checked = true;
    } else {
        dot.className = 'dot inactive';
        text.textContent = 'Bot is Paused';
        document.getElementById('toggle-active').checked = false;
    }
    
    document.getElementById('toggle-mute-groups').checked = currentState.mute_all_groups || false;

    // Instructions
    const instList = document.getElementById('instructions-list');
    instList.innerHTML = '';
    (currentState.general_instructions || []).forEach((inst, i) => {
        const li = document.createElement('li');
        li.innerHTML = `<span>${inst}</span> <span class="remove-icon" onclick="removeInstruction(${i})">✕</span>`;
        instList.appendChild(li);
    });

    // Muted
    const mutedList = document.getElementById('muted-list');
    mutedList.innerHTML = '';
    (currentState.muted_jids || []).forEach((jid, i) => {
        const li = document.createElement('li');
        li.innerHTML = `<span>${jid}</span> <span class="remove-icon" onclick="removeMuted(${i})">✕</span>`;
        mutedList.appendChild(li);
    });
}

document.getElementById('toggle-active').addEventListener('change', async (e) => {
    await apiPost('state', { active: e.target.checked });
    fetchState();
});

document.getElementById('toggle-mute-groups').addEventListener('change', async (e) => {
    await apiPost('state', { mute_all_groups: e.target.checked });
    fetchState();
});

async function addInstruction() {
    const input = document.getElementById('new-instruction');
    const val = input.value.trim();
    if (!val) return;
    const insts = currentState.general_instructions || [];
    insts.push(val);
    await apiPost('state', { general_instructions: insts });
    input.value = '';
    fetchState();
}
async function removeInstruction(idx) {
    const insts = currentState.general_instructions || [];
    insts.splice(idx, 1);
    await apiPost('state', { general_instructions: insts });
    fetchState();
}

async function addMuted() {
    const input = document.getElementById('new-muted');
    const val = input.value.trim();
    if (!val) return;
    const muts = currentState.muted_jids || [];
    if (!muts.includes(val)) muts.push(val);
    await apiPost('state', { muted_jids: muts });
    input.value = '';
    fetchState();
}
async function removeMuted(idx) {
    const muts = currentState.muted_jids || [];
    muts.splice(idx, 1);
    await apiPost('state', { muted_jids: muts });
    fetchState();
}

// --- Env Keys ---
async function fetchEnv() {
    const env = await apiGet('env');
    const tbody = document.getElementById('env-table-body');
    tbody.innerHTML = '';
    for (const [key, val] of Object.entries(env)) {
        const masked = val.length > 8 ? val.substring(0, 4) + '...' + val.substring(val.length - 4) : '***';
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><code>${key}</code></td>
            <td>${masked}</td>
            <td><button class="btn secondary" style="padding: 4px 8px;" onclick="editEnv('${key}')">Replace</button></td>
        `;
        tbody.appendChild(tr);
    }
}

function editEnv(key) {
    document.getElementById('new-env-key').value = key;
    document.getElementById('new-env-val').focus();
}

async function updateEnv() {
    const key = document.getElementById('new-env-key').value.trim();
    const val = document.getElementById('new-env-val').value.trim();
    if (!key || !val) return alert('Key and value required');
    await apiPost('env', { key, value: val });
    document.getElementById('new-env-key').value = '';
    document.getElementById('new-env-val').value = '';
    fetchEnv();
}

// --- Memory (RAG) ---
async function fetchFacts() {
    const facts = await apiGet('facts');
    const tbody = document.getElementById('facts-table-body');
    tbody.innerHTML = '';
    facts.forEach(f => {
        const tr = document.createElement('tr');
        const date = new Date(f.created_at).toLocaleString();
        tr.innerHTML = `
            <td>${f.chat_jid.split('@')[0]}</td>
            <td>${f.fact_text}</td>
            <td>${date}</td>
            <td><button class="btn danger" onclick="deleteFact(${f.id})">Delete</button></td>
        `;
        tbody.appendChild(tr);
    });
}

async function addFact() {
    const jid = document.getElementById('new-fact-jid').value.trim();
    const txt = document.getElementById('new-fact-text').value.trim();
    if (!jid || !txt) return alert('JID and Fact required');
    
    await apiPost('facts', { chat_jid: jid, fact_text: txt });
    document.getElementById('new-fact-jid').value = '';
    document.getElementById('new-fact-text').value = '';
    fetchFacts();
}

async function deleteFact(id) {
    if (!confirm('Delete this fact permanently?')) return;
    await apiDelete(`facts/${id}`);
    fetchFacts();
}

// --- Logs ---
async function fetchLogs() {
    const data = await apiGet('logs');
    const view = document.getElementById('terminal-logs');
    view.textContent = data.logs || 'No logs found.';
    view.scrollTop = view.scrollHeight;
}
