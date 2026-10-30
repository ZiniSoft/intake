const state = { codes: [] };
const $ = (id) => document.getElementById(id);

function setMessage(id, text, success = false) { const node = $(id); node.textContent = text; node.classList.toggle('success', success); }
function getCookie(name) { return document.cookie.split('; ').find((row) => row.startsWith(`${name}=`))?.split('=')[1] || ''; }
function authHeaders() { return { 'Content-Type': 'application/json', 'X-CSRF-Token': decodeURIComponent(getCookie('intake_csrf')) }; }
function showConsole(identity) { $('loginPanel').classList.add('hidden'); $('consolePanel').classList.remove('hidden'); $('logoutButton').classList.remove('hidden'); $('identityLabel').textContent = `${identity.email} / ${identity.role}`; }
function showLogin() { $('loginPanel').classList.remove('hidden'); $('consolePanel').classList.add('hidden'); $('logoutButton').classList.add('hidden'); }

async function api(path, options = {}) { const response = await fetch(path, options); const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : body.detail?.message || 'Request failed'); return body.data ?? body; }

$('loginForm').addEventListener('submit', async (event) => {
  event.preventDefault(); setMessage('loginMessage', '');
  try {
    await api('/api/v1/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ subject: $('subject').value.trim(), password: $('password').value, otp: $('loginOtp').value || null }) });
    showConsole(await api('/api/v1/auth/me', { headers: authHeaders() }));
  } catch (error) { setMessage('loginMessage', error.message); }
});

$('setupForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  setMessage('setupMessage', '');
  try { const body = await api('/api/v1/auth/mfa/setup', { method: 'POST', headers: authHeaders(), body: JSON.stringify({ current_password: $('setupPassword').value, otp: $('setupOtp').value || null }) }); $('setupPassword').value = ''; $('setupOtp').value = ''; $('secretValue').textContent = body.secret; $('setupResult').classList.remove('hidden'); setMessage('setupMessage', 'Secret generated. Add it to your authenticator app.', true); } catch (error) { setMessage('setupMessage', error.message); }
});

$('confirmForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try { await api('/api/v1/auth/mfa/confirm', { method: 'POST', headers: authHeaders(), body: JSON.stringify({ code: $('otpCode').value }) }); setMessage('setupMessage', 'MFA is enabled for this account.', true); $('otpCode').value = ''; } catch (error) { setMessage('setupMessage', error.message); }
});

$('recoveryForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  setMessage('recoveryMessage', '');
  if (!window.confirm('Generate a new set? Previous recovery codes will stop working.')) return;
  try { const body = await api('/api/v1/auth/mfa/recovery-codes', { method: 'POST', headers: authHeaders(), body: JSON.stringify({ current_password: $('recoveryPassword').value, otp: $('recoveryOtp').value }) }); $('recoveryPassword').value = ''; $('recoveryOtp').value = ''; state.codes = body.recovery_codes; $('codesGrid').innerHTML = state.codes.map((code) => `<code>${code}</code>`).join(''); $('recoveryResult').classList.remove('hidden'); setMessage('recoveryMessage', 'New codes generated. Store them offline.', true); } catch (error) { setMessage('recoveryMessage', error.message); }
});

$('copyButton').addEventListener('click', async () => { await navigator.clipboard.writeText(state.codes.join('\n')); setMessage('recoveryMessage', 'Recovery codes copied.', true); });
$('logoutButton').addEventListener('click', async () => { try { await api('/api/v1/auth/logout', { method: 'POST', headers: authHeaders() }); } finally { state.codes = []; showLogin(); } });

(async () => { try { showConsole(await api('/api/v1/auth/me', { headers: authHeaders() })); } catch { showLogin(); } })();
