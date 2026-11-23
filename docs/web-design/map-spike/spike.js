// The map spike: the built 1941 map drawn in four projections, and a timing bench that pans
// and zooms it three ways. A plain script, not a module, so the page opens from the file system.
// Nothing here is loaded by the game.
(() => {
  'use strict';

  const MAP = window.SPIKE_MAP;
  const WORLD = window.SPIKE_WORLD;
  const NS = 'http://www.w3.org/2000/svg';
  const RAD = Math.PI / 180;
  const DEG = 180 / Math.PI;
  const [WEST, SOUTH, EAST, NORTH] = MAP.box;
  const MID_LON = (WEST + EAST) / 2;
  const MID_LAT = (NORTH + SOUTH) / 2;

  // --- projections: (lon, lat) in degrees to [x, y] with y down, in degree-sized units ---

  const COS_MID = Math.cos(MID_LAT * RAD);
  const today = (lon, lat) => [(lon - WEST) * COS_MID, NORTH - lat];

  const EE = { A1: 1.340264, A2: -0.081106, A3: 0.000893, A4: 0.003796, M: Math.sqrt(3) / 2 };
  function equalEarth(lon, lat) {
    const l = (lon - MID_LON) * RAD;
    const th = Math.asin(EE.M * Math.sin(lat * RAD));
    const t2 = th * th; const t6 = t2 * t2 * t2;
    const x = (l * Math.cos(th)) / (EE.M * (EE.A1 + 3 * EE.A2 * t2 + t6 * (7 * EE.A3 + 9 * EE.A4 * t2)));
    const y = th * (EE.A1 + EE.A2 * t2 + t6 * (EE.A3 + EE.A4 * t2));
    return [x * DEG, -y * DEG];
  }

  function naturalEarth(lon, lat) {
    const l = (lon - MID_LON) * RAD; const p = lat * RAD;
    const p2 = p * p; const p4 = p2 * p2;
    const x = l * (0.8707 - 0.131979 * p2 + p4 * (-0.013791 + p4 * (0.003971 * p2 - 0.001529 * p4)));
    const y = p * (1.007226 + p2 * (0.015085 + p4 * (-0.044475 + 0.028874 * p2 - 0.005916 * p4)));
    return [x * DEG, -y * DEG];
  }

  function miller(lon, lat) {
    const l = (lon - MID_LON) * RAD;
    return [l * DEG, -1.25 * Math.log(Math.tan(Math.PI / 4 + 0.4 * lat * RAD)) * DEG];
  }

  const PROJECTIONS = [
    { key: 'today', name: 'Today', note: `One cosine (of ${MID_LAT}°) squeezes the whole map; what the game draws now` },
    { key: 'equal-earth', name: 'Equal Earth', note: `Equal area; centred on ${MID_LON}° east` },
    { key: 'natural-earth', name: 'Natural Earth', note: `A compromise; centred on ${MID_LON}° east` },
    { key: 'miller', name: 'Miller', note: `Cylindrical, near-conformal; centred on ${MID_LON}° east` },
  ];
  const FORWARD = { today, 'equal-earth': equalEarth, 'natural-earth': naturalEarth, miller };

  // --- the map's geometry, projected once per projection ---

  const kinds = new Map(WORLD.areas.map((a) => [a.key, a.kind]));
  const regionOf = new Map(WORLD.areas.map((a) => [a.key, a.region]));

  /** The map's shared edges, grouped by the kind of border they are (as the game sorts them). */
  function borderEdges() {
    const users = new Map();
    for (const [key, area] of Object.entries(MAP.areas)) {
      for (const ring of area.rings) {
        for (let i = 1; i < ring.length; i += 1) {
          const [p, q] = [ring[i - 1], ring[i]];
          if (p === q) continue;
          const edge = p < q ? `${p} ${q}` : `${q} ${p}`;
          users.set(edge, [...(users.get(edge) ?? []).filter((u) => u !== key), key]);
        }
      }
    }
    const out = { land: [], coast: [], sea: [] };
    for (const [edge, keys] of users) {
      const [a, b = null] = [...keys].sort();
      if (!kinds.has(a)) continue;
      const both = b === null || !kinds.has(b) ? null : [kinds.get(a), kinds.get(b)];
      const kind = !both ? 'coast' : both.every((k) => k === 'land') ? 'land' : both.every((k) => k === 'sea') ? 'sea' : 'coast';
      out[kind].push(edge.split(' ').map(Number));
    }
    return out;
  }
  const EDGES = borderEdges();

  /** Every region and the regions under it, by key. */
  function subtree(key) {
    const out = new Set([key]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const r of WORLD.regions) if (r.parent && out.has(r.parent) && !out.has(r.key)) { out.add(r.key); grew = true; }
    }
    return out;
  }

  const r2 = (v) => Math.round(v * 100) / 100;
  const pt = ([x, y]) => `${r2(x)} ${r2(y)}`;

  function boxOf(points) {
    let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
    for (const [x, y] of points) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }

  /** The map box's outline as lon/lat points, a degree apart along each edge. */
  function outline() {
    const out = [];
    for (let lon = WEST; lon <= EAST; lon += 1) out.push([lon, NORTH]);
    for (let lat = NORTH; lat >= SOUTH; lat -= 1) out.push([EAST, lat]);
    for (let lon = EAST; lon >= WEST; lon -= 1) out.push([lon, SOUTH]);
    for (let lat = SOUTH; lat <= NORTH; lat += 1) out.push([WEST, lat]);
    return out;
  }

  /** Meridians every 30 degrees and parallels every 15, inside the map's box. */
  function graticule(fwd) {
    const lines = [];
    for (let lon = Math.ceil(WEST / 30) * 30; lon <= EAST; lon += 30) {
      const line = [];
      for (let lat = SOUTH; lat <= NORTH; lat += 1) line.push(fwd(lon, lat));
      lines.push(line);
    }
    for (let lat = Math.ceil(SOUTH / 15) * 15; lat <= NORTH; lat += 15) {
      const line = [];
      for (let lon = WEST; lon <= EAST; lon += 2) line.push(fwd(lon, lat));
      lines.push(line);
    }
    return lines.map((l) => `M${l.map(pt).join('L')}`).join('');
  }

  const FRAME_KEYS = [
    { key: '', name: 'The whole map' },
    { key: 'europe', name: 'Europe' },
    { key: 'pacific', name: WORLD.regions.find((r) => r.key === 'pacific')?.name ?? 'Pacific' },
  ];

  const geometryCache = new Map();
  /** The 1941 map in projection `key`: path data, label points and the three frames. */
  function geometry(key) {
    if (geometryCache.has(key)) return geometryCache.get(key);
    const fwd = FORWARD[key];
    const P = MAP.vertices.map(([lon, lat]) => fwd(lon, lat));
    // a straight edge in longitude and latitude is a curve in most projections: long edges are
    // cut into one-degree steps before projecting, or they are drawn as chords
    const between = (p, q) => {
      const [a, b] = [MAP.vertices[p], MAP.vertices[q]];
      const n = Math.ceil(Math.max(Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1])));
      const out = [];
      for (let s = 1; s < n; s += 1) out.push(fwd(a[0] + ((b[0] - a[0]) * s) / n, a[1] + ((b[1] - a[1]) * s) / n));
      return out;
    };
    const line = (idx) => idx.flatMap((i, n) => (n ? [...between(idx[n - 1], i), P[i]] : [P[i]])).map(pt).join('L');
    const ring = (r) => `M${line(r)}Z`;
    const areaKeys = WORLD.areas.map((a) => a.key).filter((k) => MAP.areas[k]);
    const sea = outline().map(([lon, lat]) => fwd(lon, lat));
    const frames = new Map();
    const whole = boxOf([...P, ...sea]);
    frames.set('', whole);
    for (const f of FRAME_KEYS.slice(1)) {
      const within = subtree(f.key);
      const pts = areaKeys.filter((k) => within.has(regionOf.get(k))).flatMap((k) => MAP.areas[k].rings.flat().map((i) => P[i]));
      frames.set(f.key, boxOf(pts));
    }
    const edgePath = (edges) => edges.map((e) => `M${line(e)}`).join('');
    const g = {
      key, P, frames, whole,
      sea: `M${sea.map(pt).join('L')}Z`,
      backdrop: MAP.backdrop.map(ring).join(''),
      land: areaKeys.filter((k) => kinds.get(k) === 'land').map((k) => MAP.areas[k].rings.map(ring).join('')),
      borders: { land: edgePath(EDGES.land), coast: edgePath(EDGES.coast), sea: edgePath(EDGES.sea) },
      graticule: graticule(fwd),
      labels: areaKeys.map((k) => {
        const [lon, lat] = MAP.areas[k].label;
        return { key: k, name: WORLD.areas.find((a) => a.key === k).name, kind: kinds.get(k), at: fwd(lon, lat) };
      }),
    };
    geometryCache.set(key, g);
    return g;
  }

  function el(tag, attrs = {}, ...kids) {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) n.setAttribute(k, String(v));
    for (const kid of kids.flat()) if (kid) n.append(kid);
    return n;
  }

  /** The land, borders and graticule of `g` as SVG children. */
  function landLayer(g) {
    return [
      el('path', { d: g.sea, class: 'sea' }),
      el('path', { d: g.graticule, class: 'grat' }),
      el('path', { d: g.backdrop, class: 'backdrop' }),
      el('path', { d: g.land.join(''), class: 'land' }),
      el('path', { d: g.borders.sea, class: 'b-sea' }),
      el('path', { d: g.borders.coast, class: 'b-coast' }),
      el('path', { d: g.borders.land, class: 'b-land' }),
    ];
  }

  // --- the proof page: four projections by three frames ---

  function proof(root) {
    const grid = document.createElement('div');
    grid.className = 'grid';
    for (const f of FRAME_KEYS) {
      const row = document.createElement('section');
      row.className = 'row';
      const h = document.createElement('h2');
      h.textContent = f.name;
      row.append(h);
      const cells = document.createElement('div');
      cells.className = 'cells';
      for (const p of PROJECTIONS) {
        const g = geometry(p.key);
        const r = g.frames.get(f.key);
        const pad = Math.max(r.w, r.h) * 0.02;
        const svg = el('svg', {
          viewBox: `${r2(r.x - pad)} ${r2(r.y - pad)} ${r2(r.w + 2 * pad)} ${r2(r.h + 2 * pad)}`,
          preserveAspectRatio: 'xMidYMid meet', role: 'img', 'aria-label': `${f.name} in ${p.name}`,
          'data-projection': p.key, 'data-frame': f.key || 'whole',
        }, landLayer(g),
        f.key ? null : FRAME_KEYS.slice(1).map((o) => {
          const b = g.frames.get(o.key);
          return el('rect', { x: r2(b.x), y: r2(b.y), width: r2(b.w), height: r2(b.h), class: 'frame-box' });
        }));
        svg.style.aspectRatio = `${r.w + 2 * pad} / ${r.h + 2 * pad}`;
        const fig = document.createElement('figure');
        const cap = document.createElement('figcaption');
        const name = document.createElement('strong');
        name.textContent = p.name;
        cap.append(name, ` ${p.note}`);
        fig.append(svg, cap);
        cells.append(fig);
      }
      row.append(cells);
      grid.append(row);
    }
    root.append(grid);
    window.spikeProof = { ready: true, panels: grid.querySelectorAll('svg').length };
  }

  // --- the bench: one map, panned and zoomed by a fixed path, three ways of drawing ---

  /** Where the view is at `t` (0 to 1 over the run): zoom between 1 and 8 twice, the middle on a loop. */
  function viewAt(t, rect) {
    const zoom = 2 ** (3 * (0.5 - 0.5 * Math.cos(2 * Math.PI * 2 * t)));
    const cx = rect.x + rect.w * (0.5 + 0.35 * Math.sin(2 * Math.PI * 3 * t));
    const cy = rect.y + rect.h * (0.5 + 0.3 * Math.sin(2 * Math.PI * 2 * t + 1));
    return { zoom, cx, cy };
  }

  /**
   * Pixels per map unit and the map point at the screen's middle, the window kept inside `rect`.
   * At zoom 1 the map covers the screen (a phone shows a slice of the whole map, as a map app does).
   */
  function place(view, rect, W, H) {
    const s = Math.max(W / (rect.w / view.zoom), H / (rect.h / view.zoom));
    const hw = W / (2 * s); const hh = H / (2 * s);
    const clamp = (v, lo, hi) => (lo > hi ? (lo + hi) / 2 : Math.min(Math.max(v, lo), hi));
    return { s, cx: clamp(view.cx, rect.x + hw, rect.x + rect.w - hw), cy: clamp(view.cy, rect.y + hh, rect.y + rect.h - hh) };
  }

  /** The marks drawn over the land: a counter and a name at each area's label point, sized in pixels. */
  function marksLayer(g) {
    return g.labels.map((l) => el('g', { class: 'px', 'data-x': r2(l.at[0]), 'data-y': r2(l.at[1]) },
      l.kind === 'land' ? el('rect', { x: -10, y: -22, width: 20, height: 14, rx: 2, class: 'mk' }) : null,
      el('text', { 'text-anchor': 'middle', dy: '0.35em', 'font-size': 12, class: 'lbl' }, l.name)));
  }

  function bench(root, method, projKey) {
    const g = geometry(projKey);
    const rect = g.frames.get('');
    const W = window.innerWidth; const H = window.innerHeight;
    root.classList.add('bench');
    let svg; let group = null; let canvas = null; let draw = null;
    const marks = marksLayer(g);
    if (method === 'transform') {
      group = el('g', {}, landLayer(g), marks);
      svg = el('svg', { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', class: 'stage' }, group);
    } else if (method === 'viewbox') {
      svg = el('svg', { preserveAspectRatio: 'none', class: 'stage' }, landLayer(g), marks);
    } else if (method === 'canvas') {
      canvas = document.createElement('canvas');
      canvas.className = 'stage';
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
      root.append(canvas);
      svg = el('svg', { preserveAspectRatio: 'none', class: 'stage over' }, marks);
      const css = getComputedStyle(document.documentElement);
      const tok = (n) => css.getPropertyValue(n).trim();
      const paths = {
        sea: new Path2D(g.sea), backdrop: new Path2D(g.backdrop), land: new Path2D(g.land.join('')),
        bland: new Path2D(g.borders.land), bcoast: new Path2D(g.borders.coast), bsea: new Path2D(g.borders.sea),
        grat: new Path2D(g.graticule),
      };
      const ctx = canvas.getContext('2d');
      draw = (p) => {
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.fillStyle = tok('--bg');
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        const k = dpr * p.s;
        ctx.setTransform(k, 0, 0, k, dpr * (W / 2 - p.cx * p.s), dpr * (H / 2 - p.cy * p.s));
        const px = 1 / p.s;
        ctx.fillStyle = tok('--chart-sea'); ctx.fill(paths.sea);
        ctx.strokeStyle = tok('--rule-strong'); ctx.lineWidth = 0.6 * px; ctx.setLineDash([]); ctx.stroke(paths.grat);
        ctx.globalAlpha = 0.45; ctx.fillStyle = tok('--chart-land'); ctx.fill(paths.backdrop, 'evenodd'); ctx.globalAlpha = 1;
        ctx.fill(paths.land, 'evenodd');
        ctx.lineJoin = 'round'; ctx.strokeStyle = tok('--chart-line');
        ctx.lineWidth = px; ctx.setLineDash([4 * px, 4 * px]); ctx.stroke(paths.bsea);
        ctx.setLineDash([]); ctx.lineWidth = 2 * px; ctx.stroke(paths.bcoast);
        ctx.lineWidth = 1.2 * px; ctx.stroke(paths.bland);
      };
    } else {
      throw new Error(`unknown method ${method}`);
    }
    root.append(svg);
    const pxGroups = marks;
    const apply = (p) => {
      const k = 1 / p.s;
      if (group) group.setAttribute('transform', `matrix(${p.s} 0 0 ${p.s} ${W / 2 - p.cx * p.s} ${H / 2 - p.cy * p.s})`);
      else svg.setAttribute('viewBox', `${p.cx - W * k / 2} ${p.cy - H * k / 2} ${W * k} ${H * k}`);
      for (const m of pxGroups) m.setAttribute('transform', `translate(${m.getAttribute('data-x')} ${m.getAttribute('data-y')}) scale(${k})`);
      if (draw) draw(p);
    };
    apply(place(viewAt(0, rect), rect, W, H));

    /** Pan and zoom for `ms`, after `warm` ms not counted; resolves with each frame's time. */
    function run(ms, warm = 1000) {
      return new Promise((resolve) => {
        const frames = []; const work = [];
        let t0 = null; let last = null;
        const step = (now) => {
          if (t0 === null) t0 = now;
          const el2 = now - t0;
          if (last !== null && el2 > warm) frames.push(now - last);
          last = now;
          if (el2 > warm + ms) { resolve({ frames, work }); return; }
          const a = performance.now();
          apply(place(viewAt((el2 % 10000) / 10000, rect), rect, W, H));
          if (el2 > warm) work.push(performance.now() - a);
          requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      });
    }
    window.spikeBench = { ready: true, method, projection: projKey, run, W, H, dpr: window.devicePixelRatio || 1 };
  }

  const q = new URLSearchParams(location.search);
  if (q.get('bench')) {
    document.querySelector('main').hidden = true;
    bench(document.getElementById('spike-bench-root'), q.get('bench'), q.get('projection') || 'equal-earth');
  } else {
    proof(document.getElementById('spike'));
  }
})();
