import { renderIntelligenceCore } from '/ui/intelligence-core.js';
import { replayPipeline } from '/ui/decision-pipeline.js';

const $ = selector => document.querySelector(selector);
const money = value => '₹' + new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(value ?? 0);
const pct = value => (value * 100).toFixed(2) + '%';
const pct1 = value => (value * 100).toFixed(1) + '%';
const get = async url => { const response = await fetch(url); if (!response.ok) throw Error(await response.text()); return response.json(); };
const state = { rows: [], cancel: null, defaultRow: null };
const outcomeClass = value => value === 'NEGOTIATE' ? 'negotiate' : value === 'ACCEPT' ? 'accept' : 'reject';

function setRequestObject(detail) {
  const request = detail.buyer_request;
  $('#request-sku').textContent = request.target_sku_id;
  $('#request-stats').innerHTML = '<span>' + request.requested_quantity + ' units</span><span>' + money(request.budget) + '</span><span>Deadline · ' + request.deadline_days + ' days</span>';
  $('#request-meta').textContent = 'Seed ' + request.experiment_seed + ' · Request ' + request.request_id + ' · ' + request.classification;
}

function setTransaction(detail) {
  const result = detail.decision;
  const candidate = result.decision === 'NEGOTIATE' ? result.best_candidate : result.reference;
  const noDeal = result.decision === 'REJECT';
  const title = noDeal ? 'No Safe Transaction Found' : candidate.sku_id;
  const badge = result.decision + (result.decision === 'NEGOTIATE' ? ' · ' + candidate.action_type : '');
  const values = [
    ['SKU', candidate?.sku_id ?? 'No-Deal'],
    ['Quantity', candidate?.quantity ?? 0],
    ['Price', candidate ? money(candidate.candidate_price) : '—'],
    ['Expected net contribution', money(candidate?.expected_net_contribution)],
    ['P05', money(candidate?.p05_net_contribution)],
  ];
  $('#transaction').innerHTML = '<p class="eyebrow">MIRROR RECOMMENDS</p><div class="decision-badge ' + outcomeClass(result.decision) + '">' + badge + '</div><h2 class="title">' + title + '</h2><div class="transaction-grid">' + values.map(value => '<div>' + value[0] + '<b class="data">' + value[1] + '</b></div>').join('') + '</div><p class="copy">' + (noDeal ? 'No-Deal is the deliberate reference: expected contribution ₹0 · P05 ₹0.' : 'Selected from the persisted candidates after the P05 downside gate.') + '</p>';
}

function setPayment(detail) {
  $('#payment').innerHTML = detail.payment.razorpay_test_mode === 'CONFIGURED'
    ? '<p class="eyebrow">Ready to transact</p><strong>Razorpay Test Mode</strong><p class="copy">A selected payable transaction may proceed to checkout.</p><button class="button">Execute Test Transaction</button>'
    : '<p class="eyebrow">Execution disabled</p><strong>RAZORPAY TEST MODE NOT CONFIGURED</strong><p class="copy">Connect Razorpay test credentials to execute. MIRROR experiment results remain real persisted data.</p><button class="button" disabled>Execute Test Transaction</button>';
}

function renderStage(detail, phase) {
  renderIntelligenceCore($('#pipeline-core'), detail, phase < 2 ? 'compact' : 'pipeline');
}

async function select(seed, requestId) {
  state.cancel?.();
  $('#seed').value = seed;
  $('#request-id').value = requestId;
  const detail = await get('/dashboard/request/' + seed + '/' + requestId);
  setRequestObject(detail);
  renderIntelligenceCore($('#request-core'), detail, 'compact');
  renderStage(detail, 0);
  state.cancel = replayPipeline($('#pipeline-stages'), detail.decision, phase => renderStage(detail, phase), () => renderStage(detail, 6));
  $('#explain').innerHTML = detail.explanation.map(item => '<li>' + item + '</li>').join('');
  setTransaction(detail);
  setPayment(detail);
}

function populateExplorer() {
  const body = $('#rows');
  body.innerHTML = state.rows.map(row => '<tr tabindex="0" data-seed="' + row.seed + '" data-id="' + row.request_id + '"><td>' + row.seed + '</td><td>' + row.request_id + '</td><td><i class="dot" style="background:' + (row.classification === 'HARD_REJECT' ? 'var(--reject)' : row.classification === 'CONSTRAINT_CONFLICT' ? 'var(--negotiate)' : 'var(--signal-cyan)') + '"></i>' + row.classification + '</td><td class="decision-' + outcomeClass(row.decision) + '">' + row.decision + '</td><td>' + (row.lever || '—') + '</td><td class="data">' + money(row.expected_net_contribution) + '</td></tr>').join('');
  body.querySelectorAll('tr[data-seed]').forEach(row => {
    row.onclick = () => { select(row.dataset.seed, row.dataset.id); $('#request').scrollIntoView(); };
    row.onkeydown = event => event.key === 'Enter' && row.click();
  });
}

function renderAggregate(analysis, levers, rows, metrics) {
  const global = analysis.global_experiment_summary;
  const seeds = Object.keys(analysis.five_seed_stability.per_seed);
  $('#mean-uplift').textContent = pct(metrics.mean_seed_uplift);
  $('#seed-network').innerHTML = seeds.map((seed, index) => '<span class="seed-node">' + seed.slice(-2) + '</span>' + (index < seeds.length - 1 ? '<i></i>' : '')).join('');
  $('#seed-proof').textContent = metrics.positive_seed_count + ' / ' + seeds.length + ' seeds positive · ' + metrics.at_least_five_pct_seed_count + ' / ' + seeds.length + ' seeds achieved at least 5% uplift.';
  $('#pooled-uplift').textContent = pct(metrics.pooled_uplift);
  $('#feasible-value').textContent = money(metrics.baseline_reference_improvement) + ' · ' + pct(metrics.baseline_reference_improvement_pct);
  $('#feasible-count').textContent = metrics.baseline_reference_count + ' requests with a feasible baseline.';
  $('#recovery-number').textContent = global.constraint_conflict_rescue_count + ' / ' + global.constraint_conflict_count;
  $('#rescue-rate').textContent = pct1(global.constraint_conflict_rescue_rate) + ' rescue rate across Constraint-Conflict requests.';
  $('#recovery-field').innerHTML = Array.from({ length: global.constraint_conflict_count }, (_, index) => '<i class="recovery-unit ' + (index < global.constraint_conflict_rescue_count ? 'recovered' : '') + '"></i>').join('');
  const fieldSize = 120;
  const failed = Math.round(metrics.negotiable_candidate_count * global.risk_gate_rejection_rate);
  $('#risk-field').innerHTML = Array.from({ length: fieldSize }, (_, index) => '<i class="risk-cell ' + (index < Math.round(fieldSize * failed / metrics.negotiable_candidate_count) ? 'failed' : '') + '"></i>').join('') + '<i class="risk-sweep"></i>';
  $('#risk-copy').innerHTML = '<b class="data">' + metrics.negotiable_candidate_count + '</b> negotiable candidates were evaluated. <b class="data">' + global.risk_gate_rejections + '</b> failed the P05 risk gate: <b>' + pct1(global.risk_gate_rejection_rate) + '</b>.';
  const maximum = Math.max(...Object.values(levers.by_action).map(item => item.count), 1);
  $('#lever-tracks').innerHTML = ['SUBSTITUTION','QUANTITY','TIMING','PRICE'].map(action => {
    const count = levers.by_action[action].count;
    return '<div class="lever-track ' + (count === 0 ? 'zero' : '') + '"><b>' + action + '</b><span style="--width:' + count / maximum * 100 + '%"></span><b class="data">' + count + '</b></div>';
  }).join('');
  $('#price-detail').textContent = 'Price candidates were evaluated from the persisted alternatives, but none exceeded the strict improvement threshold. Price candidates evaluated: ' + metrics.price_candidates + ' · Passed the P05 gate: ' + metrics.price_passed_risk_gate + ' · Selected: ' + levers.by_action.PRICE.count + '.';
}

async function boot() {
  const payload = await Promise.all([get('/dashboard/analysis'), get('/dashboard/levers'), get('/dashboard/requests'), get('/dashboard/product-metrics')]);
  const analysis = payload[0], levers = payload[1], rows = payload[2], metrics = payload[3];
  state.rows = rows;
  document.querySelector('.console-head span').textContent = rows.length + ' persisted request decisions';
  [...new Set(rows.map(row => row.seed))].forEach(seed => $('#seed').add(new Option(seed, seed)));
  state.defaultRow = rows.find(row => row.decision === 'NEGOTIATE' && row.lever === 'SUBSTITUTION') || rows[0];
  renderAggregate(analysis, levers, rows, metrics);
  populateExplorer();
  $('#load').onclick = () => select($('#seed').value, $('#request-id').value);
  $('#analyze').onclick = () => { select(state.defaultRow.seed, state.defaultRow.request_id); $('#request').scrollIntoView(); };
  renderIntelligenceCore($('#hero-core'), { decision:'ACCEPT', candidates:[], baseline_feasible:true }, 'compact');
  select(state.defaultRow.seed, state.defaultRow.request_id);
}

boot().catch(error => { document.body.innerHTML = '<pre>' + error.message + '</pre>'; });
