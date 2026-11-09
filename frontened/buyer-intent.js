import { apiUrl } from './api-config.js';

const root = document.querySelector('#buyer-intent');

if (root) {
  const form = root.querySelector('#buyer-intent-form');
  const intentInput = root.querySelector('#buyer-intent-text');
  const currencyInput = root.querySelector('#buyer-intent-currency');
  const extractButton = root.querySelector('#buyer-intent-extract');
  const confirmButton = root.querySelector('#buyer-intent-confirm');
  const review = root.querySelector('#buyer-intent-review');
  const proposalsNode = root.querySelector('#buyer-intent-proposals');
  const questionsNode = root.querySelector('#buyer-intent-questions');
  const statusNode = root.querySelector('#buyer-intent-status');
  const ack = root.querySelector('#buyer-intent-ack');
  const resultNode = root.querySelector('#buyer-intent-result');

  const operators = {
    price: ['eq', 'ne', 'lt', 'lte', 'gt', 'gte'],
    quantity: ['eq', 'ne', 'lt', 'lte', 'gt', 'gte'],
    delivery_days: ['eq', 'ne', 'lt', 'lte', 'gt', 'gte'],
    product_name: ['eq', 'ne'], seller_name: ['eq', 'ne'], currency: ['eq', 'ne'],
    return_terms: ['eq', 'ne'], item_condition: ['eq', 'ne'], sku_id: ['eq', 'ne'],
  };
  const operatorLabels = {
    eq: 'is', ne: 'is not', lt: 'less than', lte: 'at most', gt: 'greater than', gte: 'at least',
  };
  const conditionTypes = Object.keys(operators);
  let proposals = [];
  let clarificationQuestions = [];
  let classificationClarificationTargets = new Map();
  let reviewed = [];
  let extractionReady = false;
  let confirmedPassport = null;

  function setStatus(message, kind = '') {
    statusNode.textContent = message;
    statusNode.dataset.kind = kind;
  }

  function apiError(data, fallback) {
    if (typeof data?.detail === 'string') return data.detail;
    if (Array.isArray(data?.detail)) {
      const messages = data.detail.map(item => item?.msg).filter(message => typeof message === 'string');
      if (messages.length) return messages.join(' ');
    }
    return fallback;
  }

  function validateExtraction(data, originalText) {
    if (!data || !Array.isArray(data.proposals) || !Array.isArray(data.clarification_questions)
      || typeof data.ready_for_review !== 'boolean') throw new Error('MIRROR returned an invalid extraction response.');
    for (const proposal of data.proposals) {
      if (!proposal || typeof proposal !== 'object'
        || !conditionTypes.includes(proposal.condition_type)
        || !operators[proposal.condition_type].includes(proposal.operator)
        || typeof proposal.expected_value !== 'string'
        || (proposal.unit !== null && typeof proposal.unit !== 'string')
        || !['hard', 'soft', null].includes(proposal.hard_or_soft)
        || typeof proposal.supporting_quote !== 'string'
        || !originalText.includes(proposal.supporting_quote)) {
        throw new Error('MIRROR returned a condition that could not be safely validated. Please try again.');
      }
    }
    if (!data.clarification_questions.every(question => typeof question === 'string')) {
      throw new Error('MIRROR returned invalid clarification details. Please try again.');
    }
  }

  function option(select, value, label) {
    const item = document.createElement('option');
    item.value = value;
    item.textContent = label;
    select.append(item);
  }

  function refreshConfirmationAvailability() {
    const allReviewed = reviewed.length > 0 && reviewed.every(Boolean);
    const hasOpenClarifications = getOpenClarifications().length > 0;
    const classificationClarificationsResolved = clarificationQuestions.length > 0
      && clarificationQuestions.every(question => {
        const proposalIndex = classificationClarificationTargets.get(question);
        return proposalIndex !== undefined
          && ['hard', 'soft'].includes(proposals[proposalIndex]?.hard_or_soft);
      });
    const extractionResolved = extractionReady || classificationClarificationsResolved;
    const complete = proposals.length > 0 && proposals.every(item =>
      item.condition_type && operators[item.condition_type]?.includes(item.operator)
      && item.expected_value.trim() && ['hard', 'soft'].includes(item.hard_or_soft)
      && item.supporting_quote && intentInput.value.includes(item.supporting_quote));
    const currency = currencyInput.value.trim().toUpperCase();
    const validCurrency = /^[A-Z]{3}$/.test(currency);
    const pricesMatchCurrency = proposals.every(item => item.condition_type !== 'price' || item.unit === currency);
    confirmButton.disabled = Boolean(confirmedPassport) || !extractionResolved || !allReviewed || !ack.checked
      || !complete || hasOpenClarifications || !validCurrency || !pricesMatchCurrency;
    root.querySelector('#buyer-intent-blocked-note').hidden = !hasOpenClarifications;
  }

  function getOpenClarifications() {
    return clarificationQuestions.filter(question => {
      const proposalIndex = classificationClarificationTargets.get(question);
      return proposalIndex === undefined
        || !['hard', 'soft'].includes(proposals[proposalIndex]?.hard_or_soft);
    });
  }

  function renderProposals() {
    proposalsNode.replaceChildren();
    proposals.forEach((proposal, index) => {
      const card = document.createElement('article');
      card.className = 'buyer-condition glass';

      const heading = document.createElement('h4');
      heading.textContent = `Condition ${index + 1}`;
      card.append(heading);

      const fields = document.createElement('div');
      fields.className = 'buyer-condition-fields';

      const typeLabel = document.createElement('label');
      typeLabel.textContent = 'Condition type';
      const typeSelect = document.createElement('select');
      typeSelect.setAttribute('aria-label', `Condition ${index + 1} type`);
      conditionTypes.forEach(type => option(typeSelect, type, type.replaceAll('_', ' ')));
      typeSelect.value = proposal.condition_type;
      typeLabel.append(typeSelect);

      const operatorLabel = document.createElement('label');
      operatorLabel.textContent = 'Comparison';
      const operatorSelect = document.createElement('select');
      operatorSelect.setAttribute('aria-label', `Condition ${index + 1} comparison`);
      const setOperators = selected => {
        operatorSelect.replaceChildren();
        operators[typeSelect.value].forEach(value => option(operatorSelect, value, operatorLabels[value]));
        operatorSelect.value = operators[typeSelect.value].includes(selected) ? selected : 'eq';
      };
      setOperators(proposal.operator);
      operatorLabel.append(operatorSelect);

      const valueLabel = document.createElement('label');
      valueLabel.textContent = 'Expected value';
      const valueInput = document.createElement('input');
      valueInput.type = 'text';
      valueInput.maxLength = 1000;
      valueInput.value = proposal.expected_value;
      valueInput.setAttribute('aria-label', `Condition ${index + 1} expected value`);
      valueLabel.append(valueInput);

      const unitLabel = document.createElement('label');
      unitLabel.textContent = 'Unit (if applicable)';
      const unitInput = document.createElement('input');
      unitInput.type = 'text';
      unitInput.maxLength = 40;
      unitInput.value = proposal.unit ?? '';
      unitInput.setAttribute('aria-label', `Condition ${index + 1} unit`);
      unitLabel.append(unitInput);

      let hardnessSelect = null;
      if (proposal.hard_or_soft === null) {
        const hardnessGroup = document.createElement('fieldset');
        hardnessGroup.className = 'buyer-condition-strength';
        const hardnessLegend = document.createElement('legend');
        hardnessLegend.textContent = 'Choose requirement strength';
        hardnessGroup.append(hardnessLegend);
        [
          ['hard', 'Hard requirement'],
          ['soft', 'Preference'],
        ].forEach(([value, labelText]) => {
          const label = document.createElement('label');
          const radio = document.createElement('input');
          radio.type = 'radio';
          radio.name = `condition-strength-${index}`;
          radio.value = value;
          radio.checked = proposal.hard_or_soft === value;
          radio.setAttribute('aria-label', `Condition ${index + 1}: ${labelText}`);
          radio.addEventListener('change', () => {
            if (!radio.checked) return;
            proposal.hard_or_soft = value;
            reviewed[index] = false;
            reviewedCheck.checked = false;
            ack.checked = false;
            renderClarifications();
            refreshConfirmationAvailability();
          });
          const text = document.createElement('span');
          text.textContent = labelText;
          label.append(radio, text);
          hardnessGroup.append(label);
        });
        fields.append(typeLabel, operatorLabel, valueLabel, unitLabel, hardnessGroup);
      } else {
        const hardnessLabel = document.createElement('label');
        hardnessLabel.textContent = 'Requirement strength';
        hardnessSelect = document.createElement('select');
        hardnessSelect.setAttribute('aria-label', `Condition ${index + 1} requirement strength`);
        option(hardnessSelect, '', 'Choose hard or preference');
        option(hardnessSelect, 'hard', 'Hard requirement');
        option(hardnessSelect, 'soft', 'Preference');
        hardnessSelect.value = proposal.hard_or_soft;
        hardnessLabel.append(hardnessSelect);
        fields.append(typeLabel, operatorLabel, valueLabel, unitLabel, hardnessLabel);
      }

      card.append(fields);

      const quote = document.createElement('blockquote');
      quote.className = 'buyer-condition-quote';
      quote.textContent = `“${proposal.supporting_quote}”`;
      const quoteCaption = document.createElement('span');
      quoteCaption.textContent = 'Exact supporting quote from your request';
      card.append(quote, quoteCaption);

      const reviewedLabel = document.createElement('label');
      reviewedLabel.className = 'buyer-reviewed-check';
      const reviewedCheck = document.createElement('input');
      reviewedCheck.type = 'checkbox';
      reviewedCheck.checked = reviewed[index];
      reviewedCheck.setAttribute('aria-label', `I reviewed condition ${index + 1}`);
      reviewedCheck.addEventListener('change', () => {
        reviewed[index] = reviewedCheck.checked;
        refreshConfirmationAvailability();
      });
      const checkText = document.createElement('span');
      checkText.textContent = 'I reviewed this condition and its source quote.';
      reviewedLabel.append(reviewedCheck, checkText);
      card.append(reviewedLabel);

      const edited = () => {
        proposal.condition_type = typeSelect.value;
        setOperators(proposal.operator);
        proposal.operator = operatorSelect.value;
        proposal.expected_value = valueInput.value;
        proposal.unit = unitInput.value.trim() || null;
        if (hardnessSelect) proposal.hard_or_soft = hardnessSelect.value || null;
        reviewed[index] = false;
        reviewedCheck.checked = false;
        refreshConfirmationAvailability();
      };
      typeSelect.addEventListener('change', edited);
      operatorSelect.addEventListener('change', () => {
        proposal.operator = operatorSelect.value;
        reviewed[index] = false;
        reviewedCheck.checked = false;
        refreshConfirmationAvailability();
      });
      valueInput.addEventListener('input', edited);
      unitInput.addEventListener('input', edited);
      hardnessSelect?.addEventListener('change', edited);
      proposalsNode.append(card);
    });
    refreshConfirmationAvailability();
  }

  function renderClarifications() {
    questionsNode.replaceChildren();
    const openClarifications = getOpenClarifications();
    openClarifications.forEach(question => {
      const item = document.createElement('li');
      item.textContent = question;
      questionsNode.append(item);
    });
    root.querySelector('#buyer-intent-clarifications').hidden = openClarifications.length === 0;
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const text = intentInput.value;
    if (!text.trim()) {
      setStatus('Enter your purchase requirements before extracting.', 'error');
      intentInput.focus();
      return;
    }
    extractButton.disabled = true;
    extractButton.textContent = 'Extracting…';
    setStatus('Sending your text to Gemini for condition extraction…', 'loading');
    resultNode.hidden = true;
    review.hidden = true;
    confirmedPassport = null;
    proposals = [];
    clarificationQuestions = [];
    classificationClarificationTargets = new Map();
    reviewed = [];
    extractionReady = false;
    ack.checked = false;
    refreshConfirmationAvailability();
    try {
      const response = await fetch(apiUrl('/api/passport-intents/extract'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(apiError(data, 'Intent extraction failed. Please try again.'));
      if (intentInput.value !== text) throw new Error('Your request changed during extraction. Submit it again to review current text.');
      validateExtraction(data, text);
      proposals = data.proposals.map(item => ({ ...item }));
      clarificationQuestions = [...data.clarification_questions];
      classificationClarificationTargets = new Map();
      clarificationQuestions.forEach(question => {
        if (!/strict requirement or a preference/i.test(question)) return;
        const proposalIndex = proposals.findIndex(item =>
          question.includes(item.supporting_quote) && item.hard_or_soft === null);
        if (proposalIndex >= 0) classificationClarificationTargets.set(question, proposalIndex);
      });
      extractionReady = data.ready_for_review;
      reviewed = proposals.map(() => false);
      review.hidden = false;
      ack.checked = false;
      renderProposals();
      renderClarifications();
      setStatus(data.extraction_mode === 'deterministic_fallback'
        ? 'Gemini is unavailable. Deterministic fallback inferred no conditions; checkout and confirmation remain blocked until proposals are reviewed.'
        : extractionReady
        ? 'Extraction is ready for your review. Nothing is confirmed yet.'
        : 'Review the supported proposals and resolve the clarification items below. Nothing is confirmed.', 'info');
      review.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
      review.hidden = true;
      setStatus(error instanceof Error ? error.message : 'Intent extraction failed. Please try again.', 'error');
    } finally {
      extractButton.disabled = false;
      extractButton.textContent = 'Extract conditions for review';
    }
  });

  ack.addEventListener('change', refreshConfirmationAvailability);
  intentInput.addEventListener('input', () => {
    if (review.hidden) return;
    review.hidden = true;
    resultNode.hidden = true;
    proposals = [];
    clarificationQuestions = [];
    classificationClarificationTargets = new Map();
    reviewed = [];
    extractionReady = false;
    ack.checked = false;
    refreshConfirmationAvailability();
    setStatus('Your request changed. Extract it again before reviewing or saving conditions.', 'info');
  });
  currencyInput.addEventListener('input', () => {
    currencyInput.value = currencyInput.value.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 3);
    refreshConfirmationAvailability();
  });

  confirmButton.addEventListener('click', async () => {
    if (confirmButton.disabled) return;
    const currency = currencyInput.value.trim().toUpperCase();
    const payload = {
      buyer_intent: intentInput.value,
      currency,
      buyer_acknowledged: true,
      conditions: proposals.map(item => ({
        condition_type: item.condition_type,
        operator: item.operator,
        expected_value: item.expected_value.trim(),
        unit: item.unit,
        hard_or_soft: item.hard_or_soft,
        supporting_quote: item.supporting_quote,
      })),
    };
    confirmButton.disabled = true;
    confirmButton.textContent = 'Saving reviewed conditions…';
    setStatus('Saving your explicit declaration…', 'loading');
    try {
      const response = await fetch(apiUrl('/api/passports/confirm-intent'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(apiError(data, 'Could not save the reviewed conditions. Please check the values.'));
      const saved = data && typeof data.id === 'string' && Array.isArray(data.conditions)
        && data.conditions.length === payload.conditions.length
        && data.conditions.every(item => item.owner === 'buyer' && item.buyer_confirmed === true
          && typeof item.buyer_confirmed_at === 'string');
      if (!saved) throw new Error('MIRROR returned an invalid Passport confirmation response.');
      confirmedPassport = data;
      try { localStorage.setItem('mirror_active_passport_id', data.id); } catch { /* Passport was saved successfully even if browser storage is disabled. */ }
      window.dispatchEvent(new CustomEvent('mirror:passport-selected', { detail: { passportId: data.id } }));
      resultNode.hidden = false;
      resultNode.className = 'buyer-intent-result buyer-intent-success';
      resultNode.replaceChildren();
      const title = document.createElement('h3');
      title.textContent = 'Buyer-reviewed conditions saved';
      const id = document.createElement('p');
      id.textContent = `Passport ID: ${data.id}`;
      const status = document.createElement('p');
      status.textContent = `${data.conditions.length} buyer conditions confirmed in the response from MIRROR.`;
      const identity = document.createElement('p');
      identity.className = 'buyer-intent-identity';
      identity.textContent = 'This records your declaration; MIRROR has not verified your identity.';
      resultNode.append(title, id, status, identity);
      setStatus('Passport saved successfully.', 'success');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Could not save the reviewed conditions.', 'error');
    } finally {
      confirmButton.textContent = 'Confirm reviewed conditions';
      refreshConfirmationAvailability();
    }
  });

  refreshConfirmationAvailability();
}
