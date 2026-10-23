import * as maplibregl from 'https://unpkg.com/maplibre-gl@6.13.0/dist/maplibre-gl.mjs';

const container = document.getElementById('routes-map');
const routes = JSON.parse(document.getElementById('map-routes').textContent);
const status = document.getElementById('routes-map-status');
const colors = Object.fromEntries(
  [...document.querySelectorAll('[data-route-color]')].map(button => [button.dataset.routeFilter, button.dataset.routeColor])
);
let map, popup, selected, activeFilter = 'all';
const loaded = new Map();
const buttons = [...document.querySelectorAll('[data-select-route]')];
const resetButton = document.querySelector('[data-reset-map]');
const motionDuration = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 850;

function visibleFeatures() {
  return [...loaded.values()].flat().filter(feature => activeFilter === 'all' || feature.properties.activity_type === activeFilter);
}

function fitFeatures(features, padding = 35, maxZoom = 12, duration = 0) {
  const bounds = new maplibregl.LngLatBounds();
  features.forEach(feature => feature.geometry.coordinates.forEach(point => bounds.extend(point)));
  if (!bounds.isEmpty()) map.fitBounds(bounds, {padding, maxZoom, duration});
  return bounds;
}

function selectRoute(route) {
  selected = route.id;
  buttons.forEach(button => button.setAttribute('aria-pressed', String(Number(button.dataset.selectRoute) === selected)));
  if (!map?.getLayer('route-lines') || !loaded.has(route.id)) return;
  const selectedFilter = ['all', ['==', ['get', 'route_id'], route.id]];
  if (activeFilter !== 'all') selectedFilter.push(['==', ['get', 'activity_type'], activeFilter]);
  map.setFilter('selected-route', selectedFilter);
  const features = loaded.get(route.id).filter(feature => activeFilter === 'all' || feature.properties.activity_type === activeFilter);
  const bounds = fitFeatures(features, 55, 13, motionDuration());
  if (bounds.isEmpty()) return;
  const content = document.createElement('div');
  const title = document.createElement('strong');
  title.textContent = route.name;
  content.append(title);
  const details = document.createElement('p');
  const unit = window.adventureUnits;
  const km = Number(route.distance_km);
  const distance = route.distance_km == null ? '' : `${(unit.get() === 'imperial' ? km * unit.kmToMiles : km).toFixed(1)} ${unit.get() === 'imperial' ? 'mi' : 'km'}`;
  details.textContent = [route.activity_label, route.is_group ? `${route.leg_count} legs · whole trip` : '', route.date_start].filter(Boolean).join(' · ');
  if (distance) {
    const value = document.createElement('span');
    value.dataset.distanceKm = route.distance_km;
    value.textContent = distance;
    details.append(document.createTextNode(' · '), value);
  }
  content.append(details);
  if (route.description) {
    const description = document.createElement('p');
    description.textContent = route.description;
    content.append(description);
  }
  route.stories.forEach(story => {
    const link = document.createElement('a');
    link.href = story.url;
    link.textContent = `Read the story: ${story.title} →`;
    link.style.display = 'block';
    content.append(link);
  });
  popup?.remove();
  popup = new maplibregl.Popup({maxWidth: '300px', anchor: 'center'}).setLngLat(bounds.getCenter()).setDOMContent(content).addTo(map);
}

buttons.forEach(button => button.addEventListener('click', () => {
  selectRoute(routes.find(route => route.id === Number(button.dataset.selectRoute)));
}));

resetButton.addEventListener('click', () => {
  selected = undefined;
  buttons.forEach(button => button.setAttribute('aria-pressed', 'false'));
  popup?.remove();
  popup = undefined;
  map.setFilter('selected-route', ['==', ['get', 'route_id'], -1]);
  fitFeatures(visibleFeatures(), 35, 12, motionDuration());
});

document.querySelectorAll('[data-route-filter]').forEach(button => button.addEventListener('click', () => {
  activeFilter = button.dataset.routeFilter;
  selected = undefined;
  document.querySelectorAll('[data-route-filter]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  document.querySelectorAll('[data-route-item]').forEach(item => {
    item.hidden = activeFilter !== 'all' && !item.dataset.modes.split(' ').includes(activeFilter);
  });
  if (map?.getLayer('route-lines')) {
    const filter = activeFilter === 'all' ? null : ['==', ['get', 'activity_type'], activeFilter];
    ['route-lines', 'route-hit-area', 'route-markers'].forEach(layer => map.setFilter(layer, filter));
    map.setFilter('selected-route', ['==', ['get', 'route_id'], -1]);
    fitFeatures(visibleFeatures());
  }
  popup?.remove();
  buttons.forEach(item => item.setAttribute('aria-pressed', 'false'));
}));

async function initialize() {
  try {
    map = new maplibregl.Map({
      container,
      center: [0, 25], zoom: 1,
      scrollZoom: false,
      style: 'https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json',
      transformRequest: url => {
        const requestUrl = new URL(url, window.location.href);
        if (['basemaps.cartocdn.com', 'tiles.basemaps.cartocdn.com'].includes(requestUrl.hostname)) {
          requestUrl.searchParams.set('key', container.dataset.cartoKey);
        }
        return {url: requestUrl.href};
      },
    });
    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    map.on('error', () => { status.textContent = 'The map could not load completely. You can still browse the routes and stories below.'; });
    const results = await Promise.allSettled(routes.map(async route => {
      const response = await fetch(route.url);
      if (!response.ok) throw new Error('Could not load route');
      const data = await response.json();
      const features = data.features.filter(feature => feature.geometry?.type === 'LineString' && feature.geometry.coordinates.length >= 2);
      features.forEach(feature => { const mode = feature.properties?.activity_type || route.activity_type; feature.properties = {...feature.properties, route_id: route.id, activity_type: mode, color: colors[mode] || '#3f5a76'}; });
      loaded.set(route.id, features);
      return features;
    }));
    const features = results.filter(result => result.status === 'fulfilled').flatMap(result => result.value);
    await new Promise(resolve => map.isStyleLoaded() ? resolve() : map.once('load', resolve));
    map.addSource('routes', {type: 'geojson', data: {type: 'FeatureCollection', features}});
    map.addSource('route-points', {type: 'geojson', data: {type: 'FeatureCollection', features: features.map(feature => ({type: 'Feature', properties: feature.properties, geometry: {type: 'Point', coordinates: feature.geometry.coordinates[0]}}))}});
    const filter = activeFilter === 'all' ? undefined : ['==', ['get', 'activity_type'], activeFilter];
    map.addLayer({id: 'route-lines', type: 'line', source: 'routes', ...(filter ? {filter} : {}), paint: {'line-color': ['get', 'color'], 'line-width': 3, 'line-opacity': 0.85}});
    map.addLayer({id: 'selected-route', type: 'line', source: 'routes', filter: ['==', ['get', 'route_id'], -1], paint: {'line-color': '#2b241d', 'line-width': 5}});
    map.addLayer({id: 'route-hit-area', type: 'line', source: 'routes', ...(filter ? {filter} : {}), paint: {'line-width': 18, 'line-opacity': 0}});
    map.addLayer({id: 'route-markers', type: 'circle', source: 'route-points', ...(filter ? {filter} : {}), maxzoom: 8, paint: {'circle-color': ['get', 'color'], 'circle-radius': 5, 'circle-stroke-color': '#fff', 'circle-stroke-width': 1}});
    resetButton.disabled = features.length === 0;
    ['route-hit-area', 'route-markers'].forEach(layer => {
      map.on('click', layer, event => selectRoute(routes.find(route => route.id === event.features[0].properties.route_id)));
      map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; });
    });
    fitFeatures(visibleFeatures());
    status.textContent = results.some(result => result.status === 'rejected') ? 'Some routes could not load. Browse the available routes or use the story links below.' : 'Select a route on the map or in the list below. Use the + and − controls to zoom.';
    if (selected) selectRoute(routes.find(route => route.id === selected));
  } catch (error) {
    status.textContent = 'The map is unavailable. You can still browse the routes and stories below.';
    console.error('Could not load routes map', error);
  }
}

// Delay map and geometry requests until this section approaches the viewport.
const observer = new IntersectionObserver(entries => {
  if (entries.some(entry => entry.isIntersecting)) {
    observer.disconnect();
    initialize();
  }
}, {rootMargin: '200px'});
observer.observe(container);
