const shell = document.querySelector('.shell');
if (shell) {
  const sidebar = document.createElement('aside');
  sidebar.className = 'mirror-sidebar';
  sidebar.innerHTML = [
    '<a class="mirror-wordmark" href="#overview" aria-label="MIRROR overview"><span class="mirror-mark">M</span><span>MIRROR<small>Predict. Stabilize. Prevent.</small></span></a>',
    '<button class="sidebar-toggle" type="button" aria-expanded="false" aria-controls="mirror-navigation">Menu <span aria-hidden="true">☰</span></button>',
    '<nav id="mirror-navigation" class="sidebar-navigation" aria-label="Main navigation">',
    '<p class="sidebar-label">WORKSPACE</p>',
    '<a href="#overview"><span aria-hidden="true">◫</span>Overview</a>',
    '<a href="#products"><span aria-hidden="true">⌕</span>Discover Products</a>',
    '<a href="#buyer-intent"><span aria-hidden="true">⌕</span>Buyer Intent</a>',
    '<a href="#passports"><span aria-hidden="true">▤</span>Purchase Passports</a>',
    '<a href="#seller-submit"><span aria-hidden="true">◇</span>Seller Offers</a>',
    '<a href="#live-room"><span aria-hidden="true">⌁</span>Live Decision</a>',
    '<a href="#resolution"><span aria-hidden="true">◷</span>Assurance / Resolution History</a>',
    '<a href="#activity"><span aria-hidden="true">⌁</span>Evidence Audit Trail</a>',
    '<p class="sidebar-label sidebar-label-secondary">EXPERIMENT</p>',
    '<a href="#merchant-lab"><span aria-hidden="true">⌘</span>Merchant Decision Lab</a></nav>',
    '<div class="sidebar-footer"><span class="prototype-dot"></span><span>CONTROLLED PROTOTYPE</span></div>'
  ].join('');

  const topbar = document.createElement('header');
  topbar.className = 'mirror-topbar';
  topbar.innerHTML = [
    '<button class="mobile-nav-toggle" id="mirror-menu-toggle" type="button" aria-label="Open navigation" aria-expanded="false">☰</button><div><p class="topbar-kicker">MIRROR / PURCHASE ASSURANCE</p><h1>Command Centre</h1><p>Buyer intent, seller offers and evidence in one place.</p></div>',
    '<div class="topbar-tools"><label class="passport-search"><span aria-hidden="true">⌕</span><input id="mirror-passport-search" type="search" placeholder="Search Passports" aria-label="Search Passports"></label><span id="mirror-api-status" class="api-status"><i></i>Checking backend</span></div>'
  ].join('');

  const hero = shell.querySelector('.hero');
  shell.before(sidebar);
  shell.prepend(topbar);
  if (hero) hero.id = 'legacy-hero';

  const requestSection = shell.querySelector('#request');
  const legacySections = [...shell.children].filter(child => child.matches('section.section'));
  const lastLegacy = legacySections[legacySections.length - 1];
  if (requestSection && lastLegacy) {
    const details = document.createElement('details');
    details.id = 'merchant-lab';
    details.className = 'merchant-lab-shell';
    details.innerHTML = '<summary><span><b>Merchant Decision Lab</b><small>Existing inventory, risk and benchmark experiments</small></span><span aria-hidden="true">＋</span></summary>';
    details.addEventListener('toggle', () => window.dispatchEvent(new Event('resize')));
    const parent = requestSection.parentElement;
    parent.insertBefore(details, requestSection);
    let current = requestSection;
    while (current) {
      const next = current.nextElementSibling;
      details.append(current);
      if (current === lastLegacy) break;
      current = next;
    }
  }

  const toggle = sidebar.querySelector('.sidebar-toggle');
  const menuToggle = topbar.querySelector('#mirror-menu-toggle');
  const setNavigationOpen = open => {
    sidebar.classList.toggle('navigation-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    menuToggle.setAttribute('aria-expanded', String(open));
    menuToggle.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
  };
  toggle.addEventListener('click', () => {
    setNavigationOpen(!sidebar.classList.contains('navigation-open'));
  });
  sidebar.querySelectorAll('a[href^="#"]').forEach(link => link.addEventListener('click', () => {
    if (link.getAttribute('href') === '#merchant-lab') document.querySelector('#merchant-lab').open = true;
    setNavigationOpen(false);
  }));
  menuToggle.addEventListener('click', () => {
    setNavigationOpen(!sidebar.classList.contains('navigation-open'));
  });
  const search = topbar.querySelector('#mirror-passport-search');
  search.addEventListener('input', () => window.dispatchEvent(new CustomEvent('mirror:passport-search', { detail: { query: search.value } })));
  window.addEventListener('mirror:backend-status', event => {
    const badge = topbar.querySelector('#mirror-api-status');
    badge.classList.toggle('is-connected', Boolean(event.detail?.connected));
    badge.classList.toggle('is-offline', !event.detail?.connected);
    badge.innerHTML = '<i></i>' + (event.detail?.connected ? 'Backend connected' : 'Backend unavailable');
  });

  const activate = () => {
    const links = [...sidebar.querySelectorAll('.sidebar-navigation a[href^="#"]')];
    let active = null, distance = Infinity;
    for (const link of links) {
      const target = document.querySelector(link.getAttribute('href'));
      if (!target) continue;
      const top = target.getBoundingClientRect().top;
      if (top <= 180 && Math.abs(top) < distance) { active = link; distance = Math.abs(top); }
    }
    links.forEach(link => link.classList.toggle('active', link === active));
  };
  window.addEventListener('scroll', activate, { passive: true });
  window.addEventListener('resize', activate, { passive: true });
  activate();
}
