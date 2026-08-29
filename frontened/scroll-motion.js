const sections = [...document.querySelectorAll('.shell > .section')];

if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      entry.target.classList.toggle('is-visible', entry.isIntersecting);
    });
  }, {
    threshold: 0.14,
    rootMargin: '-8% 0px -8% 0px'
  });

  sections.forEach((section, index) => {
    section.dataset.sectionIndex = index + 1;
    observer.observe(section);
  });

  // Reveal the first screen immediately; the observer handles the rest.
  sections[0]?.classList.add('is-visible');
}
