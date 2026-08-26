const money = value => '₹' + new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(value ?? 0);
const pct = value => (value * 100).toFixed(2) + '%';

function metric(label, value) {
  return '<div class="ml-risk__metric"><span class="ml-risk__label">' + label + '</span><b>' + value + '</b></div>';
}

function row(label, value, className = '') {
  return '<div class="ml-risk__row"><span>' + label + '</span><b class="data ' + className + '">' + value + '</b></div>';
}

function caseCard(item) {
  if (item.id === 'risk-caught') {
    return '<article class="ml-risk__case"><span class="ml-risk__label">CASE 01 · RISK CAUGHT</span><h3>Existing decision: NEGOTIATE → experimental ML: REJECT</h3>' +
      row('Seed / request', item.seed + ' / ' + item.request_id) +
      row('Observed SLA miss', pct(item.actual_sla_miss), 'ml-risk__risk') +
      row('Predicted SLA-miss risk', pct(item.ml_risk), 'ml-risk__risk') +
      row('Expected net', money(item.expected_net)) +
      row('P05', money(item.p05)) +
      '<div class="ml-risk__actions"><button class="ml-risk__button" data-seed="' + item.seed + '" data-request="' + item.request_id + '">Replay request →</button></div></article>';
  }
  return '<article class="ml-risk__case"><span class="ml-risk__label">CASE 02 · SAFER ALTERNATIVE</span><h3>Substitution → PRICE after the ML safety check</h3>' +
    row('Seed / request', item.seed + ' / ' + item.request_id) +
    row('Old SLA miss', pct(item.old_actual_sla_miss), 'ml-risk__risk') +
    row('Old expected net', money(item.old_expected_net)) +
    row('New predicted risk', pct(item.new_ml_risk), 'ml-risk__safe') +
    row('New observed SLA miss', pct(item.new_actual_sla_miss), 'ml-risk__safe') +
    row('New P05', money(item.new_p05)) +
    '<div class="ml-risk__actions"><button class="ml-risk__button" data-seed="' + item.seed + '" data-request="' + item.request_id + '">Replay request →</button></div></article>';
}

async function mountMLRisk() {
  const response = await fetch('/ui/assets/ml-risk-evidence.json');
  if (!response.ok) throw new Error('ML risk evidence unavailable');
  const evidence = await response.json();
  const pipeline = document.querySelector('#pipeline');
  if (!pipeline || document.querySelector('#ml-risk')) return;

  const section = document.createElement('section');
  section.className = 'section ml-risk';
  section.id = 'ml-risk';
  section.innerHTML = '<div class="ml-risk__header"><div><p class="eyebrow"><b>03</b> Experimental ML Safety Gate</p><h2 class="title">A second look at SLA risk.</h2><p class="copy">The learned layer sits beside MIRROR’s deterministic P05 gate. It is evidence, not a replacement for the decision engine.</p></div><span class="ml-risk__badge">' + evidence.data_label + '</span></div>' +
    '<div class="ml-risk__grid">' +
      '<article class="ml-risk__card"><span class="ml-risk__label">MODEL</span><div class="ml-risk__value">' + evidence.model_version + '</div><p class="ml-risk__sub">Threshold <b class="data">' + evidence.threshold + '</b> · SKU-held-out synthetic evaluation · ' + evidence.held_out.test_rows.toLocaleString() + ' held-out rows.</p><div class="ml-risk__metrics">' +
        metric('Precision', pct(evidence.classification_at_threshold.precision)) +
        metric('Recall', pct(evidence.classification_at_threshold.recall)) +
        metric('F1', pct(evidence.classification_at_threshold.f1)) +
        metric('Brier', evidence.calibration.brier_score.toFixed(3)) +
        metric('ECE', pct(evidence.calibration.expected_calibration_error)) +
        metric('Risk separation', evidence.p05_approved_validation.fail_vs_pass_mean_risk_ratio.toFixed(2) + '×') +
      '</div></article>' +
      '<article class="ml-risk__card"><span class="ml-risk__label">END-TO-END IMPACT</span><div class="ml-risk__value">' + (evidence.end_to_end.decision_change_rate * 100).toFixed(1) + '%</div><p class="ml-risk__sub">Only ' + evidence.end_to_end.decision_changes + ' of 500 decisions changed in the experimental comparison.</p><div class="ml-risk__metrics">' +
        metric('Expected contribution', pct(evidence.end_to_end.expected_contribution_change_pct)) +
        metric('P05 change', pct(evidence.end_to_end.p05_change_pct)) +
        metric('Extra ML rejects', evidence.end_to_end.additional_ml_rejections) +
      '</div></article>' +
    '</div>' +
    '<div><span class="ml-risk__label">DEMO CASES · REAL PERSISTED REQUESTS + PERSISTED BENCHMARK RESULTS</span><div class="ml-risk__cases">' + evidence.demo_cases.map(caseCard).join('') + '</div></div>' +
    '<ul class="ml-risk__honesty">' + evidence.honesty.map(item => '<li>' + item + '</li>').join('') + '</ul>';

  pipeline.after(section);
  section.querySelectorAll('button[data-seed]').forEach(button => {
    button.addEventListener('click', () => {
      const seed = button.dataset.seed;
      const requestId = button.dataset.request;
      const seedSelect = document.querySelector('#seed');
      const requestInput = document.querySelector('#request-id');
      const load = document.querySelector('#load');
      if (!seedSelect || !requestInput || !load) return;
      seedSelect.value = seed;
      requestInput.value = requestId;
      load.click();
      document.querySelector('#request')?.scrollIntoView({ behavior: 'smooth' });
    });
  });
}

mountMLRisk().catch(error => console.error('[MIRROR] ML risk evidence:', error));
