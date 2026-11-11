import { apiUrl } from './api-config.js';

const buyer = document.querySelector('#buyer-intent');
if (buyer) {
  const overview = document.createElement('section');
  overview.id = 'overview';
  overview.className = 'command-center section';
  overview.innerHTML = `
    <div class="command-heading"><div><p class="eyebrow">PURCHASE ASSURANCE / OVERVIEW</p><h2>Purchase Assurance<br><span>Command Centre</span></h2><p class="product-promise">Your receipt remembers what you paid. MIRROR remembers what you were promised.</p><p>One clear record for buyer intent, seller offers, evidence provenance and the decision.</p><p id="dashboard-connection" role="status" aria-live="polite">Backend status appears in the header.</p></div><div class="command-actions"><a class="button" href="#buyer-intent">Create Purchase Passport</a><a class="button button-secondary" href="#passports">View Passports</a></div></div>
    <div class="command-metrics" aria-live="polite"><article><span>Active Passports</span><strong id="dashboard-passport-count">—</strong><small>Persisted in MIRROR</small></article><article><span>Seller Offers</span><strong id="dashboard-offer-count">—</strong><small>Across loaded Passports</small></article><article><span>Conditions for review</span><strong id="dashboard-review-count">—</strong><small>Unconfirmed buyer conditions</small></article><article><span>PayPal orders</span><strong id="dashboard-paypal-count">—</strong><small>Order references recorded</small></article></div>
    <div class="command-grid"><section class="command-card"><div class="panel-heading"><div><p class="eyebrow">PASSPORT REGISTER</p><h3>Recent Passports</h3></div><a href="#passports">Open detail</a></div><div class="dashboard-table-wrap"><table class="dashboard-table"><thead><tr><th>Passport</th><th>Buyer intent</th><th>Status</th><th>Conditions</th><th>Created</th></tr></thead><tbody id="dashboard-passport-rows"></tbody></table></div><div id="dashboard-passport-empty" class="dashboard-empty" hidden>No Passports yet. Create one from Buyer Intent.</div></section>
    <section class="command-card"><div class="panel-heading"><div><p class="eyebrow">SELLER ACTIVITY</p><h3>Recent Offers</h3></div><a href="#seller-submit">Submit offer</a></div><div id="dashboard-offers" class="dashboard-list"><p class="dashboard-empty">Select a Passport to load its offers.</p></div></section>
    <section class="command-card"><div class="panel-heading"><div><p class="eyebrow">DECISION ENGINE</p><h3>Recent Evaluations</h3></div><a href="#decision">View explanation</a></div><div id="dashboard-decisions" class="dashboard-list"><p class="dashboard-empty">Evaluations from this browser session appear here. MIRROR does not persist decision results.</p></div></section>
    <section class="command-card"><div class="panel-heading"><div><p class="eyebrow">AUDIT TRAIL</p><h3>Recent Evidence Events</h3></div><a href="#activity">Open activity</a></div><div id="dashboard-activity" class="dashboard-list"><p class="dashboard-empty">Evidence events will appear after a Passport is selected.</p></div></section></div>`;
  buyer.before(overview);
  const $dash = selector => overview.querySelector(selector);
  const discovery = document.createElement('section');
  discovery.id = 'products';
  discovery.className = 'section product-discovery';
  discovery.innerHTML = `
    <p class="eyebrow">PRODUCT DISCOVERY / CHANNEL3</p><h2 class="title">Explore electronics.</h2>
    <p class="copy">Results are live Channel3 catalog data when configured. Product details and offers can change; MIRROR records the source and retrieval time. Unknown specifications remain unknown.</p>
    <form id="product-search-form" class="product-search-form"><label for="product-search-query">Search products</label><input id="product-search-query" name="query" minlength="2" maxlength="300" required placeholder="Laptop, camera, smartphone…"><button class="button" type="submit">Search catalog</button></form>
    <p id="product-search-status" role="status" aria-live="polite">Checking Channel3 configuration…</p><div id="product-results" class="product-results"></div>`;
  buyer.before(discovery);
  const workspace = document.createElement('section');
  workspace.id = 'passports';
  workspace.className = 'mvp-workspace section';
  workspace.innerHTML = `
    <p class="eyebrow">PURCHASE ASSURANCE</p>
    <h2 class="title">One promise, checked from both sides.</h2>
    <p class="copy">Review a Passport, capture a seller's offer, inspect evidence provenance, and see a current server evaluation. Seller-submitted content is never treated as verified.</p>
    <div class="mvp-stats" aria-live="polite"><article><span>Purchase Passports</span><strong id="mvp-passport-count">—</strong></article><article><span>Offers on selected Passport</span><strong id="mvp-offer-count">—</strong></article><article><span>Current evaluation</span><strong id="mvp-outcome">Not evaluated</strong></article><article><span>PayPal checkout state</span><strong id="mvp-paypal-state">Checking configuration…</strong></article></div>
    <div class="mvp-panel glass"><label for="mvp-passport-select">Purchase Passport</label><div class="mvp-toolbar"><select id="mvp-passport-select"><option value="">Loading Passports…</option></select><button id="mvp-refresh" class="button" type="button">Refresh</button><button id="mvp-demo" class="button" type="button">Start / replay labelled demo</button></div><p id="mvp-status" role="status" aria-live="polite"></p><p class="mvp-disclosure">Buyer and seller accounts are separate. Sellers can see a Passport only after buyer authorization and seller acceptance. Seller uploads remain unverified; catalogue verification does not prove seller identity, item authenticity, or fulfilment.</p></div>
    <div class="mvp-columns"><section id="buyer-requirements" class="mvp-panel glass"><h3>Buyer requirements</h3><div id="mvp-requirements">Select a Passport to inspect its conditions.</div></section><section id="seller-submit" class="mvp-panel glass"><h3>Submit seller offer</h3><form id="mvp-offer-form"><label>Product name<input name="product_name" required maxlength="200"></label><label>Seller name<input name="seller_name" required maxlength="200"></label><label>Product URL (optional)<input name="product_url" type="url" maxlength="2048"></label><div class="mvp-inline"><label>Displayed price<input name="displayed_price" required type="number" min="0.01" step="0.01"></label><label>Currency<input name="currency" required maxlength="3"></label></div><label>Delivery promise<input name="delivery_promise" maxlength="500"></label><label>Return terms<textarea name="return_terms" maxlength="2000"></textarea></label><div id="mvp-seller-conditions"></div><button class="button" type="submit">Save seller offer</button></form></section></div>
    <header id="passport-header" class="passport-detail-header"><div><p class="eyebrow">PURCHASE PASSPORT</p><h2 id="mvp-passport-title">Select a Passport</h2><p id="mvp-passport-intent">Buyer intent and seller offer details will appear here.</p></div><div class="passport-state-stack"><span id="mvp-passport-status" class="passport-state-chip">—</span><span id="mvp-passport-created">—</span></div></header>
    <div class="mvp-columns"><section id="seller-offers" class="mvp-panel glass"><h3>Seller offers</h3><div id="mvp-offers">No offers loaded.</div><div id="mvp-offer-summary" class="offer-detail-summary">Select an offer to see the seller's response against each requirement.</div></section><section id="evidence" class="mvp-panel glass"><h3>Evidence & provenance</h3><div id="mvp-evidence">No evidence loaded.</div></section></div>
    <section id="decision" class="mvp-panel glass"><div class="mvp-toolbar"><h3>Current server evaluation</h3><button id="mvp-evaluate" class="button" type="button" disabled>Evaluate selected offer</button></div><div id="mvp-decision" aria-live="polite">No current server evaluation has been run.</div></section>
    <section id="resolution" class="mvp-panel glass"><h3>Report a broken promise</h3><p class="copy">Create a record tied to a buyer condition and existing evidence. This does not authenticate your identity or guarantee a refund; PayPal's dispute process is separate.</p><form id="dispute-form"><label>Affected condition<select name="condition_id" required></select></label><label>Supporting Passport evidence<select name="evidence_ids" multiple size="3"></select></label><label>What happened?<textarea name="summary" required minlength="5" maxlength="3000"></textarea></label><button class="button" type="submit">Record issue</button></form><div id="dispute-history" aria-live="polite"></div></section>
    <section id="activity" class="mvp-panel glass"><h3>Passport activity & audit trail</h3><div id="mvp-activity">Select a Passport to load persisted evidence history.</div></section>
    <section class="mvp-panel glass" id="paypal-checkout"><h3>PayPal Checkout</h3><p id="mvp-paypal-note">Checkout stays blocked unless the server re-evaluates this Passport as APPROVE.</p><div id="mvp-paypal-buttons"></div></section>`;
  buyer.after(workspace);

  const $ = selector => workspace.querySelector(selector);
  const status = $('#mvp-status');
  let passports = [];
  let authUser = window.mirrorUser || null;
  let selectedPassport = null;
  let offers = [];
  let selectedOffer = null;
  let decision = null;
  let decisionPassportId = null;
  let decisionOfferId = null;
  let paypalConfig = null;
  let sessionDecisions = [];
  let searchQuery = '';

  const api = async (path, options = {}) => {
    const headers = new Headers(options.headers || {});
    const method = (options.method || 'GET').toUpperCase();
    if (!['GET', 'HEAD'].includes(method)) {
      const csrf = document.cookie.split('; ').find(item => item.startsWith('mirror_csrf='))?.split('=').slice(1).join('=') || '';
      headers.set('X-Mirror-CSRF', decodeURIComponent(csrf));
    }
    const response = await fetch(apiUrl(path), { ...options, headers, credentials: 'include' });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = typeof body?.detail === 'string' ? body.detail : body?.detail?.message;
      const outcome = body?.detail?.outcome ? `Current server decision: ${body.detail.outcome}.` : '';
      const reasons = Array.isArray(body?.detail?.reasons) ? body.detail.reasons.join(' ') : '';
      throw new Error([detail || `Request failed (${response.status}).`, outcome, reasons].filter(Boolean).join(' '));
    }
    return body;
  };
  const setStatus = message => { status.textContent = message; };
  const appendText = (parent, tag, text, className = '') => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = text;
    parent.append(node);
    return node;
  };
  const activeId = () => $('#mvp-passport-select').value;

  const productStatus = document.querySelector('#product-search-status');
  let productGridApi = null;
  const productResults = document.querySelector('#product-results');
  const productSearchForm = document.querySelector('#product-search-form');

  function productRows(products) {
    return products.flatMap(product => {
      const attributes = product.structured_attributes || {};
      const offers = (product.offers || []).length ? product.offers : [null];
      const offerRows = offers.map(offer => {
        const price = offer?.price?.value ?? offer?.price;
        const currency = offer?.price?.currency_code || offer?.currency;
        const singleAttribute = name => {
          const value = attributes[name];
          return Array.isArray(value) && value.length === 1 && typeof value[0] === 'string' ? value[0] : undefined;
        };
        const observations = {
          product_name: product.title, brand: product.brand, model: product.model,
          ram: singleAttribute('ram'), storage_capacity: singleAttribute('storage-capacity'),
          processor_family: singleAttribute('processor-family'), display_resolution: singleAttribute('display-resolution'),
          operating_system: singleAttribute('operating-system'), sku_id: product.product_id,
          item_condition: offer?.condition || attributes.condition?.[0],
          price: price === undefined || price === null ? undefined : String(price),
          currency,
          seller_name: offer?.domain || offer?.merchant,
        };
        const requirements = (selectedPassport?.conditions || []).filter(item => item.owner === 'buyer').map(condition => {
          const observed = observations[condition.condition_type];
          if (observed === undefined || observed === null || observed === '') return `${condition.condition_type}: unknown (catalog attribute unavailable)`;
          if (condition.condition_type === 'price' && currency !== (condition.unit || selectedPassport.currency)) return `${condition.condition_type}: unknown (currency differs or is unavailable)`;
          const comparison = declaredValueMatches(condition, String(observed));
          return `${condition.condition_type}: ${comparison === true ? 'catalog listing matches' : comparison === false ? 'catalog listing differs' : 'unknown'}`;
        });
        return {
        title: product.title || 'Unknown product', brand: product.brand || 'Unknown', model: product.model || 'Unknown',
        specifications: Object.keys(attributes).length ? JSON.stringify(attributes) : 'Unknown',
        seller: offer?.domain || offer?.merchant || 'Unknown seller',
        price: price ?? 'Unknown', currency: currency || 'Unknown',
        condition: offer?.condition || attributes.condition?.[0] || 'Unknown', url: offer?.url || product.product_url || '',
        product_id: product.product_id, source: `${product.source} · ${product.retrieved_at}`,
        buyer_comparison: requirements.length ? `Preview only; not verified: ${requirements.join(' · ')}` : 'Select a Passport to compare requirements',
      };
      });
      return offerRows;
    });
  }

  function useProductInBuyerIntent(title) {
    const intent = document.querySelector('#buyer-intent-text');
    const productText = `I am considering ${title}.`;
    intent.value = intent.value.trim() ? `${intent.value.trim()} ${productText}` : productText;
    intent.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector('#buyer-intent').scrollIntoView({ behavior: 'smooth', block: 'start' });
    intent.focus({ preventScroll: true });
  }

  async function verifyCatalogueProduct(productId) {
    if (!selectedPassport || !selectedOffer) {
      setStatus('Select a saved Passport and seller offer before verifying catalogue facts.');
      return;
    }
    if (!productId) { setStatus('Channel3 did not return a product identifier.'); return; }
    try {
      setStatus('Retrieving Channel3 product detail and checking scoped facts...');
      const result = await api(`/api/passports/${encodeURIComponent(selectedPassport.id)}/offers/${encodeURIComponent(selectedOffer.id)}/catalogue-verification`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ product_id: productId, refresh: true }),
      });
      const conditionResults = result.condition_results || [];
      const verifiedTypes = conditionResults.filter(item => item.status === 'verified').map(item => item.condition_type);
      const unsupportedTypes = conditionResults.filter(item => item.status !== 'verified')
        .map(item => `${item.condition_type}: ${(item.reason || item.status).replaceAll('_', ' ')}`);
      const verifiedSummary = verifiedTypes.length ? `independently verified ${verifiedTypes.join(', ')}` : 'no catalogue conditions independently verified';
      const unsupportedSummary = unsupportedTypes.length ? `unsupported or unresolved ${unsupportedTypes.join('; ')}` : 'no unsupported conditions';
      setStatus(`Channel3 catalogue check (${result.status}): ${verifiedSummary}; ${unsupportedSummary}. Catalogue data does not prove seller fulfilment or authenticity.`);
      await loadEvidence();
      await evaluateSelected();
    } catch (error) { setStatus(error.message); }
  }

  async function renderProductGrid(products) {
    productGridApi?.destroy?.(); productGridApi = null;
    productResults.replaceChildren();
    if (!products.length) { appendText(productResults, 'p', 'No products were returned for this search.', 'dashboard-empty'); return; }
    const rows = productRows(products);
    const table = document.createElement('div');
    table.className = 'product-grid';
    table.setAttribute('role', 'region'); table.setAttribute('aria-label', 'Channel3 product comparison');
    table.style.height = `${Math.max(260, Math.min(540, rows.length * 54 + 52))}px`;
    productResults.append(table);
    try {
      const { ModuleRegistry, AllCommunityModule, createGrid, themeQuartz } = await import('https://cdn.jsdelivr.net/npm/ag-grid-community@36.3.0/+esm');
      ModuleRegistry.registerModules([AllCommunityModule]);
      productGridApi = createGrid(table, {
        theme: themeQuartz,
        rowData: rows,
        defaultColDef: { sortable: true, filter: true, resizable: true, minWidth: 120 },
        columnDefs: [
          { field: 'title', headerName: 'Product', minWidth: 220 }, { field: 'brand' }, { field: 'model' },
          { field: 'specifications', minWidth: 220 }, { field: 'seller' }, { field: 'price' },
          { field: 'currency' }, { field: 'condition' }, { field: 'source', minWidth: 230 },
          { field: 'buyer_comparison', headerName: 'Buyer condition comparison (catalog only)', minWidth: 320 },
          { headerName: 'Actions', minWidth: 230, pinned: 'right', sortable: false, filter: false, cellRenderer: params => {
            const wrapper = document.createElement('div'); wrapper.className = 'product-row-actions';
            const button = document.createElement('button'); button.type = 'button'; button.className = 'product-use-button'; button.textContent = 'Use product in intent';
            button.addEventListener('click', () => useProductInBuyerIntent(params.data.title));
            const verify = document.createElement('button'); verify.type = 'button'; verify.className = 'product-use-button';
            verify.textContent = 'Verify selected offer';
            verify.disabled = !params.data.product_id;
            verify.addEventListener('click', () => verifyCatalogueProduct(params.data.product_id));
            wrapper.append(button, verify);
            return wrapper;
          } },
          { field: 'url', headerName: 'Source link', minWidth: 200, cellRenderer: params => {
            if (!params.value) return 'Unavailable';
            const anchor = document.createElement('a'); anchor.href = params.value; anchor.target = '_blank'; anchor.rel = 'noopener noreferrer'; anchor.textContent = 'Open listing'; return anchor;
          } },
        ],
      });
    } catch {
      table.classList.add('product-grid-fallback');
      const fallback = document.createElement('table');
      fallback.innerHTML = '<thead><tr><th>Product</th><th>Brand / model</th><th>Seller offer</th><th>Price</th><th>Condition</th><th>Buyer comparison</th><th>Source</th><th>Actions</th></tr></thead>';
      const body = document.createElement('tbody');
      for (const row of rows) {
        const tr = document.createElement('tr');
        for (const value of [row.title, `${row.brand} / ${row.model}`, row.seller, `${row.price} ${row.currency}`, row.condition, row.buyer_comparison, row.source]) {
          const cell = document.createElement('td'); cell.textContent = String(value); tr.append(cell);
        }
        const intentCell = document.createElement('td'); const intentButton = document.createElement('button');
        intentButton.type = 'button'; intentButton.textContent = 'Use in intent'; intentButton.className = 'product-use-button';
        intentButton.addEventListener('click', () => useProductInBuyerIntent(row.title)); intentCell.append(intentButton);
        const verifyButton = document.createElement('button'); verifyButton.type = 'button'; verifyButton.textContent = 'Verify selected offer';
        verifyButton.className = 'product-use-button'; verifyButton.disabled = !row.product_id;
        verifyButton.addEventListener('click', () => verifyCatalogueProduct(row.product_id));
        intentCell.append(verifyButton); tr.append(intentCell);
        body.append(tr);
      }
      fallback.append(body); table.replaceChildren(fallback);
    }
  }

  fetch(apiUrl('/api/products/config')).then(response => response.json()).then(config => {
    productStatus.textContent = config.configured
      ? 'Channel3 connected. Search returns live catalog data and current offers.'
      : 'Channel3 is not configured. Add CHANNEL3_API_KEY on the backend to enable product discovery.';
  }).catch(() => { productStatus.textContent = 'Product discovery configuration is unavailable.'; });

  productSearchForm.addEventListener('submit', async event => {
    event.preventDefault();
    const query = productSearchForm.elements.query.value.trim();
    if (query.length < 2) { productStatus.textContent = 'Enter at least two characters.'; return; }
    productStatus.textContent = 'Searching the Channel3 catalog…';
    try {
      const response = await fetch(apiUrl('/api/products/search'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query, limit: 10 }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : result.detail?.message || `Search failed (${response.status}).`);
      if (!result || result.source !== 'Channel3' || !Array.isArray(result.products)) throw new Error('Product service returned an invalid response.');
      productStatus.textContent = `${result.products.length} live catalog products · retrieved ${result.retrieved_at}. Missing attributes are unknown.`;
      await renderProductGrid(result.products);
    } catch (error) { productStatus.textContent = error.message || 'Channel3 search failed.'; productResults.replaceChildren(); }
  });

  function renderRequirements(passport) {
    const root = $('#mvp-requirements');
    root.replaceChildren();
    appendText(root, 'p', `Original buyer intent: ${passport.buyer_intent}`, 'passport-intent-copy');
    appendText(root, 'p', `Passport currency: ${passport.currency}`, 'passport-currency');
    for (const condition of passport.conditions || []) {
      const confirmation = condition.owner === 'buyer'
        ? condition.buyer_confirmed ? 'Buyer confirmed' : 'Buyer confirmation missing'
        : condition.merchant_confirmed ? 'Seller confirmed' : 'Seller confirmation missing';
      appendText(root, 'article', `${condition.condition_type.replaceAll('_', ' ')} · ${condition.operator.toUpperCase()} ${condition.expected_value}${condition.unit ? ` ${condition.unit}` : ''} · ${condition.hard_or_soft.toUpperCase()} · ${confirmation}`, `passport-condition-row ${condition.owner === 'buyer' ? 'buyer-row' : 'merchant-row'}`);
    }
  }

  function renderSellerInputs(passport) {
    const root = $('#mvp-seller-conditions');
    root.replaceChildren();
    const buyerConditions = (passport.conditions || []).filter(item => item.owner === 'buyer');
    if (!buyerConditions.length) appendText(root, 'p', 'This Passport has no buyer conditions.');
    for (const condition of buyerConditions) {
      const box = document.createElement('fieldset');
      box.className = 'mvp-condition-input';
      box.dataset.conditionId = condition.id;
      box.dataset.conditionType = condition.condition_type;
      appendText(box, 'legend', `${condition.condition_type}: ${condition.operator} ${condition.expected_value}${condition.unit ? ` ${condition.unit}` : ''}`);
      const confirms = document.createElement('input');
      confirms.type = 'checkbox'; confirms.name = 'seller_confirms';
      const confirmLabel = document.createElement('label');
      confirmLabel.append(confirms, document.createTextNode(' Seller confirms this condition'));
      box.append(confirmLabel);
      const valueLabel = document.createElement('label');
      valueLabel.textContent = 'Seller-stated value';
      const value = document.createElement('input');
      value.name = 'seller_value'; value.required = true; value.maxLength = 1000;
      const capacityCondition = ['ram', 'storage_capacity'].includes(condition.condition_type);
      value.value = `${condition.expected_value}${capacityCondition && condition.unit ? ` ${condition.unit}` : ''}`;
      if (capacityCondition) value.placeholder = `Value and unit, e.g. 16 ${condition.unit || 'GB'}`;
      valueLabel.append(value); box.append(valueLabel);
      const evidenceLabel = document.createElement('label');
      evidenceLabel.textContent = 'Evidence text (preserved as unverified)';
      const evidence = document.createElement('textarea');
      evidence.name = 'evidence_content'; evidence.required = true; evidence.maxLength = 65536;
      evidenceLabel.append(evidence); box.append(evidenceLabel);
      root.append(box);
    }
  }

  function renderOffers(items) {
    const root = $('#mvp-offers'); root.replaceChildren();
    if (!items.length) { appendText(root, 'p', 'No seller offers yet.'); return; }
    for (const offer of items) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'mvp-offer-select';
      button.textContent = `${offer.seller_name} · ${offer.product_name} · ${offer.displayed_price} ${offer.currency} · ${offer.conditions.length} condition responses`;
      button.setAttribute('aria-pressed', String(offer.id === selectedOffer?.id));
      button.addEventListener('click', () => {
        if (selectedOffer?.id !== offer.id) {
          decision = null;
          decisionPassportId = null;
          decisionOfferId = null;
          $('#mvp-outcome').textContent = 'Not evaluated';
          $('#mvp-decision').textContent = 'Evaluate this offer to calculate its current server decision.';
        }
        selectedOffer = offer;
        renderOffers(offers);
        renderOfferSummary(offer);
        $('#mvp-evaluate').disabled = false;
        loadEvidence();
        renderPaypalButton();
      });
      root.append(button);
    }
  }

  function renderOfferSummary(offer) {
    const root = $('#mvp-offer-summary'); root.replaceChildren();
    appendText(root, 'h4', `${offer.product_name} · ${offer.displayed_price} ${offer.currency}`);
    appendText(root, 'p', `Seller: ${offer.seller_name}${offer.delivery_promise ? ` · Delivery: ${offer.delivery_promise}` : ''}`);
    if (offer.return_terms) appendText(root, 'p', `Seller-stated return terms: ${offer.return_terms}`);
    for (const condition of offer.conditions || []) {
      const evidenceValue = condition.evidence?.[0]?.captured_value;
      const match = declaredValueMatches(condition, evidenceValue);
      const discrepancy = match === false ? ' · seller-declared mismatch (unverified)' : '';
      appendText(root, 'article', `${condition.condition_type.replaceAll('_', ' ')} · seller ${condition.merchant_confirmed ? 'confirms' : 'does not confirm'} · stated value ${evidenceValue || 'not supplied'} · expected ${condition.operator} ${condition.expected_value}${condition.unit ? ` ${condition.unit}` : ''}${discrepancy}`, `passport-condition-row ${condition.merchant_confirmed ? 'merchant-confirmed' : 'merchant-unconfirmed'}${match === false ? ' declared-mismatch' : ''}`);
    }
  }

  function declaredValueMatches(condition, observed) {
    if (typeof observed !== 'string' || !observed.trim()) return null;
    const numeric = ['price', 'quantity', 'delivery_days', 'ram', 'storage_capacity'].includes(condition.condition_type);
    let left = observed.trim(), right = String(condition.expected_value).trim();
    if (numeric) {
      if (['ram', 'storage_capacity'].includes(condition.condition_type)) {
        const capacity = left.match(/^\s*([0-9]+(?:\.[0-9]+)?)\s*(GB|GIB|TB|TIB)\s*$/i);
        if (!capacity || capacity[2].toLowerCase() !== String(condition.unit || '').toLowerCase()) return null;
        left = capacity[1];
      }
      left = Number(left); right = Number(right);
      if (!Number.isFinite(left) || !Number.isFinite(right)) return null;
    } else {
      left = left.toLocaleLowerCase(); right = right.toLocaleLowerCase();
    }
    switch (condition.operator) {
      case 'eq': return left === right;
      case 'ne': return left !== right;
      case 'lt': return left < right;
      case 'lte': return left <= right;
      case 'gt': return left > right;
      case 'gte': return left >= right;
      default: return null;
    }
  }

  function renderDashboard(passportList) {
    $dash('#dashboard-passport-count').textContent = String(passportList.filter(item => !['fulfilled', 'cancelled'].includes(item.status)).length);
    $dash('#dashboard-paypal-count').textContent = String(passportList.filter(item => item.paypal_order_id).length);
    $dash('#dashboard-review-count').textContent = String(passportList.reduce((total, item) => total + (item.conditions || []).filter(condition => condition.owner === 'buyer' && !condition.buyer_confirmed).length, 0));
    const tbody = $dash('#dashboard-passport-rows'); tbody.replaceChildren();
    $dash('#dashboard-passport-empty').hidden = passportList.length > 0;
    const visiblePassports = passportList.filter(passport =>
      `${passport.id} ${passport.buyer_intent} ${passport.status}`.toLowerCase().includes(searchQuery));
    $dash('#dashboard-passport-empty').textContent = passportList.length
      ? 'No Passports match this search.'
      : 'No Passports yet. Create one from Buyer Intent.';
    $dash('#dashboard-passport-empty').hidden = visiblePassports.length > 0;
    for (const passport of visiblePassports.slice(0, 12)) {
      const row = document.createElement('tr');
      const open = document.createElement('button'); open.type = 'button'; open.className = 'table-passport-link';
      open.textContent = passport.id.slice(0, 12);
      open.addEventListener('click', () => {
        $('#mvp-passport-select').value = passport.id;
        selectPassport(passport.id).then(() => $('#passports').scrollIntoView({ behavior: 'smooth' })).catch(error => setStatus(error.message));
      });
      const idCell = document.createElement('td'); idCell.append(open); row.append(idCell);
      appendText(row, 'td', passport.buyer_intent, 'intent-cell');
      appendText(row, 'td', passport.status.toUpperCase());
      appendText(row, 'td', String(passport.conditions.length));
      appendText(row, 'td', new Date(passport.created_at).toLocaleDateString());
      tbody.append(row);
    }
    const decisions = $dash('#dashboard-decisions'); decisions.replaceChildren();
    if (!sessionDecisions.length) appendText(decisions, 'p', 'No evaluations in this browser session. Run an evaluation on a Passport to see its actual result here.', 'dashboard-empty');
    for (const item of sessionDecisions.slice(0, 4)) appendText(decisions, 'article', `${item.outcome} · ${item.offerName} · ${new Date(item.at).toLocaleTimeString()}`, `dashboard-event decision-${item.outcome.toLowerCase()}`);
  }

  function renderDashboardOffers(items) {
    const root = $dash('#dashboard-offers'); root.replaceChildren();
    if (!items.length) { appendText(root, 'p', 'No seller offers are saved for the selected Passport.', 'dashboard-empty'); return; }
    for (const offer of items.slice(0, 4)) {
      const button = appendText(root, 'button', `${offer.seller_name} · ${offer.product_name} · ${offer.displayed_price} ${offer.currency}`, 'dashboard-offer-button');
      button.type = 'button';
      button.addEventListener('click', async () => {
        $('#mvp-passport-select').value = offer.passport_id;
        await selectPassport(offer.passport_id);
        selectedOffer = offers.find(item => item.id === offer.id) || offers[0] || null;
        if (selectedOffer) { renderOffers(offers); renderOfferSummary(selectedOffer); $('#mvp-evaluate').disabled = false; }
        $('#passports').scrollIntoView({ behavior: 'smooth' });
      });
    }
  }

  async function loadEvidence() {
    if (!selectedPassport) {
      $('#mvp-evidence').textContent = 'Select a Passport to inspect evidence.';
      $('#mvp-activity').textContent = 'Select a Passport to inspect audit history.';
      $dash('#dashboard-activity').innerHTML = '<p class="dashboard-empty">Select a Passport to load recent evidence events.</p>';
      return;
    }
    const root = $('#mvp-evidence'); root.replaceChildren();
    const items = await api(`/api/passports/${encodeURIComponent(selectedPassport.id)}/evidence`);
    const conditionSelect = $('#dispute-form').elements.condition_id;
    conditionSelect.replaceChildren();
    for (const condition of (selectedPassport.conditions || []).filter(item => item.owner === 'buyer')) {
      const option = document.createElement('option'); option.value = condition.id;
      option.textContent = `${condition.condition_type}: ${condition.operator} ${condition.expected_value}${condition.unit ? ` ${condition.unit}` : ''}`;
      conditionSelect.append(option);
    }
    const evidenceSelect = $('#dispute-form').elements.evidence_ids;
    evidenceSelect.replaceChildren();
    for (const evidence of items) {
      const option = document.createElement('option'); option.value = evidence.id;
      option.textContent = `${evidence.evidence_type} · ${evidence.lifecycle_state}/${evidence.verification_status}${evidence.is_simulated ? ' · SIMULATED' : ''}`;
      evidenceSelect.append(option);
    }
    if (authUser?.role === 'buyer') await loadDisputes();
    else $('#dispute-history').textContent = 'Only the buyer can review dispute records.';
    const activity = $('#mvp-activity'); activity.replaceChildren();
    const dashboardActivity = $dash('#dashboard-activity'); dashboardActivity.replaceChildren();
    if (!items.length) { appendText(root, 'p', 'No evidence has been submitted.'); appendText(activity, 'p', 'No persisted evidence events.'); appendText(dashboardActivity, 'p', 'No persisted evidence events.', 'dashboard-empty'); return; }
    for (const evidence of items) {
      const conditionNames = (evidence.associated_conditions || []).map(condition => `${condition.owner} ${condition.condition_type}`).join(', ') || 'No linked conditions';
      const categoryLabels = {
        independently_verified_catalogue_fact: 'INDEPENDENT CATALOGUE FACT',
        seller_declared_commitment: 'SELLER DECLARATION - NOT INDEPENDENTLY VERIFIED',
        unverified_evidence: 'UNVERIFIED EVIDENCE', unsupported_claim: 'UNSUPPORTED CATALOGUE CLAIM',
        stale_catalogue_fact: 'STALE CATALOGUE FACT - RETRIEVE AGAIN',
      };
      const claimsText = (evidence.claims || []).map(claim => `${claim.claim_type}=${claim.claim_value}${claim.unit ? ` ${claim.unit}` : ''}`).join(', ') || 'No supported claims';
      appendText(root, 'article', `${categoryLabels[evidence.assurance_category] || evidence.assurance_category} | ${evidence.evidence_type} | ${evidence.lifecycle_state}/${evidence.verification_status} | ${evidence.source_classification}${evidence.is_simulated ? ' | SIMULATED' : ''} | ${conditionNames} | claims: ${claimsText} | SHA-256 ${evidence.content_sha256 || 'not available'} | received ${evidence.received_at || 'unknown'}${evidence.source_reference ? ` | source ID: ${evidence.source_reference}` : ''}${evidence.claimed_source_name ? ` | claimed source: ${evidence.claimed_source_name}` : ''}`, `mvp-evidence-item evidence-${evidence.lifecycle_state}`);
      for (const event of evidence.verification_history || []) {
        const proves = (event.proves || []).map(item => typeof item === 'string' ? item : `${item.type}=${item.value}${item.unit ? ` ${item.unit}` : ''}`).join(', ');
        const limits = (event.does_not_prove || []).map(item => typeof item === 'string' ? item.replaceAll('_', ' ') : `${item.condition_type || 'claim'}: ${(item.reason || 'not established').replaceAll('_', ' ')}`).join(', ');
        const verifier = event.verifier_identity ? ` | verifier ${event.verifier_identity} v${event.verifier_version || 'unknown'}` : '';
        const line = `${event.recorded_at} | ${event.actor_type}${verifier} | ${event.method} | ${event.from_state || 'new'} -> ${event.to_state} | proves: ${proves || 'none'} | does not prove: ${limits || 'not recorded'} | ${event.reason || ''}`;
        appendText(activity, 'article', line, 'mvp-evidence-item');
        appendText(dashboardActivity, 'article', line, 'dashboard-event');
      }
    }
    if (!dashboardActivity.childElementCount) appendText(dashboardActivity, 'p', 'No verification events recorded.', 'dashboard-empty');
  }

  async function loadDisputes() {
    const root = $('#dispute-history'); root.replaceChildren();
    if (!selectedPassport) return;
    const items = await api(`/api/passports/${encodeURIComponent(selectedPassport.id)}/disputes`);
    if (!items.length) { appendText(root, 'p', 'No issues have been reported for this Passport.', 'dashboard-empty'); return; }
    for (const item of items) {
      appendText(root, 'article', `${item.status.toUpperCase()} · ${item.condition_type}: ${item.expected_value} · reported ${item.reported_at} · ${item.summary} · ${item.evidence.length} linked evidence item(s)`, 'mvp-condition mvp-unresolved');
    }
  }

  async function refreshPassports(preferredId = null) {
    authUser = window.mirrorUser || authUser;
    if (!authUser) {
      passports = [];
      renderDashboard(passports);
      return;
    }
    if (authUser.role === 'buyer') {
      passports = await api('/api/passports');
    } else {
      const grants = await api('/api/seller/grants');
      passports = await Promise.all(grants.filter(grant => grant.status === 'accepted')
        .map(grant => api(`/api/passports/${encodeURIComponent(grant.passport_id)}/seller-view`)));
    }
    $('#mvp-passport-count').textContent = String(passports.length);
    renderDashboard(passports);
    const select = $('#mvp-passport-select'); select.replaceChildren();
    const empty = document.createElement('option'); empty.value = ''; empty.textContent = passports.length ? 'Choose a Passport' : 'No Passports yet'; select.append(empty);
    for (const item of passports) {
      const option = document.createElement('option'); option.value = item.id;
      option.textContent = `${item.id.slice(0, 8)} · ${item.currency} · ${item.conditions.length} conditions`;
      select.append(option);
    }
    let storedId = null;
    try { storedId = localStorage.getItem('mirror_active_passport_id'); } catch { /* browser storage is optional */ }
    const nextId = preferredId || storedId;
    if (nextId && passports.some(item => item.id === nextId)) select.value = nextId;
    else if (passports.length) select.value = passports[0].id;
    await selectPassport(select.value);
  }

  async function selectPassport(id) {
    selectedPassport = null; selectedOffer = null; decision = null;
    decisionPassportId = null; decisionOfferId = null; offers = [];
    $('#mvp-outcome').textContent = 'Not evaluated';
    $('#mvp-offer-count').textContent = '0';
    $('#mvp-evaluate').disabled = true;
    $('#mvp-decision').textContent = 'No current server evaluation has been run.';
    renderPaypalButton();
    if (!id) {
      $('#mvp-passport-title').textContent = 'Select a Passport';
      $('#mvp-passport-intent').textContent = 'Buyer intent and seller offer details will appear here.';
      $('#mvp-passport-status').textContent = '—';
      $('#mvp-passport-created').textContent = '—';
      $('#mvp-offer-summary').textContent = 'Select an offer to see the seller response.';
      $dash('#dashboard-offer-count').textContent = '0';
      renderOffers([]);
      await loadEvidence();
      return;
    }
    selectedPassport = authUser?.role === 'seller'
      ? await api(`/api/passports/${encodeURIComponent(id)}/seller-view`)
      : await api(`/api/passports/${encodeURIComponent(id)}`);
    try { localStorage.setItem('mirror_active_passport_id', id); } catch { /* dashboard remains usable without browser storage */ }
    $('#mvp-passport-title').textContent = `Passport ${selectedPassport.id}`;
    $('#mvp-passport-intent').textContent = selectedPassport.buyer_intent || 'Buyer-shared requirements; private buyer intent is not shared with sellers.';
    $('#mvp-passport-status').textContent = String(selectedPassport.status || 'authorized').toUpperCase();
    $('#mvp-passport-created').textContent = selectedPassport.created_at
      ? `Created ${new Date(selectedPassport.created_at).toLocaleString()} · ${selectedPassport.currency}`
      : `Buyer-authorized Passport · ${selectedPassport.currency}`;
    const form = $('#mvp-offer-form'); form.elements.currency.value = selectedPassport.currency;
    renderRequirements(selectedPassport); renderSellerInputs(selectedPassport);
    offers = await api(`/api/passports/${encodeURIComponent(id)}/offers`);
    const otherOfferResults = authUser?.role === 'seller' ? [] : await Promise.allSettled(passports.filter(passport => passport.id !== id)
      .map(passport => api(`/api/passports/${encodeURIComponent(passport.id)}/offers`)));
    const aggregateOffers = [...offers, ...otherOfferResults.flatMap(result => result.status === 'fulfilled' ? result.value : [])];
    $dash('#dashboard-offer-count').textContent = String(aggregateOffers.length);
    renderDashboardOffers(aggregateOffers);
    $('#mvp-offer-count').textContent = String(offers.length);
    $('#mvp-evaluate').hidden = authUser?.role !== 'buyer';
    $('#mvp-offer-form').hidden = authUser?.role !== 'seller';
    $('#dispute-form').hidden = authUser?.role !== 'buyer';
    $('#mvp-paypal-state').textContent = paypalConfig?.configured
      ? (selectedPassport.paypal_status || 'not_started').toUpperCase()
      : 'Configuration required';
    renderOffers(offers);
    if (offers.length) { selectedOffer = offers[0]; renderOffers(offers); renderOfferSummary(selectedOffer); $('#mvp-evaluate').disabled = false; }
    else $('#mvp-offer-summary').textContent = 'No seller offer has been submitted for this Passport.';
    await loadEvidence(); await renderPaypalButton();
  }

  async function refreshOfferDashboard() {
    const groups = await Promise.allSettled(passports.map(passport =>
      api(`/api/passports/${encodeURIComponent(passport.id)}/offers`)));
    const allOffers = groups.flatMap(result => result.status === 'fulfilled' ? result.value : []);
    allOffers.sort((left, right) => Date.parse(right.captured_at) - Date.parse(left.captured_at));
    $dash('#dashboard-offer-count').textContent = String(allOffers.length);
    renderDashboardOffers(allOffers);
  }

  function renderDecision(result, passportId, offerId) {
    decision = result;
    decisionPassportId = passportId;
    decisionOfferId = offerId;
    const root = $('#mvp-decision'); root.replaceChildren();
    appendText(root, 'p', 'Computed by the server from the saved Passport, selected offer, confirmations, and evidence. Evaluation history is not stored.', 'mvp-disclosure');
    appendText(root, 'h3', result.outcome, `mvp-outcome mvp-${result.outcome.toLowerCase()}`);
    const priceLimit = selectedPassport?.conditions?.find(item => item.owner === 'buyer' && item.condition_type === 'price' && ['lt', 'lte'].includes(item.operator));
    if (selectedOffer && priceLimit && selectedOffer.currency === selectedPassport.currency
        && Number(selectedOffer.displayed_price) > Number(priceLimit.expected_value)) {
      appendText(root, 'article', `Offer discrepancy (unverified seller declaration): displayed offer price ${selectedOffer.displayed_price} ${selectedOffer.currency} is above the buyer condition ${priceLimit.operator} ${priceLimit.expected_value} ${priceLimit.unit || selectedPassport.currency}. This value is seller-submitted and is not independent verification.`, 'mvp-condition mvp-unresolved');
    }
    const reasonText = {
      buyer_confirmation_missing: 'Buyer has not confirmed this condition.',
      merchant_confirmation_missing: 'Seller has not confirmed this condition.',
      evidence_missing_or_unlinked: 'No verified, condition-linked claim is available.',
      evidence_not_verified: 'Evidence has not been independently verified.',
      evidence_stale: 'Catalogue evidence is older than 30 days and needs a fresh retrieval.',
      simulated_evidence: 'Evidence is simulated and cannot establish this condition.',
      evidence_scope_mismatch: 'Evidence claim does not match this condition type.',
      conflicting_verified_evidence: 'Verified sources conflict.',
      unsupported_condition_type: 'This condition type is not supported by the evaluator.',
      unsupported_operator: 'This comparison is not supported for the condition type.',
      verified_evidence_satisfies_condition: 'Verified evidence satisfies this condition.',
      verified_value_does_not_satisfy_condition: 'Verified evidence does not satisfy this condition.',
      party_conditions_missing: 'This party has no confirmed conditions to evaluate.',
    };
    for (const condition of [...result.passed_conditions, ...result.failed_conditions, ...result.unresolved_conditions]) {
      const label = condition.condition_type || `${condition.owner} conditions`;
      const explanations = condition.reasons.map(reason => reasonText[reason] || reason.replaceAll('_', ' ')).join(' ');
      appendText(root, 'article', `${condition.owner} · ${label} · ${condition.status.toUpperCase()}${condition.expected_value ? ` · expected ${condition.operator} ${condition.expected_value}${condition.unit ? ` ${condition.unit}` : ''}` : ''} · ${explanations}`, `mvp-condition mvp-${condition.status}`);
    }
    for (const reason of result.reasons || []) appendText(root, 'p', reason);
    $('#mvp-outcome').textContent = result.outcome;
    $('#mvp-paypal-note').textContent = result.outcome === 'APPROVE'
      ? 'The current server evaluation approves this selected offer. The order endpoint re-evaluates before order creation and capture.'
      : `Checkout blocked: current server decision is ${result.outcome}. ${(result.reasons || []).join(' ')}`;
    renderPaypalButton();
  }

  async function evaluateSelected() {
    if (!selectedPassport || !selectedOffer) return;
    const passportId = selectedPassport.id;
    const offerId = selectedOffer.id;
    decision = null;
    decisionPassportId = null;
    decisionOfferId = null;
    $('#mvp-outcome').textContent = 'Evaluating';
    $('#mvp-decision').textContent = 'Checking the saved Passport, selected offer, confirmations, and evidence...';
    renderPaypalButton();
    setStatus('Evaluating persisted Passport and evidence…');
    let result;
    try {
      result = await api(`/api/passports/${encodeURIComponent(passportId)}/evaluate?offer_id=${encodeURIComponent(offerId)}`, { method: 'POST' });
      if (selectedPassport?.id !== passportId || selectedOffer?.id !== offerId) return;
      if (result.passport_id !== passportId) throw new Error('Evaluation response did not match the selected Passport.');
    } catch (error) {
      if (selectedPassport?.id === passportId && selectedOffer?.id === offerId) {
        $('#mvp-outcome').textContent = 'Unavailable';
        $('#mvp-decision').textContent = `Current server evaluation unavailable: ${error.message}`;
        $('#mvp-paypal-note').textContent = 'Checkout blocked: MIRROR could not obtain a current server evaluation.';
        renderPaypalButton();
      }
      throw error;
    }
    renderDecision(result, passportId, offerId);
    sessionDecisions.unshift({ outcome: result.outcome, offerName: selectedOffer.product_name, at: new Date().toISOString() });
    renderDashboard(passports);
    setStatus(`Decision: ${result.outcome}.`);
  }

  async function ensurePayPalSdk() {
    if (!paypalConfig?.configured || !paypalConfig.client_id || !selectedOffer || decision?.outcome !== 'APPROVE'
        || !(paypalConfig.supported_currencies || []).includes(selectedOffer.currency)) return false;
    if (globalThis.paypal) return true;
    const script = document.createElement('script');
    script.src = `https://www.paypal.com/sdk/js?client-id=${encodeURIComponent(paypalConfig.client_id)}&currency=${encodeURIComponent(selectedOffer.currency)}&intent=capture`;
    script.async = true;
    document.head.append(script);
    await new Promise((resolve, reject) => { script.onload = resolve; script.onerror = reject; });
    return Boolean(globalThis.paypal);
  }

  async function renderPaypalButton() {
    const root = $('#mvp-paypal-buttons'); root.replaceChildren();
    if (authUser?.role !== 'buyer') { $('#mvp-paypal-note').textContent = 'Only the Passport owner can use checkout.'; return; }
    const status = selectedPassport?.paypal_status || 'not_started';
    $('#mvp-paypal-state').textContent = !paypalConfig
      ? 'Checking configuration...'
      : paypalConfig.configured ? status.toUpperCase() : 'Configuration required';
    if (status === 'captured') {
      $('#mvp-paypal-note').textContent = `PayPal confirmed completed capture ${selectedPassport.paypal_capture_id || '(reference unavailable)'} for ${selectedPassport.paypal_amount} ${selectedPassport.paypal_currency}.`;
      return;
    }
    if (status === 'pending') {
      $('#mvp-paypal-note').textContent = `PayPal capture ${selectedPassport.paypal_capture_id || ''} is pending. MIRROR is waiting for a verified PayPal webhook; this is not a completed payment.`;
      return;
    }
    if (status === 'declined') {
      $('#mvp-paypal-note').textContent = 'PayPal declined this capture. No payment success is recorded.';
      return;
    }
    if (status === 'cancelled') {
      $('#mvp-paypal-note').textContent = 'The PayPal order was cancelled. A fresh APPROVE evaluation is required before another order.';
    }
    const decisionMatchesSelection = decision?.outcome === 'APPROVE'
      && decisionPassportId === selectedPassport?.id
      && decisionOfferId === selectedOffer?.id;
    if (!selectedOffer || !decisionMatchesSelection) {
      const currentOutcome = decisionPassportId === selectedPassport?.id && decisionOfferId === selectedOffer?.id
        ? decision?.outcome : null;
      const reason = currentOutcome && decision?.reasons?.length ? ` ${(decision.reasons || []).join(' ')}` : '';
      const configurationNotice = paypalConfig && !paypalConfig.configured
        ? ` PayPal sandbox is also unavailable; configure ${(paypalConfig.missing || ['PAYPAL_CLIENT_ID', 'PAYPAL_CLIENT_SECRET']).join(', ')}.` : '';
      const cancelledNotice = status === 'cancelled' ? ' The previous PayPal order was cancelled.' : '';
      $('#mvp-paypal-note').textContent = currentOutcome
        ? `Checkout blocked: current server decision is ${currentOutcome}.${reason}${configurationNotice}${cancelledNotice}`
        : `Checkout blocked: run a current server evaluation for the selected offer.${configurationNotice}${cancelledNotice}`;
      return;
    }
    if (!paypalConfig?.configured) {
      $('#mvp-paypal-state').textContent = 'Configuration required';
      $('#mvp-paypal-note').textContent = `Decision is APPROVE, but sandbox checkout is unavailable. Configure: ${(paypalConfig?.missing || ['PAYPAL_CLIENT_ID', 'PAYPAL_CLIENT_SECRET']).join(', ')}.`;
      return;
    }
    if (!(paypalConfig.supported_currencies || []).includes(selectedOffer.currency)) {
      $('#mvp-paypal-note').textContent = `PayPal sandbox does not support ${selectedOffer.currency} in this integration. Supported currencies: ${(paypalConfig.supported_currencies || []).join(', ')}.`;
      return;
    }
    try {
      if (!await ensurePayPalSdk()) return;
      globalThis.paypal.Buttons({
        createOrder: async () => {
          try {
            const created = await api(`/api/passports/${encodeURIComponent(selectedPassport.id)}/paypal/order`, {
              method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ offer_id: selectedOffer.id }),
            });
            $('#mvp-paypal-state').textContent = 'Order created';
            $('#mvp-paypal-note').textContent = `PayPal order ${created.order_id} for ${created.amount} ${created.currency}; awaiting payer approval.`;
            return created.order_id;
          } catch (error) {
            $('#mvp-paypal-state').textContent = 'Order not created';
            $('#mvp-paypal-note').textContent = `PayPal order was not created: ${error.message}`;
            throw error;
          }
        },
        onApprove: async data => {
          try {
            const captured = await api(`/api/passports/${encodeURIComponent(selectedPassport.id)}/paypal/capture`, {
              method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ order_id: data.orderID }),
            });
            $('#mvp-paypal-note').textContent = captured.status === 'COMPLETED'
              ? `PayPal confirmed completed capture ${captured.capture_id}.`
              : `PayPal capture is ${captured.status}. This is not a completed payment.`;
          } catch (error) {
            $('#mvp-paypal-note').textContent = `PayPal did not confirm a completed capture: ${error.message}`;
          }
          await selectPassport(selectedPassport.id);
        },
        onCancel: async data => {
          if (data.orderID) await api(`/api/passports/${encodeURIComponent(selectedPassport.id)}/paypal/cancel`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ order_id: data.orderID }),
          });
          await selectPassport(selectedPassport.id);
          $('#mvp-paypal-note').textContent = 'PayPal checkout was cancelled. No payment success is recorded.';
        },
        onError: () => {
          if ($('#mvp-paypal-state').textContent !== 'Order not created') {
            $('#mvp-paypal-note').textContent = 'PayPal checkout failed. No payment success is assumed.';
          }
        },
      }).render(root);
    } catch {
      $('#mvp-paypal-note').textContent = 'Could not load the PayPal sandbox SDK. No payment was created.';
    }
  }

  async function startDemo() {
    if (authUser?.role !== 'buyer') throw new Error('Sign in as a buyer to start the demo.');
    const created = await api('/api/passports/confirm-intent', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ buyer_intent: '[DEMO] New laptop under 800 USD; seller actions use a separate account.', currency: 'USD', buyer_acknowledged: true,
        conditions: [{ condition_type: 'price', operator: 'lte', expected_value: '800', unit: 'USD', hard_or_soft: 'hard', supporting_quote: 'under 800 USD' }] }),
    });
    try { localStorage.setItem('mirror_active_passport_id', created.id); } catch { /* optional browser storage */ }
    await refreshPassports(created.id);
    setStatus('Demo Passport created. In a separate seller browser session, register or sign in, copy the seller account ID, enter it here, and grant Passport access. The seller must accept the grant before submitting an offer.');
  }
  $('#mvp-refresh').addEventListener('click', () => refreshPassports().catch(error => setStatus(error.message)));
  $('#mvp-passport-select').addEventListener('change', event => selectPassport(event.target.value).catch(error => setStatus(error.message)));
  $('#mvp-evaluate').addEventListener('click', () => evaluateSelected().catch(error => setStatus(error.message)));
  $('#mvp-demo').addEventListener('click', () => { setStatus('Creating a clearly labelled demo Passport…'); startDemo().catch(error => setStatus(error.message)); });
  $('#mvp-offer-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (!selectedPassport) { setStatus('Select a Passport first.'); return; }
    const form = event.currentTarget;
    const conditions = [...$('#mvp-seller-conditions').querySelectorAll('fieldset')].map(box => ({
      condition_id: box.dataset.conditionId,
      seller_confirms: box.querySelector('[name="seller_confirms"]').checked,
      seller_value: box.querySelector('[name="seller_value"]').value,
      evidence_content: box.querySelector('[name="evidence_content"]').value,
    }));
    const payload = {
      product_name: form.elements.product_name.value,
      seller_name: form.elements.seller_name.value,
      product_url: form.elements.product_url.value,
      displayed_price: Number(form.elements.displayed_price.value),
      currency: form.elements.currency.value.toUpperCase(),
      delivery_promise: form.elements.delivery_promise.value,
      return_terms: form.elements.return_terms.value,
    };
    payload.product_url ||= null; payload.delivery_promise ||= null; payload.return_terms ||= null;
    payload.conditions = conditions;
    try {
      setStatus('Saving seller declaration and raw evidence…');
      const created = await api(`/api/passports/${encodeURIComponent(selectedPassport.id)}/offers`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      offers = [created, ...offers]; selectedOffer = created; renderOffers(offers);
      await refreshOfferDashboard();
      $('#mvp-evaluate').disabled = authUser?.role !== 'buyer'; await loadEvidence();
      if (authUser?.role === 'buyer') await evaluateSelected();
      else setStatus('Seller offer saved. The buyer can now review and evaluate it.');
    } catch (error) { setStatus(error.message); }
  });

  $('#dispute-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (!selectedPassport) { setStatus('Select a Passport before reporting an issue.'); return; }
    const form = event.currentTarget;
    const evidenceIds = [...form.elements.evidence_ids.selectedOptions].map(option => option.value);
    try {
      const result = await api(`/api/passports/${encodeURIComponent(selectedPassport.id)}/disputes`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ condition_id: form.elements.condition_id.value, evidence_ids: evidenceIds, summary: form.elements.summary.value }),
      });
      form.reset();
      setStatus(`Issue ${result.id} recorded as ${result.status}. No refund or PayPal dispute has been filed.`);
      await loadDisputes();
    } catch (error) { setStatus(error.message); }
  });
  $('#mvp-offer-form').elements.displayed_price.addEventListener('input', event => {
    const priceValue = event.currentTarget.value;
    $('#mvp-seller-conditions').querySelectorAll('fieldset[data-condition-type="price"] [name="seller_value"]')
      .forEach(input => { input.value = priceValue; });
  });
  window.addEventListener('mirror:passport-selected', event => refreshPassports(event.detail?.passportId).catch(error => setStatus(error.message)));
  window.addEventListener('mirror:auth-change', event => {
    authUser = event.detail?.user || null;
    if (authUser) refreshPassports().catch(error => setStatus(error.message));
    else { passports = []; selectPassport('').catch(() => {}); setStatus('Sign in to continue.'); }
  });
  window.addEventListener('mirror:passport-search', event => {
    searchQuery = String(event.detail?.query || '').trim().toLowerCase();
    renderDashboard(passports);
  });
  window.addEventListener('mirror:backend-status', event => {
    const badge = $dash('#dashboard-connection');
    badge.textContent = event.detail?.state === 'checking' ? 'Checking backend...' : event.detail?.connected ? 'System Online' : 'Backend Offline';
    badge.classList.toggle('connected-state', Boolean(event.detail?.connected));
  });

  api('/api/paypal/config').then(config => {
    paypalConfig = config;
    if (!config.configured) $('#mvp-paypal-state').textContent = 'Configuration required';
    else $('#mvp-paypal-state').textContent = `${config.mode} configured`;
    renderPaypalButton();
  }).catch(() => {
    paypalConfig = { configured: false, missing: ['backend configuration unavailable'] };
    $('#mvp-paypal-state').textContent = 'Unavailable';
    renderPaypalButton();
  });
  if (authUser) refreshPassports().catch(error => {
    $('#mvp-passport-count').textContent = 'Unavailable';
    setStatus(error.message);
  });
}
