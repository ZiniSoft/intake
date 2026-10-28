const state = { token: sessionStorage.getItem('intake_access_token'), codes: [] };
const $ = (id) => document.getElementById(id);

function setMessage(id, text, success = false) { const node = $(id); node.textContent = text; node.classList.toggle('success', success); }
function authHeaders() { return { Authorization: `Bearer ${state.token}`, 'Content-Type': 'application/json' }; }
function showConsole(identity) { $('loginPanel').classList.add('hidden'); $('consolePanel').classList.remove('hidden'); $('logoutButton').classList.remove('hidden'); $('identityLabel').textContent = `${identity.email} / ${identity.role}`; }
function showLogin() { $('loginPanel').classList.remove('hidden'); $('consolePanel').classList.add('hidden'); $('logoutButton').classList.add('hidden'); }

async function api(path, options = {}) { const response = await fetch(path, options); const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(body.detail || 'Request failed'); return body; }

$('loginForm').addEventListener('submit', async (event) => {
  event.preventDefault(); setMessage('loginMessage', '');
  try {
    const body = await api('/api/v1/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ subject: $('subject').value.trim(), password: $('password').value }) });
    state.token = body.access_token; sessionStorage.setItem('intake_access_token', state.token);
    showConsole(await api('/api/v1/auth/me', { headers: authHeaders() }));
  } catch (error) { setMessage('loginMessage', error.message); }
});

$('setupButton').addEventListener('click', async () => {
  setMessage('setupMessage', '');
  try { const body = await api('/api/v1/auth/mfa/setup', { method: 'POST', headers: authHeaders() }); $('secretValue').textContent = body.secret; $('setupResult').classList.remove('hidden'); setMessage('setupMessage', 'Secret generated. Add it to your authenticator app.', true); } catch (error) { setMessage('setupMessage', error.message); }
});

$('confirmForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try { await api('/api/v1/auth/mfa/confirm', { method: 'POST', headers: authHeaders(), body: JSON.stringify({ code: $('otpCode').value }) }); setMessage('setupMessage', 'MFA is enabled for this account.', true); $('otpCode').value = ''; } catch (error) { setMessage('setupMessage', error.message); }
});

$('recoveryButton').addEventListener('click', async () => {
  setMessage('recoveryMessage', '');
  if (!window.confirm('Generate a new set? Previous recovery codes will stop working.')) return;
  try { const body = await api('/api/v1/auth/mfa/recovery-codes', { method: 'POST', headers: authHeaders() }); state.codes = body.recovery_codes; $('codesGrid').innerHTML = state.codes.map((code) => `<code>${code}</code>`).join(''); $('recoveryResult').classList.remove('hidden'); setMessage('recoveryMessage', 'New codes generated. Store them offline.', true); } catch (error) { setMessage('recoveryMessage', error.message); }
});

$('copyButton').addEventListener('click', async () => { await navigator.clipboard.writeText(state.codes.join('\n')); setMessage('recoveryMessage', 'Recovery codes copied.', true); });
$('logoutButton').addEventListener('click', () => { state.token = null; state.codes = []; sessionStorage.removeItem('intake_access_token'); showLogin(); });

(async () => { if (!state.token) return; try { showConsole(await api('/api/v1/auth/me', { headers: authHeaders() })); } catch { state.token = null; sessionStorage.removeItem('intake_access_token'); } })();
