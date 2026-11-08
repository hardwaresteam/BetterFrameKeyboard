// BetterFrame: adds VR, BetterFrame and Plugins pages to the top of Steam's own Settings, built from Steam's own
// toggles, sliders and dropdowns, so they look and work like every other Steam settings page.
// Lives in Steam's interface page; the BetterFrame service hands it the values and carries out the changes.
// If anything goes wrong it stops adding pages and Steam's own settings carry on untouched.
(() => {
  const VERSION = 11;
  const old = window.__bfSteam;
  if (old && old.version >= VERSION) return 'already ' + old.version;
  if (old) {   // an older (or switched off) copy: take it out first
    if (old.undo && old.version) { try { old.undo(); } catch (e) {} }
    window.__bfSteam = null;
  }
  const seen = new Set(), found = {src: '', sep: false};
  const install = () => {
  const S = {version: VERSION, on: false, errors: 0, lastError: '', pages: [], merge: {}, top: [], leftover: [], fold: true, keys: [], vals: {}, writes: {}, wseq: 0, wat: {},
                                subs: new Set(), injected: 0, found: {}};
  let req = null;
  try { window.webpackChunksteamui.push([[Symbol('bf-steam')], {}, r => { req = r; }]); } catch (e) {}
  if (!req) return 'no webpack';

  // ---- Steam's own building blocks, found by how Steam's settings pages use them
  // one pass over Steam's code, and only over parts not looked at before (Steam adds code as it loads)
  for (const id of Object.keys(req.m)) {
    if (seen.has(id)) continue;
    seen.add(id);
    let s = ''; try { s = req.m[id].toString(); } catch (e) { continue; }
    if (!found.src && s.includes('#Settings_Page_Internet') && s.includes('route:') && s.includes('content:')) found.src = s;
    // Steam's side list can draw a dividing line between groups of pages (a "separator" entry): check it really can
    if (!found.sep && s.includes('"separator"') && s.includes('identifier') && /"separator"===\w|\w==="separator"/.test(s)) found.sep = true;
  }
  const src = found.src;
  if (!src) return 'no settings module';
  S.sep = found.sep;
  const vars = {};
  let m;
  const re1 = /[,{;\s(](\w{1,3})=t\((\d+)\)/g;
  while ((m = re1.exec(src))) vars[m[1]] = m[2];
  const re2 = /[,{;\s(](\w{1,3})=t\.n\((\w{1,3})\)/g;
  while ((m = re2.exec(src))) if (vars[m[2]]) vars[m[1]] = vars[m[2]];
  const mod = v => { try { return req(vars[v]); } catch (e) { return null; } };
  let JSX = null, React = null;
  for (const v of Object.keys(vars)) {
    const x = mod(v);
    if (!x) continue;
    if (!JSX && typeof x.jsx === 'function' && typeof x.jsxs === 'function') JSX = x;
    if (!React && typeof x.useState === 'function' && typeof x.useEffect === 'function') React = x;
  }
  if (!JSX || !React) return 'no react';
  const uses = {};
  const re3 = /\(0,\w+\.jsxs?\)\((\w{1,3})\.(\w{1,4}),\{([^{}]{0,260})/g;
  while ((m = re3.exec(src))) {
    const key = m[1] + '.' + m[2];
    const u = uses[key] = uses[key] || {count: 0, props: {}};
    u.count++;
    for (const p of (m[3].match(/(\w+):/g) || []).map(x => x.slice(0, -1))) u.props[p] = 1;
  }
  const pick = (need, avoid) => {
    let best = null;
    for (const [k, u] of Object.entries(uses)) {
      if (need.every(p => u.props[p]) && !(avoid || []).some(p => u.props[p]) && (!best || u.count > best[1].count)) best = [k, u];
    }
    if (!best) return null;
    const [v, ex] = best[0].split('.');
    const x = mod(v);
    S.found[need.join('+')] = best[0];
    return x ? x[ex] : null;
  };
  const C = {
    Toggle: pick(['checked', 'onChange', 'label']),
    Dropdown: pick(['rgOptions', 'selectedOption', 'onChange', 'label']),
    Slider: pick(['min', 'max', 'value', 'onChange', 'label']),
    Section: pick(['label', 'children'], ['onClick', 'setting', 'checked', 'value', 'rgOptions', 'childrenContainerWidth', 'feature', 'disabled']),
    Button: pick(['label', 'onClick', 'children'], ['setting', 'checked']),
  };
  if (!C.Toggle || !C.Dropdown || !C.Slider || !C.Section) return 'missing blocks ' + JSON.stringify(S.found);
  const h = JSX.jsx, Frag = JSX.Fragment;

  // ---- the pages
  const ICONS = {
    vr: 'M4 11h28a3 3 0 0 1 3 3v9a3 3 0 0 1-3 3h-8l-3-4h-6l-3 4H4a3 3 0 0 1-3-3v-9a3 3 0 0 1 3-3zm6 5a3 3 0 1 0 0 6 3 3 0 0 0 0-6zm16 0a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
    playarea: 'M5 9l13-5 13 5v18l-13 5-13-5V9zm4 3v12l9 3.5 9-3.5V12l-9-3.5L9 12z',
    dashboard: 'M4 6h12v10H4V6zm16 0h12v10H20V6zM4 20h12v10H4V20zm16 0h12v10H20V20z',
    controller: 'M10 9h16a8 8 0 0 1 8 8v3a7 7 0 0 1-12.5 4.3L20 22h-4l-1.5 2.3A7 7 0 0 1 2 20v-3a8 8 0 0 1 8-8zm0 5v3H7v3h3v3h3v-3h3v-3h-3v-3h-3zm16 1a2 2 0 1 0 0 4 2 2 0 0 0 0-4z',
    video: 'M3 7h30a2 2 0 0 1 2 2v15a2 2 0 0 1-2 2H21v3h5v3H10v-3h5v-3H3a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2zm2 4v11h26V11H5z',
    audio: 'M4 13h6l9-7v24l-9-7H4V13zm20-1a8 8 0 0 1 0 12l-2-2a5 5 0 0 0 0-8l2-2zm4-4a13 13 0 0 1 0 20l-2-2a10 10 0 0 0 0-16l2-2z',
    power: 'M16.5 3h3v14h-3V3zM9.5 8l2 2.2A10 10 0 1 0 24.5 10.2l2-2.2A13 13 0 1 1 9.5 8z',
    bf: 'M6 5h24a2 2 0 0 1 2 2v22a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zm3 5v16h18V10H9z',
    plugins: 'M14 3a4 4 0 0 1 4 4v1h7a2 2 0 0 1 2 2v7h1a4 4 0 0 1 0 8h-1v6a2 2 0 0 1-2 2h-6v-1a4 4 0 0 0-8 0v1H5a2 2 0 0 1-2-2v-7h1a4 4 0 0 0 0-8H3v-6a2 2 0 0 1 2-2h7V7a4 4 0 0 1 2-4z',
  };
  const icon = k => h('svg', {viewBox: '0 0 36 36', fill: 'none', xmlns: 'http://www.w3.org/2000/svg',
                              children: h('path', {fill: 'currentColor', d: ICONS[k] || ICONS.vr})});
  const useVals = () => {
    const [, set] = React.useState(0);
    React.useEffect(() => { const f = () => set(x => x + 1); S.subs.add(f); return () => { S.subs.delete(f); }; }, []);
    return S.vals;
  };
  S.change = (id, value) => {   // shown straight away; the service makes the real change and reports back
    S.vals[id] = value;
    S.writes[id] = value;
    S.wat[id] = ++S.wseq;   // (kept until the service says it saved it: a change is never lost on the way)
    S.subs.forEach(f => { try { f(); } catch (e) {} });
  };
  const row = (d, vals) => {
    const v = vals[d.id];
    if (v === undefined || v === null) return null;
    if (d.kind === 'switch') return h(C.Toggle, {key: d.id, label: d.label, description: d.desc, checked: !!v, onChange: c => S.change(d.id, !!c)});
    if (d.kind === 'choice') {
      const opts = d.options.map(o => ({label: String(o[1]), data: o[0]}));
      return h(C.Dropdown, {key: d.id, label: d.label, description: d.desc, rgOptions: opts,
                            selectedOption: (opts.find(o => String(o.data) === String(v)) || opts[0]).data, onChange: o => S.change(d.id, o.data)});
    }
    if (d.kind === 'button') {   // a button that asks once more before it does anything
      const sure = v === 'confirm', done = v === 'go';
      // (the button keeps about the same width throughout: a long label made it jump wider when clicked)
      const label = done ? (d.button || d.label) : (sure ? (d.confirm || 'Sure?') : (d.button || d.label));
      const click = () => { if (done) return; if (sure) S.change(d.id, 'go'); else { S.change(d.id, 'confirm');
        setTimeout(() => { if (S.vals[d.id] === 'confirm') S.change(d.id, 'idle'); }, 5000); } };
      if (C.Button) return h(C.Button, {key: d.id, label: d.label, description: d.desc, onClick: click, children: label});
      return h(C.Toggle, {key: d.id, label: d.label + ' (' + label + ')', description: d.desc, checked: sure || done,
                          onChange: click});
    }
    if (d.kind === 'slider') return h(C.Slider, {key: d.id, label: d.label, description: d.desc, min: d.min, max: d.max, step: d.step || 1,
                                                 value: Number(v), showValue: true, valueSuffix: d.unit || '', onChange: n => S.change(d.id, n)});
    return null;
  };
  const sections = (secs, vals) => secs.map(sec => {
    const rows = sec.rows.map(d => row(d, vals)).filter(Boolean);
    return rows.length ? h(C.Section, {key: sec.title, label: sec.title, children: rows}) : null;
  }).filter(Boolean);
  const Page = props => {
    const vals = useVals();
    const page = S.pages.find(p => p.id === props.id);
    if (!page) return h('div', {children: 'Loading…'});
    // the VR page also takes any VR section whose Steam page wasn't found
    const secs = page === S.pages[0] ? page.sections.concat(S.leftover) : page.sections;
    return h(Frag, {children: sections(secs, vals)});
  };
  // VR sections inside one of Steam's pages: read fresh each time, so an updated list shows without restarting Steam
  const Extra = props => h(Frag, {children: sections(S.merge[props.mk] || [], useVals())});
  const keyOf = p => p && p.route ? String(p.route).replace(/\/+$/, '').split('/').pop().toLowerCase() : '';
  // Steam's pages in an order that groups related things; anything not listed keeps its place after these
  const ORDER = ['system', 'display', 'audio', 'internet', 'bluetooth', 'controller', 'keyboard', 'notifications', 'friends', 'power',
                 'storage', 'downloads', 'library', 'home', 'ingame', 'gamerecording', 'remoteplay', 'broadcast', 'music',
                 'customization', 'accessibility', 'family', 'security', 'account'];
  // small Steam pages folded into a related one (its settings shown under their own heading there)
  const FOLD = [
    {from: ['bluetooth'], into: ['internet'], title: (a, b) => a + ' & ' + b},
    {from: ['keyboard'], into: ['controller', 'controllers'], title: (a, b) => a + ' & ' + b},
    {from: ['home'], into: ['library'], title: (a, b) => a + ' & ' + b},
    {from: ['downloads'], into: ['storage'], title: (a, b) => a + ' & ' + b},
  ];
  const OURS = Symbol('bf-page');
  const ours = template => S.pages.map(p => {
    const base = template && template.route ? template.route.replace(/\/[^/]*$/, '') : null;
    return {identifier: 'bf-' + p.id, title: p.title, icon: icon(p.icon), visible: true, [OURS]: true,
            route: base ? base + '/betterframe-' + p.id : undefined, content: h(Page, {id: p.id})};
  });
  const isPage = x => x && typeof x === 'object' && 'content' in x && 'title' in x;
  const isOurs = x => x && typeof x === 'object' && (x[OURS] || String(x.identifier || '').startsWith('bf-'));

  // ---- putting the pages in: whenever Steam hands its settings page list to the settings dialog
  S.inject = props => {
    for (const k in props) {
      const v = props[k];
      if (typeof v !== 'object' || v === null || !Array.isArray(v) || v.length < 5 || v.__bf || v.filter(isPage).length < 4) continue;
      // only Steam's Settings list: its pages live under a settings address (the library and others have lists too)
      if (v.filter(x => isPage(x) && /settings/i.test(String(x.route || ''))).length < 4) continue;
      if (v.filter(x => isPage(x) && ORDER.includes(keyOf(x))).length < 3) continue;
      if (v.some(isOurs) || v.some(x => x && x.__bfx)) return null;   // already ours (Steam passed our list on, maybe copied): never twice
      const tpl = v.find(x => isPage(x) && x.route);
      S.keys = v.filter(isPage).map(keyOf);
      // (a page is matched by its address, or else by its title: "Keyboard")
      const titleOf = p => typeof p.title === 'string' ? p.title.trim().toLowerCase() : '';
      const keys = new Set(S.keys.concat(v.filter(isPage).map(titleOf)));
      S.leftover = [];
      for (const [mk, secs] of Object.entries(S.merge)) if (!keys.has(mk)) S.leftover.push(...secs);
      let steam = v.filter(isPage).map(p => {
        const mk = S.merge[keyOf(p)] ? keyOf(p) : titleOf(p);
        const extra = S.merge[mk];
        if (!extra) return p;
        const ex = h(Extra, {key: 'bf', mk});
        // our sections at the top of that page (Steam's own rows then under their own heading, so they don't look like ours),
        // or under Steam's own ones
        return Object.assign({}, p, {__bfx: true, content: h(Frag, {children: S.top.includes(mk)
          ? [ex, h(C.Section, {key: 'steam', label: 'Steam ' + (typeof p.title === 'string' ? p.title : 'settings'), children: p.content})]
          : [p.content, ex]})});
      });
      if (S.fold) for (const f of FOLD) {
        const child = steam.find(p => f.from.includes(keyOf(p)));
        const parent = steam.find(p => f.into.includes(keyOf(p)));
        if (!child || !parent || child.visible === false || parent.visible === false) continue;
        const merged = Object.assign({}, parent, {
          title: typeof parent.title === 'string' && typeof child.title === 'string' ? f.title(parent.title, child.title) : parent.title,
          content: h(Frag, {children: [h(Frag, {key: 'a', children: parent.content}),
                                       h(C.Section, {key: 'b', label: child.title, children: child.content})]})});
        steam = steam.filter(p => p !== child).map(p => p === parent ? merged : p);
      }
      const rank = p => { const i = ORDER.indexOf(keyOf(p)); return i < 0 ? 900 + steam.indexOf(p) : i; };
      steam.sort((a, b) => rank(a) - rank(b));
      const nv = S.pages.length ? [...ours(tpl), ...(S.sep ? ['separator'] : []), ...steam] : steam;
      nv.__bf = true;
      S.injected++;
      return Object.assign({}, props, {[k]: nv});
    }
    return null;
  };
  // Steam builds every bit of its interface through these two functions, so this must cost next to nothing:
  // once the Settings list has been found, only that one component is ever looked at again
  S.hit = null;
  const wrap = orig => function (type, props, key) {
    if (type === S.hit || (S.hit === null && S.on)) {
      if (S.on && props && typeof props === 'object' && S.errors < 5 && (S.pages.length || Object.keys(S.merge).length)) {
        try {
          const p2 = S.inject(props);
          if (p2) { S.hit = type; return orig(type, p2, key); }
        } catch (e) { S.errors++; S.lastError = '' + e; }
      }
    }
    return orig(type, props, key);
  };
  S.orig = {jsx: JSX.jsx, jsxs: JSX.jsxs};
  JSX.jsx = wrap(S.orig.jsx);
  JSX.jsxs = wrap(S.orig.jsxs);
  S.undo = () => { S.on = false; S.version = 0; S.hit = null; JSX.jsx = S.orig.jsx; JSX.jsxs = S.orig.jsxs; return 'removed'; };

  // ---- talking to the BetterFrame service
  S.update = data => {   // the pages, and every value now
    if (data.pages) S.pages = data.pages;
    if (data.merge) S.merge = data.merge;
    if (data.top) S.top = data.top;
    if ('fold' in data) S.fold = !!data.fold;
    if (data.vals) for (const [k, v] of Object.entries(data.vals)) if (!(k in S.writes)) S.vals[k] = v;
    S.subs.forEach(f => { try { f(); } catch (e) {} });
    return 'ok';
  };
  // changes waiting to be saved: handed over, and only let go once the service confirms it saved them (if an answer
  // got lost on the way, the next look simply hands them over again)
  S.take = () => ({seq: S.wseq, w: Object.assign({}, S.writes)});
  S.ack = seq => { for (const id of Object.keys(S.writes)) if ((S.wat[id] || 0) <= seq) { delete S.writes[id]; delete S.wat[id]; } return 'ok'; };
  window.__bfSteam = S;   // only once everything is in place
  return 'installed ' + VERSION + ' ' + JSON.stringify(S.found);
  };
  const res = install();
  if (res === 'no settings module' && window.webpackChunksteamui && !window.__bfSteamWait) {
    // Steam loads its settings code the first time Settings opens: try again as soon as more of its code arrives
    const arr = window.webpackChunksteamui, op = arr.push;
    let busy = false;
    window.__bfSteamWait = true;
    arr.push = function () {
      const r = op.apply(this, arguments);
      if (!busy) setTimeout(() => {
        if (busy || window.__bfSteam) return;
        busy = true;
        try { if (String(install()).startsWith('installed')) { arr.push = op; window.__bfSteamWait = false; } } catch (e) {}
        busy = false;
      }, 0);
      return r;
    };
    return 'waiting for Steam settings';
  }
  return res;
})()
