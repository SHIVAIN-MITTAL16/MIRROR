const liveSku = document.querySelector('#live-sku');

function normalizeLiveSkuLabels() {
  if (!liveSku) return;
  liveSku.querySelectorAll('option').forEach(option => {
    const sku = option.value;
    if (sku && option.textContent.includes('undefined')) option.textContent = sku;
  });
}

if (liveSku) {
  new MutationObserver(normalizeLiveSkuLabels).observe(liveSku, { childList: true });
  normalizeLiveSkuLabels();
}

// Buyer-first policy for fresh live requests:
// when the exact requested SKU is already affordable AND fulfilment-feasible,
// substitution must not be used merely because it produces more merchant
// contribution. Recovery substitutions remain enabled when the baseline is
// actually constrained.
const nativeFetch = window.fetch.bind(window);
const priceTolerance = { Low: 0.02, Medium: 0.05, High: 0.10 };

window.fetch = async (input, init = {}) => {
  const url = typeof input === 'string' ? input : input?.url || '';
  if (!url.includes('/ai/live-decision') || (init.method || 'GET').toUpperCase() !== 'POST') {
    return nativeFetch(input, init);
  }

  try {
    const payload = JSON.parse(init.body || '{}');
    if (payload.substitution_tolerance === 1 && payload.sku_id && payload.requested_quantity > 0) {
      const skuResponse = await nativeFetch('/skus/' + encodeURIComponent(payload.sku_id));
      const availabilityResponse = await nativeFetch(
        '/availability/' + encodeURIComponent(payload.sku_id) + '?days=' + encodeURIComponent(payload.deadline_days),
      );
      if (skuResponse.ok && availabilityResponse.ok) {
        const sku = await skuResponse.json();
        const availability = await availabilityResponse.json();
        const tolerance = priceTolerance[payload.price_flexibility] ?? 0.05;
        const buyerCeiling = Number(payload.budget) * (1 + tolerance);
        const baselineTotal = Number(sku.current_price) * Number(payload.requested_quantity);
        const inventoryFeasible = Number(payload.requested_quantity) <= Number(availability.available);
        if (inventoryFeasible && baselineTotal <= buyerCeiling + 1e-9) {
          payload.substitution_tolerance = 0;
          init = { ...init, body: JSON.stringify(payload) };
        }
      }
    }
  } catch (_) {
    // Never block the decision if the policy pre-check cannot run.
  }

  return nativeFetch(input, init);
};
