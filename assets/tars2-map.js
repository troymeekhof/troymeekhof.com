/* Drive map for the Cybertruck stats: draws every logged drive (start to end,
   on a 5 km grid, no addresses) with Leaflet on top of a dark basemap.
   Runs only when a #tars2-map element is on the page. */
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
  function start() {
    el.setAttribute('aria-busy', 'true');
    Promise.all([
      load('link', { rel: 'stylesheet', href: LEAFLET + 'leaflet.css', crossorigin: '' }),
      load('script', { src: LEAFLET + 'leaflet.js', crossorigin: '' }),
      fetch('/cybertruck/stats/drives-map.json').then(function (r) { return r.json(); })
    ]).then(function (r) {
      var data = r[2], L = window.L;
      var MAXZ = 6;
      var map = L.map(el, { scrollWheelZoom: false, worldCopyJump: true, minZoom: 3, maxZoom: MAXZ, zoomSnap: 1, bounceAtZoomLimits: false });
      map.on('zoomend', function () { if (map.getZoom() > MAXZ) map.setZoom(MAXZ); });
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: MAXZ, minZoom: 3, className: 'tars2-tiles',
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      }).addTo(map);
      var color = getComputedStyle(document.documentElement).getPropertyValue('--primary').trim() || '#9fd0e3';
      var amber = getComputedStyle(document.documentElement).getPropertyValue('--amber').trim() || '#e0a857';
      var lines = [], max = 1;
      data.segments.forEach(function (s) { if (s[4] > max) max = s[4]; });
      // Each drive becomes a gentle arc (quadratic curve bowing off the straight
      // line in proportion to its length) so the map reads as travel, not geometry.
      function arc(a, b) {
        var dx = b[1] - a[1], dy = b[0] - a[0], len = Math.sqrt(dx * dx + dy * dy);
        if (len < 0.25) return [a, b];
        var mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
        var bow = Math.min(0.26 * len, 4), side = (dx >= 0) ? 1 : -1;
        var cx = mx + side * bow * (-dx / len), cy = my + side * bow * (dy / len);
        var pts = [], n = Math.max(8, Math.min(40, Math.round(len * 4)));
        for (var i = 0; i <= n; i++) {
          var t = i / n, u = 1 - t;
          pts.push([u * u * a[0] + 2 * u * t * cx + t * t * b[0], u * u * a[1] + 2 * u * t * cy + t * t * b[1]]);
        }
        return pts;
      }
      data.segments.forEach(function (s) {
        var hot = s[4] > 4, w = 1 + 2.5 * Math.log(s[4]) / Math.log(max || 2);
        var pts = arc([s[0], s[1]], [s[2], s[3]]);
        lines.push(L.polyline(pts, { color: hot ? amber : color, weight: w + 7, opacity: .10, interactive: false, smoothFactor: 0, lineCap: 'round' }));
        lines.push(L.polyline(pts, { color: hot ? amber : color, weight: w, opacity: hot ? .85 : .6, interactive: false, smoothFactor: 0, lineCap: 'round' }));
      });
      (data.sites || []).forEach(function (p) {
        lines.push(L.circleMarker([p[0], p[1]], { radius: 2 + Math.min(3, Math.sqrt(p[2]) / 1.4), color: '#101316', weight: 1, fillColor: amber, fillOpacity: .75, opacity: .9 })
          .bindTooltip(p[4] + ': ' + p[2] + ' Supercharger stop' + (p[2] === 1 ? '' : 's') + ', ' + p[3].toLocaleString() + ' kWh', { direction: 'top', opacity: .95 }));
      });
      var group = L.featureGroup(lines).addTo(map);
      map.fitBounds(group.getBounds(), { padding: [20, 20] });
      var btn = L.control({ position: 'topright' });
      btn.onAdd = function () {
        var d = L.DomUtil.create('div', 'leaflet-bar tars2-home');
        d.innerHTML = '<a href="#" title="Zoom to West Michigan" role="button" aria-label="Zoom to West Michigan">MI</a><a href="#" title="Show every drive" role="button" aria-label="Show every drive">All</a>';
        d.children[0].onclick = function (e) { e.preventDefault(); map.setView([43.6, -85.2], MAXZ); };
        d.children[1].onclick = function (e) { e.preventDefault(); map.fitBounds(group.getBounds(), { padding: [20, 20] }); };
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
