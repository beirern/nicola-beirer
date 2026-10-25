async function initializeWaypointEditor() {
  const container = document.getElementById('waypoint-map');
  const routeInput = document.getElementById('id_route');
  const latitudeInput = document.getElementById('id_latitude');
  const longitudeInput = document.getElementById('id_longitude');
  const status = document.getElementById('waypoint-map-status');
  if (!container || !routeInput || !latitudeInput || !longitudeInput) return;

  const maplibregl = await import('https://unpkg.com/maplibre-gl@6.13.0/dist/maplibre-gl.mjs');
  const map = new maplibregl.Map({
    container, center: [0, 25], zoom: 1, scrollZoom: false,
    style: 'https://api.maptiler.com/maps/01a17198-5261-74f2-923d-4f19ac3cb5c2/style.json',
    transformRequest: url => {
      const requested = new URL(url, window.location.href);
      if (requested.hostname === 'api.maptiler.com') {
        requested.searchParams.set('key', container.dataset.maptilerKey);
      }
      return {url: requested.href};
    },
  });
  map.addControl(new maplibregl.NavigationControl(), 'top-right');
  let marker;
  let requestNumber = 0;

  function place(longitude, latitude) {
    if (!Number.isFinite(longitude) || !Number.isFinite(latitude) ||
        Math.abs(longitude) > 180 || Math.abs(latitude) > 90) return;
    if (!marker) {
      marker = new maplibregl.Marker({draggable: true}).setLngLat([longitude, latitude]).addTo(map);
      marker.getElement().setAttribute('aria-label', 'Waypoint marker. Use arrow keys to move it.');
      marker.getElement().addEventListener('keydown', event => {
        const movement = {
          ArrowUp: [0, 1], ArrowDown: [0, -1],
          ArrowLeft: [-1, 0], ArrowRight: [1, 0],
        }[event.key];
        if (!movement) return;
        event.preventDefault();
        const current = marker.getLngLat();
        const increment = event.shiftKey ? 0.001 : 0.0001;
        const nextLongitude = current.lng + movement[0] * increment;
        const nextLatitude = current.lat + movement[1] * increment;
        place(nextLongitude, nextLatitude);
        longitudeInput.value = nextLongitude.toFixed(6);
        latitudeInput.value = nextLatitude.toFixed(6);
      });
      marker.on('dragend', () => {
        const position = marker.getLngLat();
        latitudeInput.value = position.lat.toFixed(6);
        longitudeInput.value = position.lng.toFixed(6);
      });
    } else {
      marker.setLngLat([longitude, latitude]);
    }
  }

  function fromInputs() {
    if (latitudeInput.value === '' || longitudeInput.value === '') return;
    place(Number(longitudeInput.value), Number(latitudeInput.value));
  }
  latitudeInput.addEventListener('input', fromInputs);
  longitudeInput.addEventListener('input', fromInputs);
  fromInputs();

  map.on('click', event => {
    latitudeInput.value = event.lngLat.lat.toFixed(6);
    longitudeInput.value = event.lngLat.lng.toFixed(6);
    place(event.lngLat.lng, event.lngLat.lat);
  });

  async function loadRoute() {
    const currentRequest = ++requestNumber;
    const routeId = routeInput.value;
    if (map.getLayer('waypoint-route')) map.removeLayer('waypoint-route');
    if (map.getSource('waypoint-route')) map.removeSource('waypoint-route');
    if (!routeId) {
      status.textContent = 'Choose a route to see its geometry. Coordinates already entered are kept.';
      return;
    }
    status.textContent = 'Loading route geometry…';
    try {
      const response = await fetch(`/routes/${encodeURIComponent(routeId)}/geojson/?overview=1`, {credentials: 'same-origin'});
      if (!response.ok) throw new Error('Route geometry unavailable');
      const data = await response.json();
      if (currentRequest !== requestNumber) return;
      const coordinates = data.features.flatMap(feature => feature.geometry?.type === 'LineString' ? feature.geometry.coordinates : []);
      if (!coordinates.length) throw new Error('Route has no map geometry');
      await new Promise(resolve => map.isStyleLoaded() ? resolve() : map.once('load', resolve));
      if (currentRequest !== requestNumber) return;
      map.addSource('waypoint-route', {type: 'geojson', data});
      map.addLayer({id: 'waypoint-route', type: 'line', source: 'waypoint-route', paint: {'line-color': '#a8532e', 'line-width': 4}});
      const bounds = new maplibregl.LngLatBounds();
      coordinates.forEach(point => bounds.extend(point));
      if (marker) bounds.extend(marker.getLngLat());
      map.fitBounds(bounds, {padding: 35, maxZoom: 13, duration: 0});
      status.textContent = marker
        ? 'The placed point was kept. Click or drag to refine it, or edit the coordinates above.'
        : 'Click the map to place the stop, or enter coordinates above.';
    } catch (error) {
      if (currentRequest === requestNumber) status.textContent = 'This route has no available map geometry. You can still enter coordinates above.';
    }
  }

  routeInput.addEventListener('change', loadRoute);
  // Wagtail's snippet chooser updates a hidden input when its selection changes.
  new MutationObserver(() => { if (routeInput.value !== lastRoute) { lastRoute = routeInput.value; loadRoute(); } })
    .observe(routeInput, {attributes: true, attributeFilter: ['value']});
  let lastRoute = routeInput.value;
  loadRoute();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeWaypointEditor, {once: true});
} else {
  initializeWaypointEditor();
}
