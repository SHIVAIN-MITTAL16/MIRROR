import { apiUrl } from './api-config.js';

const root = document.createElement('section');
root.id = 'mirror-auth';
root.className = 'section auth-panel';
root.innerHTML = `<h2>Secure MIRROR session</h2>
  <p>Register or sign in as a buyer or seller. Buyer and seller actions use separate accounts; seller access is granted per Passport.</p>
  <form id="mirror-auth-form"><label>Email<input name="email" type="email" autocomplete="username" required maxlength="254"></label>
  <label>Password<input name="password" type="password" autocomplete="current-password" required minlength="12" maxlength="256"></label>
  <label>Account role<select name="role"><option value="buyer">Buyer</option><option value="seller">Seller</option></select></label>
  <button class="button" name="action" value="login">Sign in</button><button class="button button-secondary" name="action" value="register">Create account</button></form>
  <div id="mirror-auth-session" hidden><p id="mirror-auth-status" role="status"></p><button id="mirror-auth-logout" class="button button-secondary" type="button">Sign out</button>
  <div id="mirror-buyer-grant" hidden><label>Grant selected Passport to seller account ID<input id="mirror-seller-id" type="text" maxlength="64" autocomplete="off"></label><button id="mirror-create-grant" class="button" type="button">Grant seller access</button></div>
  <div id="mirror-seller-grants" hidden><h3>Passport access</h3><div id="mirror-grant-list"></div></div></div>
  <p id="mirror-auth-error" role="alert"></p>`;
document.querySelector('main')?.prepend(root);

const $ = selector => root.querySelector(selector);
let authFlowVersion = 0;
const csrf = () => window.mirrorCsrfToken || document.cookie.split('; ').find(item => item.startsWith('mirror_csrf='))?.split('=').slice(1).join('=') || '';
async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!['GET', 'HEAD'].includes((options.method || 'GET').toUpperCase())) headers.set('X-Mirror-CSRF', decodeURIComponent(csrf()));
  const response = await fetch(apiUrl(path), { ...options, headers, credentials: 'include' });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : data?.detail?.message || `Request failed (${response.status}).`);
  if (typeof data?.csrf_token === 'string') window.mirrorCsrfToken = data.csrf_token;
  return data;
}

function showSession(user) {
  if (!user) window.mirrorCsrfToken = '';
  $('#mirror-auth-form').hidden = Boolean(user);
  $('#mirror-auth-session').hidden = !user;
  $('#mirror-auth-status').textContent = user ? `Signed in as ${user.email} · ${user.role}${user.seller_id ? ` · Seller account ID: ${user.seller_id}` : ''}` : '';
  $('#mirror-buyer-grant').hidden = !user || user.role !== 'buyer';
  $('#mirror-seller-grants').hidden = !user || user.role !== 'seller';
  window.mirrorUser = user || null;
  window.dispatchEvent(new CustomEvent('mirror:auth-change', { detail: { user: user || null } }));
  if (user?.role === 'buyer') loadGrants();
  if (user?.role === 'seller') loadGrants();
}

async function loadGrants() {
  try {
    const grants = await api('/api/seller/grants');
    const list = $('#mirror-grant-list');
    list.replaceChildren();
    for (const grant of grants) {
      const row = document.createElement('p');
      row.textContent = `${grant.passport_id} · ${grant.status} · ${window.mirrorUser?.role === 'buyer' ? `seller ${grant.seller_id}` : 'buyer account'} · expires ${new Date(grant.expires_at).toLocaleString()}`;
      if (window.mirrorUser?.role === 'seller' && grant.status === 'pending') {
        const accept = document.createElement('button'); accept.type = 'button'; accept.textContent = 'Accept access';
        accept.addEventListener('click', async () => {
          try {
            await api(`/api/seller/grants/${encodeURIComponent(grant.id)}/accept`, { method: 'POST' });
            window.dispatchEvent(new CustomEvent('mirror:passport-selected', { detail: { passportId: grant.passport_id } }));
            await loadGrants();
          }
          catch (error) { $('#mirror-auth-error').textContent = error.message; }
        }); row.append(' ', accept);
      }
      if (window.mirrorUser?.role === 'buyer' && grant.status !== 'revoked') {
        const revoke = document.createElement('button'); revoke.type = 'button'; revoke.textContent = 'Revoke';
        revoke.addEventListener('click', async () => {
          try { await api(`/api/passports/${encodeURIComponent(grant.passport_id)}/seller-grants/${encodeURIComponent(grant.id)}`, { method: 'DELETE' }); await loadGrants(); }
          catch (error) { $('#mirror-auth-error').textContent = error.message; }
        }); row.append(' ', revoke);
      }
      list.append(row);
    }
    if (!grants.length) list.textContent = 'No seller access grants.';
  } catch (error) { $('#mirror-auth-error').textContent = error.message; }
}

$('#mirror-auth-form').addEventListener('submit', async event => {
  event.preventDefault();
  authFlowVersion += 1;
  const form = event.currentTarget;
  const action = event.submitter?.value === 'register' ? 'register' : 'login';
  const payload = { email: form.elements.email.value, password: form.elements.password.value };
  if (action === 'register') payload.role = form.elements.role.value;
  try { $('#mirror-auth-error').textContent = ''; await api(`/api/auth/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); showSession(await api('/api/auth/me')); }
  catch (error) { $('#mirror-auth-error').textContent = error.message; }
});
$('#mirror-auth-logout').addEventListener('click', async () => {
  authFlowVersion += 1;
  try { await api('/api/auth/logout', { method: 'POST' }); showSession(null); }
  catch (error) { $('#mirror-auth-error').textContent = error.message; }
});
$('#mirror-create-grant').addEventListener('click', async () => {
  const passportId = document.querySelector('#mvp-passport-select')?.value;
  if (!passportId) { $('#mirror-auth-error').textContent = 'Select a Passport before inviting a seller.'; return; }
  try {
    await api(`/api/passports/${encodeURIComponent(passportId)}/seller-grants`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ seller_id: $('#mirror-seller-id').value.trim() }) });
    $('#mirror-auth-error').textContent = 'Seller access granted as pending. The account owner must sign in and accept this Passport-specific grant.'; await loadGrants();
  } catch (error) { $('#mirror-auth-error').textContent = error.message; }
});

// This no-store endpoint returns an authenticated session and its CSRF token,
// or a normal anonymous result without creating an expected browser 401.
api('/api/auth/session').then(session => {
  if (authFlowVersion !== 0) return;
  if (session.authenticated) {
    if (typeof session.csrf_token === 'string') window.mirrorCsrfToken = session.csrf_token;
    showSession(session.user);
  } else showSession(null);
}).catch(() => showSession(null));
