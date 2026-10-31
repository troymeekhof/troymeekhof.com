/* Drive map for the Cybertruck stats. Everyday driving is a faint web of
   start→end lines on a 5 km grid; road trips are drawn as the chain of stops
   the truck actually made, and light up with their name, dates and miles on
   hover or tap. Runs only when a #tars2-map element is on the page. */
(function () {
  var el = document.getElementById('tars2-map');
  if (!el || !('fetch' in window)) return;
  var LEAFLET = 'https://unpkg.com/leaflet@1.9.4/dist/';
  function load(tag, attrs) {
    return new Promise(function (res, rej) {
      var n = document.createElement(tag);
      for (var k in attrs) n.setAttribute(k, attrs[k]);
      n.onload = res; n.onerror = rej;
      document.head.appendChild(n);
    });
  }
  function fmt(n) { return n.toLocaleString('en-US'); }
  function dates(a, b) {
    var o = { month: 'short', day: 'numeric' }, A = new Date(a + 'T12:00:00'), B = new Date(b + 'T12:00:00');
    var s = A.toLocaleDateString('en-US', o);
    if (a !== b) s += ' – ' + B.toLocaleDateString('en-US', o);
    return s + ', ' + B.getFullYear();
  }
  function start() {
    el.setAttribute('aria-busy', 'true');
    Promise.all([
      load('link', { rel: 'stylesheet', href: LEAFLET + 'leaflet.css', crossorigin: '' }),
      load('script', { src: LEAFLET + 'leaflet.js', crossorigin: '' }),
      fetch('/cybertruck/stats/drives-map.json').then(function (r) { return r.json(); }),
      fetch('/cybertruck/stats/trips.json').then(function (r) { return r.json(); })
    ]).then(function (r) {
      var local = r[2], trips = r[3].trips || [], L = window.L;
      var MAXZ = 6;
      var map = L.map(el, { scrollWheelZoom: false, worldCopyJump: true, minZoom: 3, maxZoom: MAXZ, zoomSnap: 1, bounceAtZoomLimits: false });
      map.attributionControl.setPrefix('');
      map.on('zoomend', function () { if (map.getZoom() > MAXZ) map.setZoom(MAXZ); });
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: MAXZ, minZoom: 3, className: 'tars2-tiles',
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
      }).addTo(map);
      var css = getComputedStyle(document.documentElement);
      var blue = css.getPropertyValue('--primary').trim() || '#9fd0e3';
      var amber = css.getPropertyValue('--amber').trim() || '#e0a857';

      // Everyday driving: a quiet web.
      var web = [];
      local.segments.forEach(function (s) {
        web.push(L.polyline([[s[0], s[1]], [s[2], s[3]]], { color: blue, weight: 1, opacity: Math.min(.35, .08 + .04 * s[4]), interactive: false, lineCap: 'round' }));
      });
      L.featureGroup(web).addTo(map);

      // Road trips: chained stops, hoverable.
      var all = [], list = document.getElementById('tars2-trips');
      trips.forEach(function (t) {
        var row = null;
        var halo = L.polyline(t.path, { color: amber, weight: 9, opacity: .10, interactive: false, lineJoin: 'round', lineCap: 'round', smoothFactor: 1.2 });
        var line = L.polyline(t.path, { color: amber, weight: 2.2, opacity: .8, interactive: false, lineJoin: 'round', lineCap: 'round', smoothFactor: 1.2 });
        var hit = L.polyline(t.path, { color: amber, weight: 16, opacity: 0, lineJoin: 'round', bubblingMouseEvents: false });
        var tip = '<b>' + t.name + '</b><br>' + dates(t.start, t.end) + ' · ' + fmt(t.miles) + ' mi · ' + t.days + ' day' + (t.days === 1 ? '' : 's') + '<br>Farthest stop: ' + t.farthest;
        hit.bindTooltip(tip, { sticky: true, direction: 'top', opacity: .96, className: 'tars2-tip' });
        function on() { line.setStyle({ weight: 4, opacity: 1 }); halo.setStyle({ opacity: .35 }); line.bringToFront(); hit.bringToFront(); if (row) row.classList.add('is-on'); }
        function off() { line.setStyle({ weight: 2.2, opacity: .8 }); halo.setStyle({ opacity: .10 }); if (row) row.classList.remove('is-on'); }
        function zoom() { map.fitBounds(line.getBounds(), { padding: [30, 30], maxZoom: MAXZ }); }
        hit.on('mouseover', on).on('mouseout', off).on('click', zoom);
        all.push(halo, line, hit);
        if (list) {
          row = document.createElement('li');
          row.innerHTML = '<b>' + t.name + '</b><span>' + dates(t.start, t.end) + ' · ' + fmt(t.miles) + ' mi</span>';
          row.tabIndex = 0;
          row.addEventListener('mouseenter', on); row.addEventListener('mouseleave', off);
          row.addEventListener('focus', on); row.addEventListener('blur', off);
          row.addEventListener('click', function () { zoom(); el.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); });
          list.appendChild(row);
        }
      });
      var group = L.featureGroup(all).addTo(map);
      var bounds = group.getBounds();
      map.fitBounds(bounds, { padding: [16, 16] });
      var btn = L.control({ position: 'topright' });
      btn.onAdd = function () {
        var d = L.DomUtil.create('div', 'leaflet-bar tars2-home');
        d.innerHTML = '<a href="#" title="Michigan" role="button" aria-label="Zoom to Michigan">MI</a><a href="#" title="Every trip" role="button" aria-label="Show every trip">All</a>';
        d.children[0].onclick = function (e) { e.preventDefault(); map.setView([44.2, -85.0], MAXZ); };
        d.children[1].onclick = function (e) { e.preventDefault(); map.fitBounds(bounds, { padding: [16, 16] }); };
        return d;
      };
      btn.addTo(map);
      el.removeAttribute('aria-busy');
      el.classList.add('is-ready');
    }).catch(function () {
      el.removeAttribute('aria-busy');
      el.innerHTML = '<p class="mnote">The map could not load right now. <a href="/cybertruck/stats/">See the numbers instead.</a></p>';
    });
  }
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (es) { if (es.some(function (e) { return e.isIntersecting; })) { io.disconnect(); start(); } }, { rootMargin: '400px' });
    io.observe(el);
  } else start();
})();
