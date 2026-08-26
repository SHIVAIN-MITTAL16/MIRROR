import { renderIntelligenceCore } from '/ui/intelligence-core.js';
import { replayPipeline } from '/ui/decision-pipeline.js';

const intro = document.querySelector('#cinematic-intro');
const introVideo = document.querySelector('#intro-video');
const skipIntro = document.querySelector('#skip-intro');
const replayIntro = document.querySelector('#replay-intro');
let introClosed = false;

function completeIntro() {
  if (introClosed) return;
  introClosed = true;
  document.body.classList.add('intro-complete');
  window.setTimeout(() => intro?.remove(), 1100);
}

replayIntro?.addEventListener('click', () => {
  window.location.reload();
});

if (intro && introVideo) {
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  skipIntro?.addEventListener('click', completeIntro);
  introVideo.addEventListener('ended', completeIntro, { once: true });
  introVideo.addEventListener('error', completeIntro, { once: true });

  if (reducedMotion) {
    completeIntro();
  } else {
    const startIntro = () => {
      introVideo.play().catch(() => {
        // Keep the intro visible if autoplay is temporarily blocked.
        // The user can still use the explicit Skip intro control.
      });
    };

    if (introVideo.readyState >= HTMLMediaElement.HAVE_METADATA) {
      startIntro();
    } else {
      introVideo.addEventListener('loadedmetadata', startIntro, { once: true });
    }
  }
}

const freshOverrides = document.createElement('link');
freshOverrides.rel = 'stylesheet';
freshOverrides.href = '/ui/core-overrides.css?qa=metrics';
document.head.append(freshOverrides);

const $ = selector => document.querySelector(selector);
const money = value => '₹' + new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(value ?? 0);
const pct = value => (value * 100).toFixed(2) + '%';
const pct1 = value => (value * 100).toFixed(1) + '%';
const get = async url => { const response = await fetch(url); if (!response.ok) throw Error(await response.text()); return response.json(); };
const state = { rows: [], cancel: null, defaultRow: null, selectedKey: null };
const outcomeClass = value => value === 'NEGOTIATE' ? 'negotiate' : value === 'ACCEPT' ? 'accept' : 'reject';

function setRequestObject(detail) {
  const request = detail.buyer_request;
  $('#request-sku').textContent = request.target_sku_id;
  $('#request-stats').innerHTML = '<span>' + request.requested_quantity + ' units</span><span>' + money(request.budget) + '</span><span>Deadline · ' + request.deadline_days + ' days</span>';
  $('#request-constraints').innerHTML = '<span><b>PROFILE</b>' + request.brand_preference + ' · ' + request.min_ram_gb + 'GB RAM · ' + request.min_storage_gb + 'GB</span><span><b>FULFILMENT</b>' + request.available + ' available · ' + (request.incoming_available ? request.incoming_quantity + ' incoming' : 'no incoming') + '</span><span><b>FLEXIBILITY</b>Price ' + request.price_flexibility + ' · Qty ' + request.quantity_flexibility + ' · Timing ' + request.timing_flexibility + '</span><span><b>ALTERNATIVES</b>' + request.eligible_substitute_skus.length + ' eligible substitutes</span>';
  $('#request-meta').textContent = 'Seed ' + request.experiment_seed + ' · Request ' + request.request_id + ' · ' + request.classification;
}

function setHeroState(detail) {
  const result = detail.decision;
  const candidate = result.best_candidate;
  const label = result.decision + (candidate ? ' · ' + candidate.action_type : result.classification ? ' · ' + result.classification : '');
  $('#hero-state').textContent = 'REQUEST ' + detail.buyer_request.request_id + ' · ' + label;
  $('#hero-state').className = 'hero-state ' + outcomeClass(result.decision);
  renderIntelligenceCore($('#hero-core'), detail, 'hero');
}

function setRiskSelection(detail) {
  const result = detail.decision;
  const candidate = result.best_candidate || result.reference;
  $('#risk-selected-value').textContent = candidate ? money(candidate.p05_net_contribution) + ' / ' + money(candidate.expected_net_contribution) : '—';
  $('#risk-selected-name').textContent = candidate ? candidate.sku_id : 'NO SAFE DEAL';
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
  renderIntelligenceCore($('#pipeline-core'), detail, 'pipeline');
}

async function select(seed, requestId) {
  state.cancel?.();
  $('#seed').value = seed;
  $('#request-id').value = requestId;
  const detail = await get('/dashboard/request/' + seed + '/' + requestId);
  state.selectedKey = seed + ':' + requestId;
  setRequestObject(detail);
  setHeroState(detail);
  setRiskSelection(detail);
  renderIntelligenceCore($('#request-core'), detail, 'compact');
  renderStage(detail, 0);
  state.cancel = replayPipeline($('#pipeline-stages'), detail.decision, phase => renderStage(detail, phase), () => renderStage(detail, 6));
  $('#explain').innerHTML = detail.explanation.map(item => '<li>' + item + '</li>').join('');
  setTransaction(detail);
  setPayment(detail);
  populateExplorer();
}

function populateExplorer() {
  const body = $('#rows');
  const decision = $('#decision-filter').value;
  const classification = $('#class-filter').value;
  const rows = state.rows.filter(row => (decision === 'ALL' || row.decision === decision) && (classification === 'ALL' || row.classification === classification));
  body.innerHTML = rows.map(row => '<tr tabindex="0" class="' + (state.selectedKey === row.seed + ':' + row.request_id ? 'selected-row' : '') + '" data-seed="' + row.seed + '" data-id="' + row.request_id + '"><td>' + row.seed + '</td><td>' + row.request_id + '</td><td><i class="dot" style="background:' + (row.classification === 'HARD_REJECT' ? 'var(--reject)' : row.classification === 'CONSTRAINT_CONFLICT' ? 'var(--negotiate)' : 'var(--signal-cyan)') + '"></i>' + row.classification + '</td><td class="decision-' + outcomeClass(row.decision) + '">' + row.decision + '</td><td>' + (row.lever || '—') + '</td><td class="data">' + money(row.expected_net_contribution) + '</td></tr>').join('');
  $('#selected-identity').textContent = state.selectedKey ? 'SELECTED · ' + state.selectedKey.replace(':', ' / REQUEST ') : 'SELECT A ROW TO REPLAY';
  body.querySelectorAll('tr[data-seed]').forEach(row => {
    row.onclick = () => { select(row.dataset.seed, row.dataset.id); $('#request').scrollIntoView(); };
    row.onkeydown = event => event.key === 'Enter' && row.click();
  });
}

function renderAggregate(analysis, levers, rows, metrics) {
  const global = analysis.global_experiment_summary;
  const seeds = Object.keys(analysis.five_seed_stability.per_seed);
  $('#mean-uplift').textContent = pct(metrics.mean_seed_uplift);
  $('#seed-network').innerHTML = seeds.map((seed, index) => { const seedResult = analysis.five_seed_stability.per_seed[seed]; return '<span class="seed-node"><b>' + seed.slice(-2) + '</b><small>A ' + pct1(seedResult.accept_pct) + '</small><small>P05 ' + money(seedResult.mean_selected_p05_net_contribution) + '</small></span>' + (index < seeds.length - 1 ? '<i></i>' : ''); }).join('');
  $('#seed-proof').textContent = metrics.positive_seed_count + ' / ' + seeds.length + ' seeds positive · ' + metrics.at_least_five_pct_seed_count + ' / ' + seeds.length + ' seeds achieved at least 5% uplift.';
  $('#pooled-uplift').textContent = pct(metrics.pooled_uplift);
  $('#feasible-value').textContent = money(metrics.baseline_reference_improvement) + ' · ' + pct(metrics.baseline_reference_improvement_pct);
  $('#feasible-count').textContent = metrics.baseline_reference_count + ' requests with a feasible baseline.';
  $('#recovery-number').textContent = global.constraint_conflict_rescue_count + ' / ' + global.constraint_conflict_count;
  $('#rescue-rate').textContent = pct1(global.constraint_conflict_rescue_rate) + ' rescue rate across Constraint-Conflict requests.';
  $('#recovery-recovered').style.width = pct1(global.constraint_conflict_rescue_rate);
  $('#recovery-recovered-label').textContent = global.constraint_conflict_rescue_count;
  $('#recovery-failed-label').textContent = global.constraint_conflict_count - global.constraint_conflict_rescue_count;
  $('#recovery-total-label').textContent = global.constraint_conflict_count;
  $('#risk-copy').innerHTML = '<b class="data">' + metrics.negotiable_candidate_count + '</b> candidates evaluated · <b class="data">' + global.risk_gate_rejections + '</b> failed · <b class="data">' + (metrics.negotiable_candidate_count - global.risk_gate_rejections) + '</b> passed the P05 risk gate: <b>' + pct1(global.risk_gate_rejection_rate) + '</b> rejected.';
  $('#risk-evaluated').textContent = metrics.negotiable_candidate_count;
  $('#risk-rejected').textContent = global.risk_gate_rejections;
  $('#risk-passed').textContent = metrics.negotiable_candidate_count - global.risk_gate_rejections;
  const totalLevers = Object.values(levers.by_action).reduce((sum, item) => sum + item.count, 0);
  const maximum = Math.max(...Object.values(levers.by_action).map(item => item.count), 1);
  $('#lever-tracks').innerHTML = ['SUBSTITUTION','QUANTITY','TIMING','PRICE'].map(action => {
    const count = levers.by_action[action].count;
    return '<div class="lever-track ' + (count === 0 ? 'zero' : '') + '"><b>' + action + '</b><span style="--width:' + count / maximum * 100 + '%"></span><b class="data">' + count + ' <small>' + pct1(count / (totalLevers || 1)) + '</small></b></div>';
  }).join('');
  $('#lever-total').textContent = totalLevers;
  $('#price-detail').textContent = 'Price candidates were evaluated from the persisted alternatives, but none exceeded the strict improvement threshold. Price candidates evaluated: ' + metrics.price_candidates + ' · Passed the P05 gate: ' + metrics.price_passed_risk_gate + ' · Selected: ' + levers.by_action.PRICE.count + '.';
}

async function boot() {
  const payload = await Promise.all([get('/dashboard/analysis'), get('/dashboard/levers'), get('/dashboard/requests'), get('/dashboard/product-metrics')]);
  const analysis = payload[0], levers = payload[1], rows = payload[2], metrics = payload[3];
  state.rows = rows;
  document.querySelector('.console-head span').textContent = rows.length + ' persisted request decisions';
  [...new Set(rows.map(row => row.seed))].forEach(seed => $('#seed').add(new Option(seed, seed)));
  [...new Set(rows.map(row => row.classification))].forEach(classification => $('#class-filter').add(new Option(classification, classification)));
  state.defaultRow = rows.find(row => row.decision === 'NEGOTIATE' && row.lever === 'SUBSTITUTION') || rows[0];
  renderAggregate(analysis, levers, rows, metrics);
  populateExplorer();
  $('#load').onclick = () => select($('#seed').value, $('#request-id').value);
  $('#analyze').onclick = () => { select(state.defaultRow.seed, state.defaultRow.request_id); $('#request').scrollIntoView(); };
  $('#decision-filter').onchange = populateExplorer;
  $('#class-filter').onchange = populateExplorer;
  $('#clear-filters').onclick = () => { $('#decision-filter').value = 'ALL'; $('#class-filter').value = 'ALL'; populateExplorer(); };
  renderIntelligenceCore($('#hero-core'), { decision:'REJECT', classification:'IDLE' }, 'hero');
  select(state.defaultRow.seed, state.defaultRow.request_id);
}

boot().catch(error => { document.body.innerHTML = '<pre>' + error.message + '</pre>'; });
