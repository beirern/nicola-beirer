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
let showPhotos = true;
let activeDeck, activePhotos = [], photoIndex = 0, activeMarker, deckRequest = 0;
const markers = new Map();
const loaded = new Map();
// Marker detail follows map zoom: 0 bubble, 1 thumbnail, 2 small fan, 3 full fan.
const LEVEL_ZOOM = [4, 7, 10];
// A lone POI tapped from far out first zooms to show its surroundings; a second tap opens its photos.
const CONTEXT_MIN_ZOOM = 7;
const CONTEXT_ZOOM = 8.5;
const LEVEL_CARD = [[32, 40], [46, 58], [68, 86], [92, 116]];
const LEVEL_MERGE_PX = [64, 88, 124, 164];
let deckStops = [];
let listIds, listNumbers = new Map(), listOpener;
const list = document.getElementById('waypoint-list');
const buttons = [...document.querySelectorAll('[data-select-route]')];
const resetButton = document.querySelector('[data-reset-map]');
const motionDuration = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 850;

function visibleFeatures() {
  return [...loaded.values()].flat().filter(feature => activeFilter === 'all' || feature.properties.activity_type === activeFilter);
}

// The overview frames every route, so filtering never zooms into one lone route.
function allFeatures() {
  return [...loaded.values()].flat();
}

function visibleWaypoints() {
  if (!showPhotos) return [];
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

// Pick where a stack sits relative to its dot: above by default, beside it when the route runs underneath.
function routeLine(routeId) {
  const points = (loaded.get(routeId) || []).flatMap(feature => feature.geometry.coordinates);
  const step = Math.max(1, Math.ceil(points.length / 500));
  return points.filter((_, index) => index % step === 0).map(point => map.project(point));
}

function stackSide(dot, level, line) {
  const [w, h] = LEVEL_CARD[level];
  const reach = 0.74 * w, edge = 14, pad = 6;
  const rects = {
    up: [-reach, -(h + 14), reach, -14],
    right: [edge, -(h + 8), edge + 2 * reach, -8],
    left: [-(edge + 2 * reach), -(h + 8), -edge, -8],
  };
  let best = 'up', fewest = Infinity;
  for (const [side, [x1, y1, x2, y2]] of Object.entries(rects)) {
    const hits = line.filter(point =>
      point.x > dot.x + x1 - pad && point.x < dot.x + x2 + pad && point.y > dot.y + y1 - pad && point.y < dot.y + y2 + pad).length;
    if (hits < fewest) { fewest = hits; best = side; }
    if (fewest === 0) break;
  }
  return best;
}

function updateMarkers() {
  if (!map || !markers.size) return;
  const level = markerLevel();
  const stops = visibleWaypoints();
  const pinned = stops.filter(stop => listIds?.includes(stop.id));
  const free = stops.filter(stop => !listIds?.includes(stop.id));
  const points = free.map(stop => ({stop, point: map.project(stop.coordinates)}));
  // POIs from different routes only merge when much closer, so nearby routes keep separate stacks.
  const touches = (a, b) => Math.hypot(a.point.x - b.point.x, a.point.y - b.point.y) <
    LEVEL_MERGE_PX[level] * (a.stop.route_id === b.stop.route_id ? 1 : 0.5);
  const groups = [];
  points.forEach(item => {
    const touching = groups.filter(group => group.some(member => touches(member, item)));
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
  const lines = new Map();
  const visibleIds = new Set(stops.map(stop => stop.id));
  markers.forEach(marker => {
    const element = marker.getElement();
    element.hidden = !visibleIds.has(Number(element.dataset.stopId));
    element.classList.remove('waypoint-numbered', 'waypoint-highlight', 'waypoint-side-left', 'waypoint-side-right');
    element.style.removeProperty('--poi-color');
  });
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
      ? `${group.length} points of interest, ${total} photos; open the list`
      : `${lead.name}, ${lead.photo_count} ${lead.photo_count === 1 ? 'photo' : 'photos'}`);
    button.querySelector('.waypoint-preview-count').textContent = merged && level > 0 ? `${group.length} POIs` : String(total);
    // A POI's cover is its first photo; merged stacks show each member's cover.
    const covers = merged ? group.map(({stop}) => stop.previews[0]) : lead.previews;
    renderPreview(button, covers.slice(0, 3));
    markers.get(lead.id).setOffset([0, 8]);
    if (level > 0) {
      const line = [...new Set(group.map(({stop}) => stop.route_id))].flatMap(routeId => {
        if (!lines.has(routeId)) lines.set(routeId, routeLine(routeId));
        return lines.get(routeId);
      });
      const side = stackSide(group[0].point, level, line);
      if (side !== 'up') button.classList.add(`waypoint-side-${side}`);
    }
  });
  // POIs from an open list show as numbered dots matching the list.
  pinned.forEach(stop => {
    const button = markers.get(stop.id).getElement();
    const route = routes.find(item => item.id === stop.route_id);
    button.classList.remove('waypoint-level-0', 'waypoint-level-1', 'waypoint-level-2', 'waypoint-level-3', 'waypoint-merged');
    button.classList.add('waypoint-preview-button', 'waypoint-numbered');
    button.dataset.clusterIds = '';
    button.style.setProperty('--poi-color', colors[route?.activity_type] || '#a8532e');
    button.setAttribute('aria-label', `${listNumbers.get(stop.id)}. ${stop.name}, ${stop.photo_count} ${stop.photo_count === 1 ? 'photo' : 'photos'}`);
    button.querySelector('.waypoint-preview-count').textContent = String(listNumbers.get(stop.id));
    renderPreview(button, []);
    markers.get(stop.id).setOffset([0, 22]);
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

function listPadding() {
  const phone = window.matchMedia('(max-width: 600px)').matches;
  return phone
    ? {top: 50, left: 40, right: 40, bottom: Math.round(container.clientHeight * 0.5) + 30}
    : {top: 60, bottom: 60, left: 60, right: 260};
}

function openList(button) {
  const ids = button.dataset.clusterIds.split(',').map(Number);
  const members = waypoints.filter(stop => ids.includes(stop.id));
  const sections = [...new Set(members.map(stop => stop.route_id))].sort((a, b) => a - b).map(routeId => ({
    route: routes.find(route => route.id === routeId),
    stops: members.filter(stop => stop.route_id === routeId).sort((a, b) => routeProgress(a) - routeProgress(b)),
  }));
  listIds = ids;
  listOpener = button;
  listNumbers = new Map(sections.flatMap(section => section.stops.map((stop, index) => [stop.id, index + 1])));
  renderList(sections, members.length);
  list.hidden = false;
  const bounds = new maplibregl.LngLatBounds();
  members.forEach(stop => bounds.extend(stop.coordinates));
  map.fitBounds(bounds, {padding: listPadding(), maxZoom: 16, duration: motionDuration()});
  updateMarkers();
  list.querySelector('[data-list-close]').focus();
}

function renderList(sections, total) {
  list.querySelector('[data-list-title]').textContent = `${total} points of interest`;
  const body = list.querySelector('[data-list-body]');
  body.replaceChildren();
  sections.forEach(({route, stops}) => {
    if (sections.length > 1 || route) {
      const heading = document.createElement('h3');
      heading.textContent = route?.name || 'Route';
      heading.style.setProperty('--poi-color', colors[route?.activity_type] || '#a8532e');
      body.append(heading);
    }
    stops.forEach(stop => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'waypoint-list-row';
      row.style.setProperty('--poi-color', colors[route?.activity_type] || '#a8532e');
      const number = document.createElement('span');
      number.className = 'waypoint-list-number';
      number.textContent = String(listNumbers.get(stop.id));
      const cover = document.createElement('img');
      cover.src = stop.previews[0];
      cover.alt = '';
      const text = document.createElement('span');
      text.className = 'waypoint-list-text';
      const name = document.createElement('strong');
      name.textContent = stop.name;
      const count = document.createElement('small');
      count.textContent = `${stop.photo_count} ${stop.photo_count === 1 ? 'photo' : 'photos'}`;
      text.append(name, count);
      row.append(number, cover, text);
      const marker = () => markers.get(stop.id)?.getElement();
      const light = on => marker()?.classList.toggle('waypoint-highlight', on);
      row.addEventListener('mouseenter', () => light(true));
      row.addEventListener('mouseleave', () => light(false));
      row.addEventListener('focus', () => light(true));
      row.addEventListener('blur', () => light(false));
      row.addEventListener('click', () => {
        map.easeTo({center: stop.coordinates, duration: motionDuration()});
        openDeck(stop, row);
      });
      body.append(row);
    });
  });
}

function closeList(restoreFocus = false) {
  if (!listIds) return;
  listIds = undefined;
  listNumbers = new Map();
  list.hidden = true;
  updateMarkers();
  if (restoreFocus && listOpener?.isConnected) listOpener.focus();
}

list.querySelector('[data-list-close]').addEventListener('click', () => closeList(true));
list.addEventListener('keydown', event => {
  if (event.key === 'Escape') { closeList(true); event.preventDefault(); }
});

// Order POIs along their route so the deck's route strip reads start to finish.
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

// Frame the POI's whole route when it fits at a readable zoom; otherwise stay close on the POI.
function contextCamera(stop) {
  const bounds = new maplibregl.LngLatBounds();
  (loaded.get(stop.route_id) || []).forEach(feature => feature.geometry.coordinates.forEach(point => bounds.extend(point)));
  bounds.extend(stop.coordinates);
  const fit = map.cameraForBounds(bounds, {padding: {top: 150, bottom: 70, left: 80, right: 80}, maxZoom: 12});
  return fit && fit.zoom >= CONTEXT_ZOOM
    ? {center: fit.center, zoom: fit.zoom}
    : {center: stop.coordinates, zoom: CONTEXT_ZOOM};
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
  closeList();
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
  popup = undefined;
  const show = () => {
    if (selected !== route.id) return;
    popup?.remove();
    const spot = popupSpot(route);
    popup = new maplibregl.Popup({maxWidth: '300px', anchor: spot?.anchor || 'center', offset: spot ? 16 : 0})
      .setLngLat(spot?.lngLat || bounds.getCenter()).setDOMContent(content).addTo(map);
  };
  if (map.isMoving()) map.once('moveend', show); else show();
}

// Anchor the popup beside the route with its pointer touching the line, clear of photo stacks and the line itself.
function popupSpot(route) {
  const canvas = map.getCanvas();
  const width = canvas.clientWidth, height = canvas.clientHeight;
  const popupW = Math.min(300, width - 24), popupH = 190, gap = 20, margin = 8;
  const origin = container.getBoundingClientRect();
  // Measure the drawn cards, badges, and dots (the button box is smaller than a fanned stack).
  const pad = 12;
  const boxes = [...markers.values()].map(marker => marker.getElement()).filter(element => !element.hidden)
    .flatMap(element => [...element.querySelectorAll('.waypoint-preview-card, .waypoint-preview-count, .waypoint-dot-core')])
    .filter(part => part.offsetParent)
    .map(part => {
      const rect = part.getBoundingClientRect();
      return {left: rect.left - origin.left - pad, right: rect.right - origin.left + pad, top: rect.top - origin.top - pad, bottom: rect.bottom - origin.top + pad};
    });
  const line = (loaded.get(route.id) || []).filter(feature => activeFilter === 'all' || feature.properties.activity_type === activeFilter)
    .flatMap(feature => feature.geometry.coordinates).map(point => map.project(point));
  if (line.length < 2) return undefined;
  const centre = line.reduce((sum, point) => ({x: sum.x + point.x / line.length, y: sum.y + point.y / line.length}), {x: 0, y: 0});
  const step = Math.max(1, Math.ceil(line.length / 40));
  let best, bestScore = -Infinity;
  for (const minimum of [1, 0]) {
  for (let index = 0; index < line.length; index += step) {
    const point = line[index];
    const options = {
      left: [point.x + gap, point.y - popupH / 2], right: [point.x - gap - popupW, point.y - popupH / 2],
      top: [point.x - popupW / 2, point.y + gap], bottom: [point.x - popupW / 2, point.y - gap - popupH],
    };
    for (const [anchor, [left, top]] of Object.entries(options)) {
      const right = left + popupW, bottom = top + popupH;
      if (left < margin || top < margin || right > width - margin || bottom > height - margin) continue;
      if (right > width - 70 && top < 170) continue;
      if (line.some(other => other.x > left - 4 && other.x < right + 4 && other.y > top - 4 && other.y < bottom + 4)) continue;
      const clearance = Math.min(Infinity, ...boxes.map(box =>
        Math.hypot(Math.max(box.left - right, left - box.right, 0), Math.max(box.top - bottom, top - box.bottom, 0))));
      if (clearance < minimum) continue;
      const score = Math.min(clearance, 80) - Math.hypot(point.x - centre.x, point.y - centre.y) / 30;
      if (score > bestScore) { bestScore = score; best = {anchor, point}; }
    }
  }
  if (best) break;
  }
  return best && {anchor: best.anchor, lngLat: map.unproject([best.point.x, best.point.y])};
}

buttons.forEach(button => button.addEventListener('click', () => {
  selectRoute(routes.find(route => route.id === Number(button.dataset.selectRoute)));
}));

resetButton.addEventListener('click', () => {
  closeDeck(false);
  closeList();
  selected = undefined;
  buttons.forEach(button => button.setAttribute('aria-pressed', 'false'));
  popup?.remove();
  popup = undefined;
  map.setFilter('selected-route', ['==', ['get', 'route_id'], -1]);
  fitFeatures(allFeatures(), 35, 12, motionDuration());
  if (!map.isMoving()) updateMarkers();
});

document.querySelector('[data-toggle-photos]').addEventListener('click', event => {
  showPhotos = !showPhotos;
  event.currentTarget.textContent = showPhotos ? 'Hide photos' : 'Show photos';
  if (!showPhotos) {
    closeDeck(false);
    closeList();
  }
  updateMarkers();
});

document.querySelectorAll('[data-route-filter]').forEach(button => button.addEventListener('click', () => {
  closeDeck(false);
  closeList();
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
    fitFeatures(allFeatures());
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
    `${stopNumber ? `POI ${stopNumber} of ${deckStops.length} · ` : ''}${photoIndex + 1} of ${activePhotos.length} photos`;
  const image = deck.querySelector('[data-deck-image]');
  image.src = photo.url;
  image.alt = photo.alt;
  const [year, month, day] = (photo.taken_on || '').split('-').map(Number);
  const taken = photo.taken_on ? new Date(year, month - 1, day).toLocaleDateString(undefined, {year: 'numeric', month: 'short', day: 'numeric'}) : '';
  deck.querySelector('[data-deck-caption]').textContent = [taken, photo.caption].filter(Boolean).join(' - ');
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
    if (!response.ok) throw new Error('Point of interest unavailable');
    const details = await response.json();
    if (request !== deckRequest) return;
    activeDeck = stop;
    activePhotos = details.photos;
    photoIndex = 0;
    if (!activePhotos.length) throw new Error('Point of interest has no photos');
    const wasOpen = !deck.hidden;
    deckStops = orderedStops(stop.route_id);
    if (!deckStops.some(item => item.id === stop.id)) deckStops.push(stop);
    deck.hidden = false;
    renderDeck();
    map.easeTo({center: stop.coordinates, duration: motionDuration()});
    (wasOpen && deck.querySelector('[aria-current="true"]') || deck.querySelector('[data-deck-close]')).focus();
  } catch (error) {
    if (request === deckRequest) status.textContent = 'The photos for this point of interest could not load. Try again later.';
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
      // Let in-flight tiles finish and keep more of them, so zooming back doesn't redraw blurry placeholders.
      cancelPendingTileRequestsWhileZooming: false,
      maxTileCacheSize: 400,
      maxTileCacheZoomLevels: 8,
      style: 'https://api.maptiler.com/maps/01a17198-5261-74f2-923d-4f19ac3cb5c2/style.json',
      transformRequest: url => {
        const requestUrl = new URL(url, window.location.href);
        if (requestUrl.hostname === 'api.maptiler.com') {
          requestUrl.searchParams.set('key', container.dataset.maptilerKey);
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
        if (button.dataset.clusterIds) openList(button);
        else if (map.getZoom() < CONTEXT_MIN_ZOOM && !button.classList.contains('waypoint-numbered')) {
          status.textContent = `Zoomed in on ${stop.name}. Select it again to see its photos.`;
          map.flyTo({...contextCamera(stop), duration: motionDuration()});
        } else openDeck(stop, button);
      });
      markers.set(stop.id, new maplibregl.Marker({element: button, anchor: 'bottom', offset: [0, 8]}).setLngLat(stop.coordinates).addTo(map));
    });
    map.on('moveend', updateMarkers);
    // Keep stack size in step with the zoom while an animation runs, not only once it ends.
    let frame;
    map.on('zoom', () => { frame ??= requestAnimationFrame(() => { frame = undefined; updateMarkers(); }); });
    map.on('resize', updateMarkers);
    map.on('click', () => closeList());
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
