(function () {
  const KM_TO_MILES = 0.6213711922;
  const M_TO_FEET = 3.280839895;
  const storageKey = 'adventure-units';
  const format = (value, digits) => new Intl.NumberFormat('en-US', {
    maximumFractionDigits: digits,
  }).format(value);

  let units = 'metric';
  try {
    if (localStorage.getItem(storageKey) === 'imperial') units = 'imperial';
  } catch (_) {
    // The toggle still works when browser storage is unavailable.
  }

  function render() {
    document.querySelectorAll('[data-distance-km]').forEach((element) => {
      const km = Number(element.dataset.distanceKm);
      const suffix = element.dataset.suffix || '';
      element.textContent = units === 'imperial'
        ? `${format(km * KM_TO_MILES, 2)} mi${suffix}`
        : `${format(km, 2)} km${suffix}`;
    });
    document.querySelectorAll('[data-elevation-m]').forEach((element) => {
      const meters = Number(element.dataset.elevationM);
      const prefix = element.dataset.prefix || '';
      const suffix = element.dataset.suffix || '';
      element.textContent = units === 'imperial'
        ? `${prefix}${format(meters * M_TO_FEET, 0)} ft${suffix}`
        : `${prefix}${format(meters, 0)} m${suffix}`;
    });
    document.querySelectorAll('[data-speed-kmh]').forEach((element) => {
      const kmh = Number(element.dataset.speedKmh);
      element.textContent = units === 'imperial'
        ? `${format(kmh * KM_TO_MILES, 1)} mph`
        : `${format(kmh, 1)} km/h`;
    });
    document.querySelectorAll('[data-unit-toggle] button').forEach((button) => {
      const active = button.dataset.unit === units;
      button.setAttribute('aria-pressed', String(active));
      button.classList.toggle('bg-[#e3d5bc]', active);
      button.classList.toggle('text-ink', active);
    });
  }

  document.querySelectorAll('[data-unit-toggle] button').forEach((button) => {
    button.addEventListener('click', () => {
      units = button.dataset.unit;
      try { localStorage.setItem(storageKey, units); } catch (_) { /* Storage is optional. */ }
      render();
      document.dispatchEvent(new CustomEvent('adventureunitschange', { detail: { units } }));
    });
  });

  window.adventureUnits = { get: () => units, kmToMiles: KM_TO_MILES, mToFeet: M_TO_FEET };
  render();
})();
