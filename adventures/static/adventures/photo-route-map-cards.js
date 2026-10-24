import * as maplibregl from 'https://unpkg.com/maplibre-gl@6.13.0/dist/maplibre-gl.mjs';

const container = document.getElementById('routes-map');
const routes = JSON.parse(document.getElementById('map-routes').textContent);
const waypoints = JSON.parse(document.getElementById('map-waypoints').textContent);
const status = document.getElementById('routes-map-status');
const deck = document.getElementById('waypoint-deck');
const colors = Object.fromEntries(
  [...document.querySelectorAll('[data-route-color]')].map(button => [button.dataset.routeFilter, button.dataset.routeColor])
);
let map, popup, selected, activeFilter = 'all';
let activeDeck, activePhotos = [], photoIndex = 0, activeMarker, deckRequest = 0;
const markers = new Map();
const loaded = new Map();
// Marker detail follows map zoom: 0 bubble, 1 thumbnail, 2 small fan, 3 full fan.
const LEVEL_ZOOM = [4, 7, 10];
const LEVEL_MERGE_PX = [64, 88, 124, 164];
let deckStops = [];
const buttons = [...document.querySelectorAll('[data-select-route]')];
const resetButton = document.querySelector('[data-reset-map]');
const motionDuration = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 850;

function visibleFeatures() {
  return [...loaded.values()].flat().filter(feature => activeFilter === 'all' || feature.properties.activity_type === activeFilter);
}

function visibleWaypoints() {
  return waypoints.filter(stop => {
    const route = routes.find(item => item.id === stop.route_id);
    return route && (!selected || selected === stop.route_id) &&
      (activeFilter === 'all' || route.activity_types.includes(activeFilter));
  });
}

function markerLevel() {
  const zoom = map.getZoom();
  return LEVEL_ZOOM.filter(limit => zoom >= limit).length;
}

function updateMarkers() {
  if (!map || !markers.size) return;
  const level = markerLevel();
  const stops = visibleWaypoints();
  const points = stops.map(stop => ({stop, point: map.project(stop.coordinates)}));
  const groups = [];
  points.forEach(item => {
    const touching = groups.filter(group => group.some(member =>
      Math.hypot(member.point.x - item.point.x, member.point.y - item.point.y) < LEVEL_MERGE_PX[level]
    ));
    if (!touching.length) groups.push([item]);
    else {
      const first = touching[0];
      first.push(item);
      touching.slice(1).forEach(group => {
        first.push(...group);
        groups.splice(groups.indexOf(group), 1);
      });
    }
  });
  const visibleIds = new Set(stops.map(stop => stop.id));
  markers.forEach(marker => { marker.getElement().hidden = !visibleIds.has(Number(marker.getElement().dataset.stopId)); });
  groups.forEach(group => {
    const lead = group[0].stop;
    const button = markers.get(lead.id).getElement();
    group.slice(1).forEach(({stop}) => { markers.get(stop.id).getElement().hidden = true; });
    const total = group.reduce((sum, {stop}) => sum + stop.photo_count, 0);
    const merged = group.length > 1;
    button.classList.remove('waypoint-level-0', 'waypoint-level-1', 'waypoint-level-2', 'waypoint-level-3');
    button.classList.add('waypoint-preview-button', `waypoint-level-${level}`);
    button.classList.toggle('waypoint-merged', merged);
    button.dataset.clusterIds = merged ? group.map(({stop}) => stop.id).join(',') : '';
    button.setAttribute('aria-label', merged
      ? `${group.length} photo stops, ${total} photos; zoom in`
      : `${lead.name}, ${lead.photo_count} ${lead.photo_count === 1 ? 'photo' : 'photos'}`);
    button.querySelector('.waypoint-preview-count').textContent = merged && level > 0 ? `${group.length} stops` : String(total);
    // A stop's cover is its first photo; merged stacks show each member's cover.
    const covers = merged ? group.map(({stop}) => stop.previews[0]) : lead.previews;
    renderPreview(button, covers.slice(0, 3));
    markers.get(lead.id).setOffset([0, 8]);
  });
}

function renderPreview(button, urls) {
  const key = urls.join('|');
  if (button.dataset.previewKey === key) return;
  button.dataset.previewKey = key;
  const stack = button.querySelector('.waypoint-preview-stack');
  stack.replaceChildren();
  urls.forEach((url, index) => {
    const card = document.createElement('span');
    card.className = `waypoint-preview-card waypoint-preview-card-${index}`;
    const photo = document.createElement('img');
    photo.src = url;
    photo.alt = '';
    photo.loading = 'lazy';
    card.append(photo);
    stack.append(card);
  });
}

function zoomIntoGroup(button) {
  const ids = button.dataset.clusterIds.split(',').map(Number);
  const bounds = new maplibregl.LngLatBounds();
  waypoints.filter(stop => ids.includes(stop.id)).forEach(stop => bounds.extend(stop.coordinates));
  const before = map.getZoom();
  map.fitBounds(bounds, {padding: 140, maxZoom: Math.min(before + 3, 17), duration: motionDuration()});
  // Stops sharing (almost) one spot cannot separate; open the first one, the route strip reaches the rest.
  if (before >= 16.5) openDeck(waypoints.find(stop => stop.id === ids[0]), button);
}

// Order stops along their route so the deck's route strip reads start to finish.
const progressCache = new Map();
function routeProgress(stop) {
  if (progressCache.has(stop.id)) return progressCache.get(stop.id);
  const line = (loaded.get(stop.route_id) || []).flatMap(feature => feature.geometry.coordinates);
  let best = 0, bestDistance = Infinity;
  line.forEach((point, index) => {
    const distance = (point[0] - stop.coordinates[0]) ** 2 + (point[1] - stop.coordinates[1]) ** 2;
    if (distance < bestDistance) { best = index; bestDistance = distance; }
  });
  progressCache.set(stop.id, best);
  return best;
}

function orderedStops(routeId) {
  return visibleWaypoints().filter(stop => stop.route_id === routeId).sort((a, b) => a.route_id - b.route_id || routeProgress(a) - routeProgress(b));
}

function fitFeatures(features, padding = 35, maxZoom = 12, duration = 0) {
  const bounds = new maplibregl.LngLatBounds();
  features.forEach(feature => feature.geometry.coordinates.forEach(point => bounds.extend(point)));
  visibleWaypoints().forEach(stop => bounds.extend(stop.coordinates));
  if (!bounds.isEmpty()) map.fitBounds(bounds, {padding, maxZoom, duration});
  return bounds;
}

function selectRoute(route) {
  if (!route) return;
  closeDeck(false);
  selected = route.id;
  updateMarkers();
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
  closeDeck(false);
  selected = undefined;
  updateMarkers();
  buttons.forEach(button => button.setAttribute('aria-pressed', 'false'));
  popup?.remove();
  popup = undefined;
  map.setFilter('selected-route', ['==', ['get', 'route_id'], -1]);
  fitFeatures(visibleFeatures(), 35, 12, motionDuration());
});

document.querySelectorAll('[data-route-filter]').forEach(button => button.addEventListener('click', () => {
  closeDeck(false);
  activeFilter = button.dataset.routeFilter;
  selected = undefined;
  updateMarkers();
  document.querySelectorAll('[data-route-filter]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  document.querySelectorAll('[data-route-item]').forEach(item => {
    item.hidden = activeFilter !== 'all' && !item.dataset.modes.split(' ').includes(activeFilter);
  });
  if (map?.getLayer('route-lines')) {
    const filter = activeFilter === 'all' ? null : ['==', ['get', 'activity_type'], activeFilter];
    ['route-lines', 'route-hit-area'].forEach(layer => map.setFilter(layer, filter));
    map.setFilter('selected-route', ['==', ['get', 'route_id'], -1]);
    fitFeatures(visibleFeatures());
  }
  popup?.remove();
  buttons.forEach(item => item.setAttribute('aria-pressed', 'false'));
}));

function renderDeck() {
  const photo = activePhotos[photoIndex];
  if (!photo) return;
  deck.querySelector('[data-deck-name]').textContent = activeDeck.name;
  const stopNumber = deckStops.findIndex(stop => stop.id === activeDeck.id) + 1;
  deck.querySelector('[data-deck-count]').textContent =
    `${stopNumber ? `Stop ${stopNumber} of ${deckStops.length} · ` : ''}${photoIndex + 1} of ${activePhotos.length} photos`;
  const image = deck.querySelector('[data-deck-image]');
  image.src = photo.url;
  image.alt = photo.alt;
  deck.querySelector('[data-deck-caption]').textContent = photo.caption;
  const previous = deck.querySelector('[data-deck-prev]');
  const next = deck.querySelector('[data-deck-next]');
  previous.disabled = next.disabled = activePhotos.length < 2;
  previous.querySelector('img').src = activePhotos[(photoIndex - 1 + activePhotos.length) % activePhotos.length].url;
  next.querySelector('img').src = activePhotos[(photoIndex + 1) % activePhotos.length].url;
  renderStrip();
}

function renderStrip() {
  const strip = deck.querySelector('[data-deck-strip]');
  strip.replaceChildren();
  strip.hidden = deckStops.length < 2;
  deckStops.forEach((stop, index) => {
    const dot = document.createElement('button');
    dot.type = 'button';
    dot.className = 'waypoint-strip-dot';
    dot.style.left = `${index / (deckStops.length - 1) * 100}%`;
    dot.setAttribute('aria-label', `${stop.name}, ${stop.photo_count} ${stop.photo_count === 1 ? 'photo' : 'photos'}`);
    if (stop.id === activeDeck.id) dot.setAttribute('aria-current', 'true');
    dot.addEventListener('click', () => {
      map.easeTo({center: stop.coordinates, duration: motionDuration()});
      openDeck(stop, markers.get(stop.id).getElement());
    });
    strip.append(dot);
  });
}

function closeDeck(restoreFocus = true) {
  deckRequest++;
  deck.hidden = true;
  activeDeck = undefined;
  activePhotos = [];
  if (restoreFocus && activeMarker) activeMarker.focus();
}

async function openDeck(stop, marker) {
  const request = ++deckRequest;
  activeMarker = marker;
  try {
    const response = await fetch(stop.url);
    if (!response.ok) throw new Error('Photo stop unavailable');
    const details = await response.json();
    if (request !== deckRequest) return;
    activeDeck = stop;
    activePhotos = details.photos;
    photoIndex = 0;
    if (!activePhotos.length) throw new Error('Photo stop has no photos');
    const wasOpen = !deck.hidden;
    deckStops = orderedStops(stop.route_id);
    if (!deckStops.some(item => item.id === stop.id)) deckStops.push(stop);
    deck.hidden = false;
    renderDeck();
    map.easeTo({center: stop.coordinates, duration: motionDuration()});
    (wasOpen && deck.querySelector('[aria-current="true"]') || deck.querySelector('[data-deck-close]')).focus();
  } catch (error) {
    if (request === deckRequest) status.textContent = 'The photos for this stop could not load. Try again later.';
  }
}

function stepPhoto(delta) {
  if (!activePhotos.length) return;
  photoIndex = (photoIndex + delta + activePhotos.length) % activePhotos.length;
  renderDeck();
}

deck.querySelector('[data-deck-close]').addEventListener('click', () => closeDeck());
deck.querySelector('[data-deck-prev]').addEventListener('click', () => stepPhoto(-1));
deck.querySelector('[data-deck-next]').addEventListener('click', () => stepPhoto(1));
deck.addEventListener('keydown', event => {
  if (event.key === 'Escape') { closeDeck(); event.preventDefault(); }
  if (event.key === 'ArrowLeft') { stepPhoto(-1); event.preventDefault(); }
  if (event.key === 'ArrowRight') { stepPhoto(1); event.preventDefault(); }
  if (event.key === 'Tab') {
    const controls = [...deck.querySelectorAll('button:not(:disabled)')];
    const first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) { last.focus(); event.preventDefault(); }
    if (!event.shiftKey && document.activeElement === last) { first.focus(); event.preventDefault(); }
  }
});
let touchStart;
deck.addEventListener('touchstart', event => { touchStart = event.touches[0]?.clientX; }, {passive: true});
deck.addEventListener('touchend', event => {
  if (touchStart === undefined) return;
  const delta = event.changedTouches[0]?.clientX - touchStart;
  if (Math.abs(delta) > 40) stepPhoto(delta < 0 ? 1 : -1);
  touchStart = undefined;
}, {passive: true});

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
    // Shaded relief under water, roads, and labels; free elevation tiles, no key needed.
    map.addSource('terrain', {
      type: 'raster-dem', encoding: 'terrarium', tileSize: 256, maxzoom: 14,
      tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
      attribution: 'Terrain: Mapzen, AWS Terrain Tiles',
    });
    map.addLayer({
      id: 'hillshade', type: 'hillshade', source: 'terrain',
      paint: {
        'hillshade-exaggeration': 0.45,
        'hillshade-shadow-color': '#6b5a3e',
        'hillshade-highlight-color': '#fffaf0',
        'hillshade-accent-color': '#8a7a5f',
      },
    }, map.getLayer('water') ? 'water' : undefined);
    // The basemap hides country names until zoom 2-3; show them when fully zoomed out.
    ['place_country_1', 'place_country_2'].forEach(id => {
      const layer = map.getLayer(id);
      if (layer) map.setLayerZoomRange(id, 0, layer.maxzoom ?? 24);
    });
    map.addSource('routes', {type: 'geojson', data: {type: 'FeatureCollection', features}});
    const filter = activeFilter === 'all' ? undefined : ['==', ['get', 'activity_type'], activeFilter];
    map.addLayer({id: 'route-lines', type: 'line', source: 'routes', ...(filter ? {filter} : {}), paint: {'line-color': ['get', 'color'], 'line-width': 3, 'line-opacity': 0.85}});
    map.addLayer({id: 'selected-route', type: 'line', source: 'routes', filter: ['==', ['get', 'route_id'], -1], paint: {'line-color': '#2b241d', 'line-width': 5}});
    map.addLayer({id: 'route-hit-area', type: 'line', source: 'routes', ...(filter ? {filter} : {}), paint: {'line-width': 18, 'line-opacity': 0}});
    waypoints.forEach(stop => {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.stopId = stop.id;
      const stack = document.createElement('span');
      stack.className = 'waypoint-preview-stack';
      stack.setAttribute('aria-hidden', 'true');
      const count = document.createElement('span');
      count.className = 'waypoint-preview-count';
      count.setAttribute('aria-hidden', 'true');
      const stem = document.createElement('span');
      stem.className = 'waypoint-stem';
      stem.setAttribute('aria-hidden', 'true');
      const dot = document.createElement('span');
      dot.className = 'waypoint-dot-core';
      dot.setAttribute('aria-hidden', 'true');
      button.append(stack, count, stem, dot);
      button.addEventListener('click', event => {
        event.stopPropagation();
        if (button.dataset.clusterIds) zoomIntoGroup(button);
        else openDeck(stop, button);
      });
      markers.set(stop.id, new maplibregl.Marker({element: button, anchor: 'bottom', offset: [0, 8]}).setLngLat(stop.coordinates).addTo(map));
    });
    map.on('moveend', updateMarkers);
    map.on('resize', updateMarkers);
    updateMarkers();
    resetButton.disabled = features.length === 0;
    ['route-hit-area'].forEach(layer => {
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
