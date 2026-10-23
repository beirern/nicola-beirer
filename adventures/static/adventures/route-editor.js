(() => {
  function initialize() {
    const kind = document.querySelector('[name=kind]');
    const section = document.querySelector('[data-route-legs]');
    if (!kind || !section || section.dataset.initialized) return;
    section.dataset.initialized = 'true';
    const rows = section.querySelector('[data-leg-rows]');
    const total = section.querySelector('[name=legs-TOTAL_FORMS]');
    function update() {
      const group = kind.value === 'group';
      section.hidden = !group;
      document.querySelectorAll('.route-recording-fields').forEach(panel => { panel.hidden = group; });
      document.querySelectorAll('[name=file], [name=activity_type]').forEach(field => { field.required = !group && (field.name !== 'file' || field.dataset.hasRecording !== 'true'); });
    }
    function numberRows() {
      [...rows.children].forEach((row, index) => {
        row.querySelector('[data-leg-number]').textContent = index + 1;
        row.querySelector('[name$=-ORDER]').value = index;
        row.querySelector('[data-leg-up]').disabled = index === 0;
        row.querySelector('[data-leg-down]').disabled = index === rows.children.length - 1;
      });
    }
    section.querySelector('[data-add-leg]').addEventListener('click', () => {
      const markup = section.querySelector('template').innerHTML.replaceAll('__prefix__', total.value);
      rows.insertAdjacentHTML('beforeend', markup);
      total.value = Number(total.value) + 1;
      numberRows();
      rows.lastElementChild.querySelector('select').focus();
    });
    rows.addEventListener('click', event => {
      const up = event.target.closest('[data-leg-up]');
      const down = event.target.closest('[data-leg-down]');
      const row = (up || down)?.closest('[data-leg-row]');
      if (up && row.previousElementSibling) rows.insertBefore(row, row.previousElementSibling);
      if (down && row.nextElementSibling) rows.insertBefore(row.nextElementSibling, row);
      numberRows();
    });
    kind.addEventListener('change', update);
    update();
    // Preserve a submitted order when redisplaying validation errors.
    [...rows.children].sort((a, b) => Number(a.querySelector('[name$=-ORDER]').value) - Number(b.querySelector('[name$=-ORDER]').value)).forEach(row => rows.append(row));
    numberRows();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
  else initialize();
  // Wagtail can hydrate snippet forms after navigation.
  new MutationObserver(initialize).observe(document.documentElement, {childList: true, subtree: true});
})();
