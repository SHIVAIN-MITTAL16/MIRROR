export function replayPipeline(host, record, onPhase, done) {
  let timer;
  let phase = 0;
  const labels = ['Buyer request', 'Baseline', 'Candidates', 'Constraint check', 'P05 risk gate', 'Survivors', 'Selected decision'];
  const render = () => {
    host.querySelectorAll('.pipeline-step').forEach((element, index) => {
      element.className = 'pipeline-step ' + (index < phase ? 'done' : index === phase ? 'active' : '');
    });
    onPhase?.(phase);
  };
  const advance = () => {
    phase += 1;
    render();
    if (phase < labels.length) timer = setTimeout(advance, phase === 3 ? 700 : 430);
    else done?.();
  };
  host.innerHTML = '<div class="pipeline-steps">' + labels.map(label => '<span class="pipeline-step">' + label + '</span>').join('') + '</div><button class="skip btn">Skip replay</button>';
  render();
  timer = setTimeout(advance, 300);
  host.querySelector('.skip').onclick = () => {
    clearTimeout(timer);
    phase = labels.length;
    render();
    done?.();
  };
  return () => clearTimeout(timer);
}
