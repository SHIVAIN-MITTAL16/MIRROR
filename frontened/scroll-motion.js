const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

if (!reduceMotion.matches) {
  const syncSections = () => {
    const sections = [...document.querySelectorAll('.shell > .section')];
    sections.forEach((section,index) => {
      section.dataset.scrollIndex = String(index);
      if (!section.classList.contains('is-active')) section.classList.add('is-after');
    });
    return sections;
  };

  let sections = syncSections();
  let active = 0;
  let raf = 0;

  const update = () => {
    raf = 0;
    sections = syncSections();
    const center = window.innerHeight * .5;
    let next = 0;
    sections.forEach((section,index) => {
      const r = section.getBoundingClientRect();
      if (r.top <= center && r.bottom >= center) next = index;
    });
    if (next === active && sections.length) return;
    active = next;
    sections.forEach((section,index) => {
      section.classList.toggle('is-before',index < active);
      section.classList.toggle('is-active',index === active);
      section.classList.toggle('is-after',index > active);
    });
  };

  const requestUpdate = () => { if (!raf) raf = requestAnimationFrame(update); };
  window.addEventListener('scroll',requestUpdate,{passive:true});
  window.addEventListener('resize',requestUpdate,{passive:true});
  new MutationObserver(() => { sections = syncSections(); requestUpdate(); }).observe(document.querySelector('.shell'),{childList:true});
  requestUpdate();
}