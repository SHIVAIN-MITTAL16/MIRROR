const format = value => new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(value ?? 0);
const identity = (a, b) => Boolean(b) && ['sku_id','action_type','quantity','delivery_window_days','candidate_price'].every(key => a[key] === b[key]);
const points = { PRICE:[50,18,'top'], QUANTITY:[84,48,'right'], TIMING:[50,79,'bottom'], SUBSTITUTION:[16,48,'left'] };
const decisionClass = result => result.decision === 'NEGOTIATE' ? 'negotiate' : result.decision === 'ACCEPT' ? 'accept' : 'reject';

export function renderIntelligenceCore(host, detail, mode = 'pipeline') {
  const result = detail.decision && typeof detail.decision === 'object' ? detail.decision : detail;
  const request = detail.buyer_request;
  const candidates = result.candidates || [];
  const best = result.best_candidate;
  const activeTypes = [...new Set(candidates.map(candidate => candidate.action_type))];
  const survivors = candidates.filter(candidate => candidate.passes_risk_gate).length;
  const candidateText = activeTypes.length ? activeTypes.join(' · ') : 'NONE';
  const baselineText = result.baseline_feasible ? 'FEASIBLE' : 'NOT FEASIBLE';
  const gateText = candidates.length ? survivors + ' / ' + candidates.length + ' PASS' : 'NOT EVALUATED';
  const selectedText = best ? best.sku_id + ' · ' + best.action_type : result.decision === 'ACCEPT' ? 'BASELINE REFERENCE' : 'NO SAFE TRANSACTION';
  const selectedValues = best ? '₹' + format(best.expected_net_contribution) + ' EXPECTED · ₹' + format(best.p05_net_contribution) + ' P05' : '';
  const stages = [
    ['BUYER REQUEST', request ? 'REQ ' + request.request_id + ' · ' + request.requested_quantity + ' UNITS · ' + request.deadline_days + 'D' : 'IDLE', 'active'],
    ['BASELINE', request ? baselineText + (result.reference ? ' · ₹' + format(result.reference.expected_net_contribution) : '') : 'IDLE', result.baseline_feasible === false ? 'failed' : 'active'],
    ['CANDIDATES', candidates.length + ' EVALUATED · ' + candidateText, candidates.length ? 'active' : 'failed'],
    ['CONSTRAINT CHECK', result.baseline_feasible ? 'BASELINE COMPATIBLE' : 'ALTERNATIVES REQUIRED', result.baseline_feasible ? 'active' : 'failed'],
    ['P05 RISK GATE', gateText, survivors ? 'active' : 'failed'],
    ['SURVIVORS', survivors + ' SAFE PATH' + (survivors === 1 ? '' : 'S'), survivors ? 'active' : 'failed'],
    ['SELECTED DECISION', selectedText + (selectedValues ? ' · ' + selectedValues : ''), decisionClass(result)]
  ];
  const art = '<div class="mirror-object"><svg viewBox="0 0 360 300" aria-hidden="true"><defs><linearGradient id="plate" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#e3f5f6" stop-opacity=".82"/><stop offset=".42" stop-color="#8fc8df" stop-opacity=".68"/><stop offset="1" stop-color="#47739b" stop-opacity=".74"/></linearGradient><linearGradient id="plate-shadow" x1="0" x2="0" y1="0" y2="1"><stop stop-color="#7fb4d2" stop-opacity=".74"/><stop offset="1" stop-color="#294c70" stop-opacity=".92"/></linearGradient><linearGradient id="facet" x1="0" x2="0.85" y1="0" y2="1"><stop stop-color="#f1ffff" stop-opacity=".92"/><stop offset=".36" stop-color="#a9d8e9" stop-opacity=".72"/><stop offset="1" stop-color="#3b6389" stop-opacity=".94"/></linearGradient><radialGradient id="aperture" cx="50%" cy="35%"><stop stop-color="#122841"/><stop offset=".72" stop-color="#091625"/><stop offset="1" stop-color="#050b15"/></radialGradient><filter id="soft-shadow"><feGaussianBlur stdDeviation="11"/></filter><filter id="surface-shadow"><feDropShadow dx="0" dy="5" stdDeviation="4" flood-color="#030812" flood-opacity=".58"/></filter></defs><ellipse class="object-shadow" cx="180" cy="263" rx="122" ry="16"/><path class="object-plate back" d="M96 86 180 40l84 46-84 48Z"/><path class="object-back-edge" d="m96 86 84 48v10l-84-48ZM264 86l-84 48v10l84-48Z"/><path class="object-plate base" d="M65 174 180 116l115 58-115 61Z"/><path class="object-side" d="M65 174v39l115 58v-36Z"/><path class="object-side right" d="m295 174v39l-115 58v-36Z"/><path class="object-bevel" d="m65 174 115 61 115-61v10l-115 62-115-62Z"/><path class="object-aperture-well" d="m121 160 59-30 59 30-59 30Z"/><path class="object-aperture" d="m133 160 47-24 47 24-47 24Z"/><path class="object-rim" d="m121 160 59-30 59 30-59 30Z"/><path class="object-facet" d="m180 73 45 86-45 72-45-72Z" filter="url(#surface-shadow)"/><path class="object-facet bright" d="m180 73 20 89-20 69-20-69Z"/><path class="object-line" d="M112 166h136M100 188l80 40 80-40"/><circle class="object-lock" cx="180" cy="161" r="9"/><circle class="object-lock-core" cx="180" cy="161" r="3"/></svg><i class="symbol symbol-candidate">◇</i><i class="symbol symbol-risk">◌</i><i class="symbol symbol-decision">□</i><i class="symbol symbol-substitution">◆</i></div>';
  host.innerHTML = '<div class="intelligence-core decision-core ' + decisionClass(result) + ' ' + mode + '" data-mode="' + mode + '"><div class="core-spine"></div>' + art + '<div class="core-orbit"><span></span><b>MIRROR</b></div><div class="decision-stages">' + stages.map(stage => '<div class="decision-stage ' + stage[2] + '"><i></i><div><b>' + stage[0] + '</b><span>' + stage[1] + '</span></div></div>').join('') + '</div><div class="core-result">' + result.decision + '</div></div>';
}
