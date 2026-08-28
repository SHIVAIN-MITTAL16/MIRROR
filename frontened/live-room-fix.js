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
