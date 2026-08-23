const format = value => new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(value ?? 0);
const identity = (a, b) => Boolean(b) && ['sku_id','action_type','quantity','delivery_window_days','candidate_price'].every(key => a[key] === b[key]);
const points = { PRICE:[50,18,'top'], QUANTITY:[84,48,'right'], TIMING:[50,79,'bottom'], SUBSTITUTION:[16,48,'left'] };
const decisionClass = result => result.decision === 'NEGOTIATE' ? 'negotiate' : result.decision === 'ACCEPT' ? 'accept' : 'reject';

export function renderIntelligenceCore(host, detail, mode = 'pipeline') {
  const result = detail.decision && typeof detail.decision === 'object' ? detail.decision : detail;
  const candidates = result.candidates || [];
  const best = result.best_candidate;
  const compact = mode === 'compact';
  const showRoutes = !compact && result.decision !== 'ACCEPT';
  const active = Object.entries(points).map(([type, point]) => {
    const group = candidates.filter(candidate => candidate.action_type === type);
    if (!group.length || result.decision === 'ACCEPT') return null;
    const chosen = group.find(candidate => identity(candidate,best)) || group[0];
    return { type, x:point[0], y:point[1], side:point[2], chosen, selected:identity(chosen,best), passes:group.some(candidate => candidate.passes_risk_gate) };
  }).filter(Boolean);
  const route = active.map(item => {
    const d = 'M50 48 Q' + (50 + item.x) / 2 + ' ' + ((48 + item.y) / 2 - 8) + ' ' + item.x + ' ' + item.y;
    const state = item.selected ? 'selected' : item.passes ? 'pass' : 'failed';
    return '<g class="core-route ' + state + '"><path class="route-base" d="' + d + '"/><path class="route-signal" d="' + d + '"/><circle cx="' + item.x + '" cy="' + item.y + '" r="2.2"/></g>';
  }).join('');
  const panels = active.map(item => '<div class="candidate-card ' + item.side + ' ' + (item.selected ? 'selected' : '') + ' ' + (item.passes ? '' : 'failed') + '" style="--x:' + item.x + '%;--y:' + item.y + '%"><b>' + (item.selected ? 'SELECTED · ' : '') + item.type + '</b><span>Expected <strong>₹' + format(item.chosen.expected_net_contribution) + '</strong></span><span>P05 <strong>₹' + format(item.chosen.p05_net_contribution) + '</strong></span><small>' + (item.passes ? 'RISK GATE PASSED' : 'P05 GATE FAILED') + '</small></div>').join('');
  const terminal = result.decision === 'NEGOTIATE' ? 'NEGOTIATE · ' + best.action_type : result.decision === 'ACCEPT' ? 'ACCEPT · BASELINE' : result.classification === 'HARD_REJECT' ? 'REJECT · HARD CONSTRAINT' : 'REJECT · RESCUE FAILED';
  const fracture = result.baseline_feasible === false ? 'fractured' : '';
  host.innerHTML = '<div class="intelligence-core ' + decisionClass(result) + ' ' + (compact ? 'compact' : '') + '" data-mode="' + mode + '"><svg class="core-map" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id="signal" x1="0" x2="1"><stop stop-color="#22D3EE" stop-opacity=".08"/><stop offset=".5" stop-color="#DDFBFF"/><stop offset="1" stop-color="#22D3EE" stop-opacity=".12"/></linearGradient><filter id="glow"><feGaussianBlur stdDeviation="1.2" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs><path class="axis ' + fracture + '" d="M50 7 C50 27 50 72 50 93"/><path class="axis-signal ' + fracture + '" d="M50 7 C50 27 50 72 50 93"/>' + (showRoutes ? route : '') + '<g class="neural"><path d="M43 45 L50 40 L58 44 L60 52 L54 58 L45 56 Z M43 45 L54 58 M50 40 L45 56 M58 44 L45 56"/><circle cx="43" cy="45" r="1"/><circle cx="50" cy="40" r="1"/><circle cx="58" cy="44" r="1"/><circle cx="60" cy="52" r="1"/><circle cx="54" cy="58" r="1"/><circle cx="45" cy="56" r="1"/></g></svg><div class="core-node buyer">BUYER<br><small>REQUEST</small></div><div class="orbital outer"></div><div class="orbital inner"></div><div class="nucleus"></div>' + (showRoutes ? panels : '') + '<div class="core-node merchant">MERCHANT<br><small>INVENTORY</small></div><div class="core-result">' + terminal + '</div></div>';
}
