import { test, expect } from '@playwright/test';

const backendURL = process.env.MIRROR_E2E_BACKEND_URL || 'http://127.0.0.1:8002';
const diagnosticsByTest = new Map();
const contextsByTest = new Map();

test.beforeEach(async ({ page }, testInfo) => {
  const diagnostics = [];
  diagnosticsByTest.set(testInfo.testId, diagnostics);
  page.on('console', message => {
    if (message.type() === 'error') diagnostics.push(`console: ${message.text()}`);
  });
  page.on('response', response => {
    if (response.status() >= 400) {
      const path = new URL(response.url()).pathname;
      diagnostics.push(`http: ${response.request().method()} ${path} ${response.status()}`);
    }
  });
  page.on('pageerror', error => diagnostics.push(`pageerror: ${error.stack || error.message}`));
  page.on('requestfailed', failed => diagnostics.push(`requestfailed: ${failed.url()} ${failed.failure()?.errorText || ''}`));
  await page.addInitScript(apiBase => { globalThis.MIRROR_API_BASE_URL = apiBase; }, backendURL);
});

test.afterEach(async ({}, testInfo) => {
  const diagnostics = diagnosticsByTest.get(testInfo.testId) || [];
  if (testInfo.status !== testInfo.expectedStatus && diagnostics.length) {
    await testInfo.attach('browser-console-and-network-errors.txt', {
      body: Buffer.from(diagnostics.join('\n')),
      contentType: 'text/plain',
    });
  }
  diagnosticsByTest.delete(testInfo.testId);
  await contextsByTest.get(testInfo.testId)?.close();
  contextsByTest.delete(testInfo.testId);
});

test('frontend assets resolve and separate buyer/seller handoff stays truthful', async ({ page, request, browser }, testInfo) => {
  test.setTimeout(90000);
  const diagnostics = diagnosticsByTest.get(testInfo.testId);

  const response = await page.goto('/');
  expect(response?.status()).toBe(200);
  await expect(page.locator('#buyer-intent-form')).toBeVisible();
  await expect(page.locator('#mvp-offer-form')).toBeVisible();

  const sellerEmail = `seller-${Date.now()}@example.test`;
  const sellerContext = await browser.newContext();
  contextsByTest.set(testInfo.testId, sellerContext);
  const sellerPage = await sellerContext.newPage();
  sellerPage.on('console', message => { if (message.type() === 'error') diagnostics.push(`seller console: ${message.text()}`); });
  sellerPage.on('response', response => {
    if (response.status() >= 400) {
      const path = new URL(response.url()).pathname;
      diagnostics.push(`seller http: ${response.request().method()} ${path} ${response.status()}`);
    }
  });
  sellerPage.on('pageerror', error => diagnostics.push(`seller pageerror: ${error.stack || error.message}`));
  sellerPage.on('requestfailed', failed => diagnostics.push(`seller requestfailed: ${failed.url()} ${failed.failure()?.errorText || ''}`));
  await sellerPage.addInitScript(apiBase => { globalThis.MIRROR_API_BASE_URL = apiBase; }, backendURL);
  await sellerPage.goto('/');
  await sellerPage.locator('#mirror-auth-form [name="email"]').fill(sellerEmail);
  await sellerPage.locator('#mirror-auth-form [name="password"]').fill('Browser-Seller-Password-2060!');
  await sellerPage.locator('#mirror-auth-form [name="role"]').selectOption('seller');
  await sellerPage.getByRole('button', { name: 'Create account' }).click();
  await expect(sellerPage.locator('#mirror-auth-session')).toBeVisible();
  const sellerIdentity = await sellerPage.evaluate(async () => {
    const response = await fetch(`${globalThis.MIRROR_API_BASE_URL}/api/auth/me`, { credentials: 'include' });
    return response.json();
  });
  expect(sellerIdentity.role).toBe('seller');
  expect(sellerIdentity.seller_id).toBeTruthy();
  await page.locator('#mirror-auth-form [name="email"]').fill(`buyer-${Date.now()}@example.test`);
  await page.locator('#mirror-auth-form [name="password"]').fill('Browser-Buyer-Password-2060!');
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page.locator('#mirror-auth-session')).toBeVisible();

  const assetUrls = await page.locator('link[rel="stylesheet"],script[src]').evaluateAll(nodes =>
    nodes.map(node => node.href || node.src).filter(url => url.startsWith(location.origin))
  );
  for (const url of assetUrls) {
    const asset = await request.get(url);
    expect(asset.status(), `Local asset failed: ${url}`).toBe(200);
  }

  const configResponse = await request.get(`${backendURL}/api/products/config`);
  expect(configResponse.status()).toBe(200);
  const channel3Configured = (await configResponse.json()).configured === true;

  if (!channel3Configured) {
    await page.locator('#product-search-query').fill('laptop');
    await page.getByRole('button', { name: 'Search catalog' }).click();
    await expect(page.locator('#product-search-status')).toContainText(/not configured|configuration|required|unavailable/i);
    test.skip(true, 'Channel3 credentials are not configured; live product selection and catalogue verification cannot be exercised.');
  }

  await page.locator('#product-search-query').fill('laptop');
  const searchResponsePromise = page.waitForResponse(res =>
    res.url().endsWith('/api/products/search') && res.request().method() === 'POST'
  );
  await page.getByRole('button', { name: 'Search catalog' }).click();
  const searchResponse = await searchResponsePromise;
  expect(searchResponse.status()).toBe(200);
  const search = await searchResponse.json();
  expect(search.source).toBe('Channel3');
  expect(search.products.length).toBeGreaterThan(0);
  const product = search.products.find(item => item.product_id && item.title);
  expect(product, 'Channel3 search returned no selectable product').toBeTruthy();
  expect(product.title.length).toBeLessThanOrEqual(200);
  const selectProduct = page.locator('.product-use-button').filter({ hasText: 'Use product in intent' }).first();
  await expect(selectProduct, 'Product intent action should be available in the result row').toBeVisible({ timeout: 10000 });
  await selectProduct.click();

  const buyerIntent = `I require ${product.title} and it must be in new condition.`;
  await page.locator('#buyer-intent-text').fill(buyerIntent);
  await page.route('**/api/passport-intents/extract', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      proposals: [
        { condition_type: 'product_name', operator: 'eq', expected_value: product.title,
          unit: null, hard_or_soft: 'hard', supporting_quote: product.title },
        { condition_type: 'item_condition', operator: 'eq', expected_value: 'new',
          unit: null, hard_or_soft: 'hard', supporting_quote: 'new condition' },
      ],
      clarification_questions: [], ready_for_review: true, extraction_mode: 'browser_test_fixture',
    }),
  }));
  await page.getByRole('button', { name: 'Extract conditions for review' }).click();
  await expect(page.locator('#buyer-intent-review')).toBeVisible();
  await page.locator('#buyer-intent-currency').fill('USD');
  await page.getByRole('checkbox', { name: 'I reviewed condition 1' }).check();
  await page.getByRole('checkbox', { name: 'I reviewed condition 2' }).check();
  await page.locator('#buyer-intent-ack').check();
  await expect(page.locator('#buyer-intent-confirm')).toBeEnabled();
  await page.locator('#buyer-intent-confirm').click();
  await expect(page.locator('#buyer-intent-result')).toContainText('Buyer-reviewed conditions saved');
  const passportText = await page.locator('#buyer-intent-result').innerText();
  const passportId = passportText.match(/Passport ID:\s*([\w-]+)/)?.[1];
  expect(passportId).toBeTruthy();
  await expect(page.locator('#mvp-passport-select')).toHaveValue(passportId);

  await page.locator('#mirror-seller-id').fill(sellerIdentity.seller_id);
  await page.locator('#mirror-create-grant').click();
  await expect(page.locator('#mirror-auth-error')).toContainText('Seller access granted');
  await sellerPage.reload();
  await expect(sellerPage.locator('#mirror-grant-list')).toContainText(passportId);
  await sellerPage.getByRole('button', { name: 'Accept access' }).click();
  await sellerPage.locator('#mvp-passport-select').selectOption(passportId);
  await expect(sellerPage.locator('#mvp-seller-conditions fieldset')).toHaveCount(2);

  const offerForm = sellerPage.locator('#mvp-offer-form');
  await offerForm.locator('[name="product_name"]').fill(product.title);
  await offerForm.locator('[name="seller_name"]').fill('QA fixture seller (not a real seller)');
  await offerForm.locator('[name="displayed_price"]').fill('100');
  await offerForm.locator('[name="currency"]').fill('USD');
  const sellerConditions = sellerPage.locator('#mvp-seller-conditions fieldset');
  await expect(sellerConditions).toHaveCount(2);
  for (const condition of await sellerConditions.all()) {
    await condition.locator('[name="seller_confirms"]').check();
    await condition.locator('[name="evidence_content"]').fill('SYNTHETIC BROWSER QA ONLY; not real seller evidence.');
  }
  await offerForm.getByRole('button', { name: 'Save seller offer' }).click();
  await expect(sellerPage.locator('#mvp-status')).toContainText('Seller offer saved');
  await page.locator('#mvp-refresh').click();
  await page.locator('#mvp-evaluate').click();
  await expect(page.locator('#mvp-decision')).toContainText('ESCALATE');

  let catalogueResult;
  const verifierResponsePromise = page.waitForResponse(res =>
    res.url().includes('/catalogue-verification') && res.request().method() === 'POST'
  );
  await page.getByRole('button', { name: 'Verify selected offer' }).first().click();
  const verifierResponse = await verifierResponsePromise;
  if (verifierResponse.status() !== 200) {
    const errorMessage = await page.locator('#mvp-status').innerText();
    expect(errorMessage).toMatch(/Channel3|catalogue|temporarily|failed|unavailable/i);
    throw new Error(`Live Channel3 verifier returned HTTP ${verifierResponse.status()}; UI reported: ${errorMessage}`);
  }
  catalogueResult = await verifierResponse.json();
  const conditionResults = catalogueResult.condition_results;
  if (catalogueResult.identity_matches_offer) {
    expect(conditionResults.find(item => item.condition_type === 'product_name')?.status).toBe('verified');
    expect(conditionResults.find(item => item.condition_type === 'item_condition')?.status).toBe('unsupported');
    await expect(page.locator('#mvp-evidence')).toContainText('INDEPENDENT CATALOGUE FACT');
  } else {
    // Search results and detail records can change independently. A mismatch
    // must stay unresolved and must never be turned into a catalogue claim.
    expect(catalogueResult.status).toBe('identity_mismatch');
    expect(conditionResults.every(item => item.status !== 'verified')).toBe(true);
    await expect(page.locator('#mvp-evidence')).toContainText('UNSUPPORTED CATALOGUE CLAIM');
  }
  console.log('Live Channel3 catalogue result', JSON.stringify({
    status: catalogueResult.status,
    identity_matches_offer: catalogueResult.identity_matches_offer,
    condition_results: conditionResults.map(item => ({ condition_type: item.condition_type, status: item.status })),
  }));

  await expect(page.locator('#mvp-evidence')).toContainText('SELLER DECLARATION - NOT INDEPENDENTLY VERIFIED');
  await expect(page.locator('#mvp-decision')).toContainText('ESCALATE');
  await expect(page.locator('#mvp-decision')).toContainText('item_condition');
  await expect(page.locator('#mvp-paypal-note')).toContainText(/blocked/i);

  const paymentCalls = [];
  page.on('request', req => {
    if (/\/paypal\/(order|capture)$/.test(new URL(req.url()).pathname)) paymentCalls.push(req.url());
  });
  await page.locator('#mvp-evaluate').click();
  await expect(page.locator('#mvp-decision')).toContainText('ESCALATE');
  await expect(page.locator('#mvp-paypal-note')).toContainText(/blocked/i);
  expect(paymentCalls).toEqual([]);
  expect(diagnostics, 'Browser console or network errors').toEqual([]);
});

test('buyer-facing errors are shown when backend endpoints fail', async ({ page }) => {
  await page.route('**/api/products/search', route => route.fulfill({
    status: 502, contentType: 'application/json', body: JSON.stringify({ detail: 'Channel3 product discovery is temporarily unavailable.' }),
  }));
  await page.goto('/');
  await page.locator('#mirror-auth-form [name="email"]').fill(`buyer-error-${Date.now()}@example.test`);
  await page.locator('#mirror-auth-form [name="password"]').fill('Browser-Buyer-Password-2060!');
  await page.locator('#mirror-auth-form [name="role"]').selectOption('buyer');
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page.locator('#mirror-auth-session')).toBeVisible();
  await page.locator('#product-search-query').fill('camera');
  await page.getByRole('button', { name: 'Search catalog' }).click();
  await expect(page.locator('#product-search-status')).toContainText('temporarily unavailable');

  await page.route('**/api/passports', route => route.fulfill({
    status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Test backend unavailable.' }),
  }));
  await page.locator('#mvp-refresh').click();
  await expect(page.locator('#mvp-status')).toContainText('Test backend unavailable');
});

test('checkout approval is scoped to the current Passport and offer', async ({ page }, testInfo) => {
  test.setTimeout(45000);
  const idA = '00000000-0000-4000-8000-0000000000a1';
  const idB = '00000000-0000-4000-8000-0000000000b1';
  const conditionA = { id: 'condition-a', passport_id: idA, owner: 'buyer', condition_type: 'product_name', operator: 'eq', expected_value: 'Fixture Alpha', unit: null, hard_or_soft: 'hard', buyer_confirmed: true, merchant_confirmed: false };
  const conditionB = { ...conditionA, id: 'condition-b', passport_id: idB, expected_value: 'Fixture Beta' };
  const passport = (id, intent, condition) => ({ id, status: 'active', buyer_intent: intent, currency: 'USD', created_at: '2026-11-10T00:00:00Z', updated_at: '2026-11-10T00:00:00Z', paypal_order_id: null, paypal_status: 'not_started', paypal_amount: null, paypal_currency: null, paypal_capture_id: null, conditions: [condition] });
  const offer = (id, passportId, name, condition) => ({ id, passport_id: passportId, product_name: name, seller_name: 'QA fixture seller', displayed_price: '100.00', currency: 'USD', captured_at: '2026-11-10T00:00:00Z', conditions: [{ ...condition, id: `seller-${id}`, owner: 'merchant', merchant_confirmed: true, evidence: [] }] });
  const offers = {
    [idA]: [offer('offer-a-approve', idA, 'Offer A', conditionA), offer('offer-a-escalate', idA, 'Offer A2', conditionA)],
    [idB]: [offer('offer-b-reject', idB, 'Offer B', conditionB)],
  };
  const records = { [idA]: passport(idA, 'Fixture Passport Alpha', conditionA), [idB]: passport(idB, 'Fixture Passport Beta', conditionB) };
  const evaluation = (passportId, outcome) => ({
    passport_id: passportId, outcome, passed_conditions: outcome === 'APPROVE' ? [{ condition_id: 'condition-a', owner: 'buyer', condition_type: 'product_name', operator: 'eq', expected_value: 'Fixture Alpha', observed_values: ['Fixture Alpha'], hard_or_soft: 'hard', status: 'passed', evidence_ids: ['fixture-only'], evidence_statuses: ['verified'], simulated_evidence_ids: [], confirmation_required: 'buyer', confirmation_received: true, reasons: ['verified_evidence_satisfies_condition'] }] : [],
    failed_conditions: outcome === 'REJECT' ? [{ condition_id: 'condition-b', owner: 'buyer', condition_type: 'product_name', operator: 'eq', expected_value: 'Fixture Beta', observed_values: ['Different fixture'], hard_or_soft: 'hard', status: 'failed', evidence_ids: ['fixture-only'], evidence_statuses: ['verified'], simulated_evidence_ids: [], confirmation_required: 'buyer', confirmation_received: true, reasons: ['verified_value_does_not_satisfy_condition'] }] : [],
    unresolved_conditions: outcome === 'ESCALATE' ? [{ condition_id: 'condition-a', owner: 'buyer', condition_type: 'product_name', operator: 'eq', expected_value: 'Fixture Alpha', observed_values: [], hard_or_soft: 'hard', status: 'unresolved', evidence_ids: [], evidence_statuses: [], simulated_evidence_ids: [], confirmation_required: 'buyer', confirmation_received: true, reasons: ['evidence_missing_or_unlinked'] }] : [],
    reasons: outcome === 'ESCALATE' ? ['Required information is unresolved.'] : outcome === 'REJECT' ? ['A hard condition failed.'] : [],
  });

  // These are explicitly UI-only fixtures. They do not write claims or evidence
  // to the database and the PayPal SDK stub never invokes createOrder/capture.
  await page.addInitScript(() => {
    globalThis.paypal = { Buttons: () => ({ render: root => { const button = document.createElement('button'); button.textContent = 'PayPal QA stub'; root.append(button); } }) };
  });
  await page.route('**/api/paypal/config', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ configured: true, client_id: 'QA_PUBLIC_CLIENT_ID', mode: 'sandbox', supported_currencies: ['USD'], missing: [], webhook_configured: false }) }));
  await page.route('**/api/passports**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === '/api/passports' && request.method() === 'GET') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([records[idA], records[idB]]) });
    const match = path.match(/^\/api\/passports\/([^/]+)(?:\/(.*))?$/);
    if (!match) return route.continue();
    const [, passportId, rest = ''] = match;
    if (rest === 'evaluate') {
      const offerId = url.searchParams.get('offer_id');
      const outcome = offerId === 'offer-a-approve' ? 'APPROVE' : offerId === 'offer-a-escalate' ? 'ESCALATE' : 'REJECT';
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(evaluation(passportId, outcome)) });
    }
    if (request.method() === 'GET' && !rest && records[passportId]) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(records[passportId]) });
    if (request.method() === 'GET' && rest === 'offers') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(offers[passportId] || []) });
    if (request.method() === 'GET' && (rest === 'evidence' || rest === 'disputes')) return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    return route.continue();
  });

  const paymentCalls = [];
  page.on('request', request => { if (/\/paypal\/(order|capture)$/.test(new URL(request.url()).pathname)) paymentCalls.push(request.url()); });
  await page.goto('/');
  await page.locator('#mirror-auth-form [name="email"]').fill(`decision-fixture-${Date.now()}@example.test`);
  await page.locator('#mirror-auth-form [name="password"]').fill('Browser-Buyer-Password-2060!');
  await page.locator('#mirror-auth-form [name="role"]').selectOption('buyer');
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page.locator('#mirror-auth-session')).toBeVisible();
  await expect(page.locator('#mvp-passport-select')).toHaveValue(idA);

  await page.locator('#mvp-offers').getByRole('button', { name: /Offer A ·/ }).first().click();
  await page.locator('#mvp-evaluate').click();
  await expect(page.locator('#mvp-decision')).toContainText('APPROVE');
  await expect(page.locator('#mvp-paypal-buttons')).toContainText('PayPal QA stub');

  await page.locator('#mvp-offers').getByRole('button', { name: /Offer A2 ·/ }).click();
  await expect(page.locator('#mvp-decision')).toContainText('Evaluate this offer');
  await expect(page.locator('#mvp-paypal-note')).toContainText('Checkout blocked');
  await expect(page.locator('#mvp-paypal-buttons')).toBeEmpty();
  await page.locator('#mvp-evaluate').click();
  await expect(page.locator('#mvp-decision')).toContainText('ESCALATE');
  await expect(page.locator('#mvp-paypal-note')).toContainText('Checkout blocked: current server decision is ESCALATE');
  await expect(page.locator('#mvp-paypal-buttons')).toBeEmpty();

  // Re-establish a fixture APPROVE, then switch Passport without evaluating
  // the next one. The old result must be cleared immediately across Passports.
  await page.locator('#mvp-offers').getByRole('button', { name: /Offer A ·/ }).first().click();
  await page.locator('#mvp-evaluate').click();
  await expect(page.locator('#mvp-decision')).toContainText('APPROVE');
  await expect(page.locator('#mvp-paypal-buttons')).toContainText('PayPal QA stub');
  await page.locator('#mvp-passport-select').selectOption(idB);
  await expect(page.locator('#mvp-decision')).toContainText('No current server evaluation');
  await expect(page.locator('#mvp-paypal-note')).toContainText('Checkout blocked');
  await expect(page.locator('#mvp-paypal-buttons')).toBeEmpty();
  await page.locator('#mvp-evaluate').click();
  await expect(page.locator('#mvp-decision')).toContainText('REJECT');
  await expect(page.locator('#mvp-paypal-note')).toContainText('Checkout blocked: current server decision is REJECT');
  await expect(page.locator('#mvp-paypal-buttons')).toBeEmpty();

  await page.locator('#mvp-passport-select').selectOption(idA);
  await expect(page.locator('#mvp-decision')).toContainText('No current server evaluation');
  await expect(page.locator('#mvp-paypal-note')).toContainText('Checkout blocked');
  await expect(page.locator('#mvp-paypal-buttons')).toBeEmpty();
  expect(paymentCalls, 'fixture SDK must not place/capture an order').toEqual([]);
  expect(diagnosticsByTest.get(testInfo.testId)).toEqual([]);
});
