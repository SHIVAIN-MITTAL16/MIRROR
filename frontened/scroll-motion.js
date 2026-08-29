const sections = [...document.querySelectorAll('.shell > .section')];
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

if (sections.length && !reduceMotion.matches) {
  let activeIndex = 0;
  let raf = 0;

  sections.forEach((section, index) => {
    section.dataset.scrollIndex = String(index);
    section.classList.add(index === 0 ? 'is-active' : 'is-after');
    section.style.zIndex = String(index + 1);
  });

  const update = () => {
    raf = 0;
    const viewportCenter = window.innerHeight * 0.5;

    // Pick the last section covering the visual centre. This works with
    // sticky sections as well as the taller data-heavy MIRROR sections.
    let nextIndex = 0;
    for (let i = 0; i < sections.length; i += 1) {
      const rect = sections[i].getBoundingClientRect();
      if (rect.top <= viewportCenter && rect.bottom >= viewportCenter) nextIndex = i;
    }

    if (nextIndex === activeIndex) return;
    activeIndex = nextIndex;

    sections.forEach((section, index) => {
      section.classList.toggle('is-before', index < activeIndex);
      section.classList.toggle('is-active', index === activeIndex);
      section.classList.toggle('is-after', index > activeIndex);
    });
  };

  const requestUpdate = () => {
    if (!raf) raf = requestAnimationFrame(update);
  };

  window.addEventListener('scroll', requestUpdate, {passive:true});
  window.addEventListener('resize', requestUpdate, {passive:true});
  requestUpdate();
}
