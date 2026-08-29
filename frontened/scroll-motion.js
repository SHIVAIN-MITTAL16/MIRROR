const sections = [...document.querySelectorAll('.shell > .section')];

if (sections.length && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
  let active = sections[0];

  const setActive = (section) => {
    if (!section || section === active) return;
    active?.classList.remove('is-active');
    section.classList.add('is-active');
    active = section;
  };

  sections[0].classList.add('is-active');

  const observer = new IntersectionObserver((entries) => {
    const visible = entries
      .filter(entry => entry.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio);

    if (visible[0]) setActive(visible[0].target);
  }, {
    threshold: [0.15, 0.3, 0.5, 0.7],
    rootMargin: '-18% 0px -18% 0px'
  });

  sections.forEach(section => observer.observe(section));
}
