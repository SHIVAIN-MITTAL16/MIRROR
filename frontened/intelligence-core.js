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
  host.innerHTML = '<div class="intelligence-core decision-core ' + decisionClass(result) + ' ' + mode + '" data-mode="' + mode + '"><div class="core-spine"></div><div class="core-orbit"><span></span><b>MIRROR</b></div><div class="decision-stages">' + stages.map(stage => '<div class="decision-stage ' + stage[2] + '"><i></i><div><b>' + stage[0] + '</b><span>' + stage[1] + '</span></div></div>').join('') + '</div><div class="core-result">' + result.decision + '</div></div>';
}
