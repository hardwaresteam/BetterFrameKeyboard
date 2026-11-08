// BetterFrame Keyboard: a VR keyboard for WebXR (Chromium XR on Steam Frame).
// Flat keys on a panel, typed with either laser (light trigger) or by touching them with the controller tips.
// Live dictation: words appear while you talk. Falls back to mouse on a flat screen.
import * as THREE from 'three';

const $ = (id) => document.getElementById(id);

/* ------------------------------------------------------------------ state */
const S = {
  text: '', partial: '', hist: [], sel: false, clip: '', shift: false, caps: false, lastShift: 0,
  layer: 'abc', layout: 'compact', speak: true, live: false,
  curve: 10, size: 'm', sounds: true, rate: 1, touch: true, sent: [], status: ''
};
const PREF_KEYS = ['layout', 'speak', 'curve', 'size', 'sounds', 'rate', 'touch'];
try { const p = JSON.parse(localStorage.getItem('bf-kb3d-v4') || '{}'); PREF_KEYS.forEach((k) => { if (p[k] !== undefined) S[k] = p[k]; }); } catch (e) {}
function savePrefs() { try { const p = {}; PREF_KEYS.forEach((k) => { p[k] = S[k]; }); localStorage.setItem('bf-kb3d-v4', JSON.stringify(p)); } catch (e) {} }

const helper = { stt: false, tts: false, model: '' };
const EMOJI = ['😂','😭','😊','😍','🥺','😎','🤔','😅','👍','👎','🙏','👏','🔥','💯','❤️','💀','🎮','🏆','⭐','✨','😴','🤝','👀','🎉','😡','🤯','😬','🫡','✅','❌'];

/* ------------------------------------------------------------ key layouts */
const K = (label, w, o = {}) => ({ label, w, ...o });
const letters = (s) => s.split('').map((c) => K(c, 1, { ch: c, char: true }));
const sym = (pairs) => pairs.map((p) => K(p[0], 1, { sym: p, char: true }));
const chars = (list, w = 1.5) => list.map((c) => K(c, w, { ins: c, char: true }));
const SMILEY = { icon: 'smiley' };

function abcRows(full) {
  if (!full) return [ // big keys: 11 keys across, like a phone keyboard
    { keys: '1234567890'.split('').map((c) => K(c, 1, { ins: c, char: true })).concat([K('Back', 1, { mod: true, small: true, act: 'back' })]) },
    { keys: letters('qwertyuiop').concat(sym([['\'','"']])) },
    { keys: [K('', 0.5, { spacer: true })].concat(letters('asdfghjkl')).concat([K('Enter', 1.5, { go: true, small: true, act: 'enter' })]) },
    { keys: [K('Shift', 1, { mod: true, small: true, act: 'shift' })].concat(letters('zxcvbnm')).concat(sym([[',',';'],['.',':'],['?','!']])) },
    { keys: [K('.?123', 2, { mod: true, small: true, act: 'l123' }), K('', 1.2, { mod: true, act: 'emoji', ...SMILEY, aria: 'Emoji' }), K('', 7.8, { act: 'space', aria: 'Space' })] }
  ];
  const rows = [];
  if (full) rows.push({ frow: true, keys: [K('Esc', 1, { mod: true, small: true, act: 'esc' })].concat([1,2,3,4,5,6,7,8,9,10,11,12].map((n) => K('F' + n, 1, { mod: true, small: true, act: 'fkey' }))).concat([K('', 2, { mod: true, act: 'emoji', ...SMILEY, aria: 'Emoji' })]) });
  rows.push({ keys: sym([['`','~'],['1','!'],['2','@'],['3','#'],['4','$'],['5','%'],['6','^'],['7','&'],['8','*'],['9','('],['0',')'],['-','_'],['=','+']]).concat([K('Back', 2, { mod: true, small: true, act: 'back' })]) });
  rows.push({ keys: [K('Tab', 1.5, { mod: true, small: true, act: 'tab' })].concat(letters('qwertyuiop')).concat(sym([['[','{'],[']','}']])).concat([K('\\', 1.5, { sym: ['\\','|'], char: true })]) });
  rows.push({ keys: [K('Caps', 1.75, { mod: true, small: true, act: 'caps' })].concat(letters('asdfghjkl')).concat(sym([[';',':'],['\'','"']])).concat([K('Enter', 2.25, { go: true, small: true, act: 'enter' })]) });
  rows.push({ keys: [K('Shift', 2.25, { mod: true, small: true, act: 'shift' })].concat(letters('zxcvbnm')).concat(sym([[',','<'],['.','>'],['/','?']])).concat([K('Shift', 2.75, { mod: true, small: true, act: 'shift' })]) });
  if (full) rows.push({ keys: [K('.?123', 2, { mod: true, small: true, act: 'l123' }), K('Ctrl', 1.4, { mod: true, small: true }), K('Alt', 1.4, { mod: true, small: true }), K('', 7.4, { act: 'space', aria: 'Space' }), K('Alt', 1.4, { mod: true, small: true }), K('Ctrl', 1.4, { mod: true, small: true })] });
  return rows;
}
function layerRows() {
  const full = S.layout !== 'compact';
  if (S.layer === 'abc') return abcRows(full);
  const cw = full ? 1.5 : 1.1, f = full ? 1 : 11 / 15;
  const bottom = [K('ABC', 2 * f, { mod: true, small: true, act: 'abc' }), K('', 1.5 * f, { mod: true, act: 'emoji', ...SMILEY, aria: 'Emoji' }), K('', 8 * f, { act: 'space', aria: 'Space' }), K('Enter', 3.5 * f, { go: true, small: true, act: 'enter' })];
  if (S.layer === '123') return [
    { keys: chars(['1','2','3','4','5','6','7','8','9','0'], cw) },
    { keys: chars(['#','@','$','&','*','(',')','-','_','/'], cw) },
    { keys: [K('#+=', 2.25 * f, { mod: true, small: true, act: 'lsym' })].concat(chars(['!','?','.',',','\'','"',':'], cw)).concat([K('Back', 2.25 * f, { mod: true, small: true, act: 'back' })]) },
    { keys: bottom }];
  if (S.layer === 'sym') return [
    { keys: chars(['[',']','{','}','%','^','+','=','<','>'], cw) },
    { keys: chars(['\\','|','~','`',';','\u20AC','\u00A3','\u00A5','\u2022','\u00B0'], cw) },
    { keys: [K('123', 2.25 * f, { mod: true, small: true, act: 'l123' })].concat(chars(['\u00A9','\u00AE','\u2122','\u00A7','\u2026','\u00BF','\u00A1'], cw)).concat([K('Back', 2.25 * f, { mod: true, small: true, act: 'back' })]) },
    { keys: bottom }];
  const rows = [];
  for (let i = 0; i < EMOJI.length; i += 10) rows.push({ keys: EMOJI.slice(i, i + 10).map((e) => K(e, cw, { ins: e, char: true, emoji: true })) });
  rows.push({ keys: [K('ABC', 2 * f, { mod: true, small: true, act: 'abc' }), K('.?123', 2 * f, { mod: true, small: true, act: 'l123' }), K('', 6 * f, { act: 'space', aria: 'Space' }), K('Back', 2 * f, { mod: true, small: true, act: 'back' }), K('Enter', 3 * f, { go: true, small: true, act: 'enter' })] });
  return rows;
}
function touchBar() {
  return [
    K('Undo', 1.4, { act: 'undo', bar: true }), K('Cut', 1.1, { act: 'cut', bar: true }), K('Copy', 1.3, { act: 'copy', bar: true }), K('Paste', 1.4, { act: 'paste', bar: true }), K('Select all', 2, { act: 'selall', bar: true }),
    K('', 0.4, { spacer: true }),
    K(S.speak ? 'Speak: on' : 'Speak: off', 2, { act: 'speak', bar: true, on: S.speak }),
    K(S.live ? '\u25CF Listening' : 'Mic', 2, { act: 'mic', bar: true, rec: S.live }),
    K('', 0.4, { spacer: true }),
    K('Full', 1.1, { act: 'lay-full', bar: true, on: S.layout === 'full' }), K('Big keys', 1.8, { act: 'lay-compact', bar: true, on: S.layout === 'compact' }), K('Split', 1.2, { act: 'lay-split', bar: true, on: S.layout === 'split' }),
    K('', 0.4, { spacer: true }),
    K('Move here', 2, { act: 'recenter', bar: true })
  ];
}

/* ---------------------------------------------------------------- three */
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.xr.enabled = true;
renderer.xr.setReferenceSpaceType('local-floor');
try { renderer.xr.setFramebufferScaleFactor(1.75); renderer.xr.setFoveation(0); } catch (e) {} // sharper image in the headset
const ANISO = Math.min(8, renderer.capabilities && renderer.capabilities.getMaxAnisotropy ? renderer.capabilities.getMaxAnisotropy() : 4);
$('stage').appendChild(renderer.domElement);

const scene = new THREE.Scene();
const BG = new THREE.Color(0x070b12);
scene.background = BG;
const camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.01, 50);
camera.position.set(0, 1.55, 0.25);
camera.lookAt(0, 1.2, -0.55);
const grid = new THREE.GridHelper(24, 48, 0x22406e, 0x14243c); grid.material.transparent = true; grid.material.opacity = 0.5; scene.add(grid);

const root = new THREE.Group(); root.position.set(0, 1.2, -0.55); scene.add(root);
const kb = new THREE.Group(); kb.rotation.x = -0.42; root.add(kb);

/* ---------------------------------------------------------- key drawing */
const FONT = '"Noto Sans","DejaVu Sans",system-ui,sans-serif';
const EMOJI_FONT = '"Noto Color Emoji","Apple Color Emoji","Segoe UI Emoji",sans-serif';
const PAL = { key: '#2A3745', mod: '#1D2631', go: '#1A8FE8', bar: '#18212B', on: '#1A8FE8', rec: '#D9454A', glow: '#8FCBFF' };
function roundRect(g, x, y, w, h, r) { r = Math.min(r, w / 2, h / 2); g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }
function drawSmiley(g, cx, cy, r) {
  g.strokeStyle = '#FFFFFF'; g.fillStyle = '#FFFFFF'; g.lineWidth = r * 0.16; g.lineCap = 'round';
  g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.stroke();
  g.beginPath(); g.arc(cx - r * 0.36, cy - r * 0.22, r * 0.12, 0, Math.PI * 2); g.fill();
  g.beginPath(); g.arc(cx + r * 0.36, cy - r * 0.22, r * 0.12, 0, Math.PI * 2); g.fill();
  g.beginPath(); g.arc(cx, cy + r * 0.05, r * 0.5, Math.PI * 0.18, Math.PI * 0.82); g.stroke();
}
function keyFill(k) {
  if (k.rec) return PAL.rec;
  if (k.bar) return k.on ? PAL.on : PAL.bar;
  if (k.go) return PAL.go;
  if ((k.act === 'shift' && S.shift) || (k.act === 'caps' && S.caps)) return PAL.on;
  return k.mod ? PAL.mod : PAL.key;
}
function drawKey(m) {
  const d = m.userData, k = d.key, c = d.canvas, g = c.getContext('2d');
  const W = c.width, H = c.height, pad = 6;
  g.clearRect(0, 0, W, H);
  roundRect(g, pad, pad, W - pad * 2, H - pad * 2, H * 0.2);
  g.fillStyle = keyFill(k); g.fill();
  if (d.hot) { g.fillStyle = 'rgba(255,255,255,0.14)'; g.fill(); g.lineWidth = Math.max(2, H * 0.022); g.strokeStyle = PAL.glow; g.stroke(); }
  if (d.down) { g.fillStyle = 'rgba(0,0,0,0.28)'; g.fill(); }
  g.textBaseline = 'middle'; g.fillStyle = '#FFFFFF';
  const shown = d.shown;
  if (k.icon === 'smiley') drawSmiley(g, W / 2, H / 2, H * 0.2);
  else if (k.emoji) { g.font = Math.round(H * 0.42) + 'px ' + EMOJI_FONT; g.textAlign = 'center'; g.fillText(shown, W / 2, H * 0.54); }
  else if (k.bar) { g.font = '600 ' + Math.round(H * 0.38) + 'px ' + FONT; g.textAlign = 'center'; g.fillText(shown, W / 2, H * 0.52); }
  else if (k.small) { g.font = '600 ' + Math.round(H * 0.24) + 'px ' + FONT; g.textAlign = 'left'; g.fillText(shown, H * 0.22, H * 0.52); }
  else {
    if (d.sub) { g.font = '600 ' + Math.round(H * 0.18) + 'px ' + FONT; g.fillStyle = '#8E99A6'; g.textAlign = 'center'; g.fillText(d.sub, W / 2, H * 0.27); g.fillStyle = '#FFFFFF'; }
    g.font = '500 ' + Math.round(H * (d.sub ? 0.3 : 0.34)) + 'px ' + FONT; g.textAlign = 'center'; g.fillText(shown, W / 2, d.sub ? H * 0.62 : H * 0.53);
  }
  d.tex.needsUpdate = true;
}

/* ------------------------------------------------------------- build keys */
// key pitch in metres. Full fits 15 keys across, Compact (big keys) 11.
const SIZES = { s: { px: 0.057, py: 0.05, cpx: 0.074, cpy: 0.058 }, m: { px: 0.064, py: 0.056, cpx: 0.084, cpy: 0.064 }, l: { px: 0.071, py: 0.062, cpx: 0.094, cpy: 0.07 } };
const hitMat = new THREE.MeshBasicMaterial({ visible: false });
let keys = [], hits = [], handle = null, backing = null;
let kbTopLocal = 0.1;
let R = Infinity;

function disposeTree(g) {
  g.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material && o.material !== hitMat) { if (o.material.map) o.material.map.dispose(); o.material.dispose(); }
  });
  while (g.children.length) g.remove(g.children[0]);
}
function curvePos(x) { if (!isFinite(R)) return { x, z: 0, ry: 0 }; const a = x / R; return { x: R * Math.sin(a), z: R * (1 - Math.cos(a)), ry: -a }; }
function bendGeometry(geo) { // wrap a flat plane around the same cylinder as the keys
  if (!isFinite(R)) return geo;
  const p = geo.attributes.position;
  for (let i = 0; i < p.count; i++) { const c = curvePos(p.getX(i)); p.setX(i, c.x); p.setZ(i, p.getZ(i) + c.z); }
  p.needsUpdate = true; geo.computeBoundingSphere(); return geo;
}

function buildKeyboard() {
  disposeTree(kb); keys = []; hits = [];
  const Z = SIZES[S.size] || SIZES.m, bigKeys = S.layout === 'compact', PX = bigKeys ? Z.cpx : Z.px, PY = bigKeys ? Z.cpy : Z.py, gap = PX * 0.1;
  const kh = PY - gap;
  R = S.curve <= 0 ? Infinity : 0.7 + (40 - S.curve) / 40 * 2.2;
  const split = S.layout === 'split';
  const full = S.layout !== 'compact';
  const unitsW = (r) => r.keys.reduce((a, k) => a + k.w, 0);

  // Row positions come from the letter layout, so every page lines up with the bottom (space bar) row
  const ref = abcRows(full);
  const rowY = []; let yy = -PY / 2;
  ref.forEach((r) => { rowY.push(yy); yy -= PY + (r.frow ? gap : 0); });
  const rows = layerRows();
  const offset = Math.max(0, ref.length - rows.length);
  const fullW = (bigKeys ? 11 : 15) * PX - gap;

  let blocks;
  if (split) {
    const L = [], Rr = [];
    rows.forEach((r) => { const tot = unitsW(r); let acc = 0; const a = [], b = []; r.keys.forEach((k) => { (acc + k.w / 2 < tot / 2 ? a : b).push(k); acc += k.w; }); L.push({ keys: a }); Rr.push({ keys: b }); });
    blocks = [{ rows: L, side: -1 }, { rows: Rr, side: 1 }];
  } else blocks = [{ rows, side: 0 }];

  const splitGap = 0.14;
  blocks.forEach((b) => {
    const grp = new THREE.Group();
    const bw = Math.max.apply(null, b.rows.map((r) => unitsW(r) * PX - gap));
    if (split) {
      const pivot = new THREE.Group(); pivot.position.x = b.side * splitGap / 2; kb.add(pivot);
      grp.position.x = b.side * bw / 2; pivot.add(grp);
      pivot.rotation.y = -b.side * 0.26; pivot.rotation.z = -b.side * 0.05;
      const bg = new THREE.Mesh(new THREE.PlaneGeometry(bw + 0.03, ref.length * PY + 0.03), panelMat());
      bg.position.set(0, (rowY[0] + rowY[rowY.length - 1]) / 2, -0.004); grp.add(bg);
    } else kb.add(grp);
    b.rows.forEach((r, i) => {
      const y = rowY[i + offset];
      const rw = unitsW(r) * PX - gap;
      let x = -rw / 2;
      r.keys.forEach((k) => { const w = k.w * PX - gap; if (!k.spacer) addKey(grp, k, x + w / 2, y, w, kh, k.w * PX, PY, split); x += k.w * PX; });
    });
  });

  // Thin tool bar above the F row
  const barH = PY * 0.62;
  const bar = touchBar();
  const barUnits = bar.reduce((a, k) => a + k.w, 0);
  const bu = Math.min(PX * 0.9, (fullW + gap + (split ? splitGap : 0)) / barUnits);
  let bx = -(barUnits * bu - gap) / 2;
  const barY = gap * 1.2 + barH / 2;
  bar.forEach((k) => { const w = k.w * bu - gap; if (!k.spacer) addKey(kb, k, bx + w / 2, barY, w, barH, k.w * bu, barH + gap, split); bx += k.w * bu; });
  kbTopLocal = barY + barH / 2;

  // Backing panel
  const bottomY = rowY[rowY.length - 1] - PY / 2;
  const pW = fullW + 0.036 + (split ? splitGap : 0), pTop = kbTopLocal + 0.016, pBot = bottomY - 0.016;
  if (false) { // no backing panel: keys float on their own
    backing = new THREE.Mesh(bendGeometry(new THREE.PlaneGeometry(pW, pTop - pBot, 48, 1)), panelMat(pW, pTop - pBot));
    backing.position.set(0, (pTop + pBot) / 2, -0.003); kb.add(backing);
  }

  // Grab bar under the keyboard (trigger or grip to move)
  const hy = pBot - 0.03;
  const hc = document.createElement('canvas'); hc.width = 256; hc.height = 32;
  const hg = hc.getContext('2d'); roundRect(hg, 2, 2, 252, 28, 14); hg.fillStyle = '#9AA6B4'; hg.fill();
  const ht = new THREE.CanvasTexture(hc); ht.colorSpace = THREE.SRGBColorSpace;
  handle = new THREE.Mesh(new THREE.PlaneGeometry(0.2, 0.016), new THREE.MeshBasicMaterial({ map: ht, transparent: true }));
  handle.position.set(0, hy, 0); handle.userData = { handle: true, hover: 0, baseZ: 0 }; kb.add(handle);
  const hh = new THREE.Mesh(new THREE.PlaneGeometry(0.34, 0.06), hitMat); hh.position.set(0, hy, 0.002); hh.userData = { mesh: handle }; kb.add(hh); hits.push(hh);
  positionPanel();
}
function panelMat(w, h) {
  const c = document.createElement('canvas'); c.width = 512; c.height = Math.max(64, Math.round(512 * (h || 0.3) / (w || 0.8)));
  const g = c.getContext('2d'); roundRect(g, 0, 0, c.width, c.height, 26); g.fillStyle = 'rgba(12,17,24,0.92)'; g.fill();
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  return new THREE.MeshBasicMaterial({ map: t, transparent: true, depthWrite: false });
}
function addKey(parent, k, cx, cy, w, h, hitW, hitH, flat) {
  const up = S.shift !== S.caps;
  let shown = k.label, sub = '';
  if (k.ch) shown = up ? k.ch.toUpperCase() : k.ch;
  else if (k.sym) { shown = S.shift ? k.sym[1] : k.sym[0]; sub = S.shift ? k.sym[0] : k.sym[1]; }
  const c = document.createElement('canvas'); c.height = 256; c.width = Math.max(128, Math.round(256 * w / h));
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = ANISO;
  const geo = new THREE.PlaneGeometry(w, h, flat ? 1 : Math.max(1, Math.round(w / 0.02)), 1);
  const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ map: tex, transparent: true }));
  if (!flat && isFinite(R)) { // bend each key around the curve so wide keys stay smooth
    const p = geo.attributes.position;
    for (let i = 0; i < p.count; i++) { const c0 = curvePos(cx + p.getX(i)), c1 = curvePos(cx); p.setX(i, c0.x - c1.x); p.setZ(i, c0.z - c1.z); }
    p.needsUpdate = true; geo.computeBoundingSphere();
    const c1 = curvePos(cx); mesh.position.set(c1.x, cy, c1.z);
  } else mesh.position.set(cx, cy, 0);
  mesh.userData = { key: k, shown, sub, canvas: c, tex, hot: false, down: false, hover: 0, baseZ: mesh.position.z, w, h, cx };
  drawKey(mesh);
  parent.add(mesh); keys.push(mesh);
  const hit = new THREE.Mesh(new THREE.PlaneGeometry(hitW, hitH), hitMat);
  hit.position.z = 0.002; hit.userData = { mesh }; mesh.add(hit); hits.push(hit);
}

/* ---------------------------------------------- slim preview strip (text) */
const stripCanvas = document.createElement('canvas'); stripCanvas.width = 2400; stripCanvas.height = 300;
const stripTex = new THREE.CanvasTexture(stripCanvas); stripTex.colorSpace = THREE.SRGBColorSpace; stripTex.anisotropy = 4;
const strip = new THREE.Mesh(new THREE.PlaneGeometry(0.72, 0.09), new THREE.MeshBasicMaterial({ map: stripTex, transparent: true }));
root.add(strip);
function positionPanel() {
  const a = kb.rotation.x;
  strip.position.set(0, kbTopLocal * Math.cos(a) + 0.07, kbTopLocal * Math.sin(a) - 0.01);
  strip.rotation.x = -0.1;
}
let caretOn = true;
function drawPanel() {
  const g = stripCanvas.getContext('2d'), W = 1600, H = 200;
  g.setTransform(1.5, 0, 0, 1.5, 0, 0); g.clearRect(0, 0, W, H);
  roundRect(g, 4, 4, W - 8, H - 8, 40); g.fillStyle = 'rgba(10,15,22,0.94)'; g.fill();
  g.lineWidth = 5; g.strokeStyle = S.live ? '#E5484D' : 'rgba(26,159,255,0.9)'; g.stroke();
  g.textBaseline = 'alphabetic'; g.font = '500 62px ' + FONT;
  const maxW = W - 120;
  const grey = greyText();
  let a = S.text, b = grey ? ((a && !/\s$/.test(a) ? ' ' : '') + grey) : '';
  while (a.length + b.length > 1 && g.measureText('\u2026' + a + b).width > maxW) { if (a.length) a = a.slice(1); else b = b.slice(1); }
  const trimmed = (a + b) !== (S.text + (grey ? ((S.text && !/\s$/.test(S.text) ? ' ' : '') + grey) : ''));
  let x = 56;
  if (!a && !b) { g.fillStyle = '#6E7883'; g.fillText(S.live ? 'Listening\u2026' : 'Start typing\u2026', x, 110); }
  else {
    if (trimmed) { g.fillStyle = '#6E7883'; g.fillText('\u2026', x, 110); x += g.measureText('\u2026').width; }
    if (S.sel && a) { g.fillStyle = 'rgba(26,159,255,.45)'; g.fillRect(x - 4, 48, g.measureText(a).width + 8, 76); }
    g.fillStyle = '#FFFFFF'; g.fillText(a, x, 110); x += g.measureText(a).width;
    if (b) { g.fillStyle = '#8E99A6'; g.fillText(b, x, 110); x += g.measureText(b).width; }
    if (caretOn) { g.fillStyle = '#8FCBFF'; g.fillRect(x + 4, 54, 5, 68); }
  }
  g.font = '600 30px ' + FONT;
  const last = S.sent[S.sent.length - 1];
  const info = S.status || (S.live ? 'Talk normally. Words appear as you speak. Press Listening to stop.' : last ? 'Sent: ' + last.t + (last.spoken ? '  \u2022 spoken' : '') : '');
  if (info) {
    let t = info; while (t.length > 1 && g.measureText(t).width > maxW) t = t.slice(0, -2) + '\u2026';
    g.fillStyle = S.status ? '#FFD28A' : '#8E99A6'; g.fillText(t, 56, 172);
  }
  stripTex.needsUpdate = true;
}
setInterval(() => { caretOn = !caretOn; drawPanel(); }, 530);

/* ----------------------------------------------------------- key bubble */
function makeBubble() {
  const c = document.createElement('canvas'); c.width = 192; c.height = 192;
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  const m = new THREE.Mesh(new THREE.PlaneGeometry(0.032, 0.032), new THREE.MeshBasicMaterial({ map: t, transparent: true, depthTest: false }));
  m.renderOrder = 10; m.visible = false; scene.add(m);
  m.userData = { canvas: c, tex: t, text: null };
  return m;
}
function setBubble(b, text, emoji) {
  if (b.userData.text === text) return;
  const g = b.userData.canvas.getContext('2d'); g.setTransform(1.5, 0, 0, 1.5, 0, 0); g.clearRect(0, 0, 128, 128);
  roundRect(g, 4, 4, 120, 120, 26); g.fillStyle = 'rgba(245,248,252,0.96)'; g.fill();
  g.fillStyle = '#0A0E13'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.font = emoji ? '64px ' + EMOJI_FONT : '600 66px ' + FONT; g.fillText(text, 64, 68);
  b.userData.tex.needsUpdate = true; b.userData.text = text;
}

/* -------------------------------------------------------------- pointers */
const raycaster = new THREE.Raycaster();
const tmpM = new THREE.Matrix4(), tmpV = new THREE.Vector3(), tmpV2 = new THREE.Vector3(), headPos = new THREE.Vector3();
const pointers = [];
const TIP = 0.06;
function makePointer(ctrl, isMouse) {
  const p = { ctrl, isMouse, hovered: null, cand: null, candN: 0, source: null, repeat: null, down: false, dir: new THREE.Vector3(0, 0, -1), touchKey: null, touchArmed: true, useSelect: true, gripDown: false };
  if (!isMouse) {
    const lg = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 0, -1)]);
    p.line = new THREE.Line(lg, new THREE.LineBasicMaterial({ color: 0x8fcbff, transparent: true, opacity: 0.7 }));
    scene.add(p.line);
    p.tip = new THREE.Mesh(new THREE.SphereGeometry(0.007, 14, 10), new THREE.MeshBasicMaterial({ color: 0x1a9fff }));
    p.tip.position.z = -TIP; ctrl.add(p.tip);
  }
  p.dot = new THREE.Mesh(new THREE.SphereGeometry(0.004, 12, 8), new THREE.MeshBasicMaterial({ color: 0xffffff, depthTest: false }));
  p.dot.renderOrder = 11; p.dot.visible = false; scene.add(p.dot);
  p.bubble = makeBubble();
  pointers.push(p);
  return p;
}
for (let i = 0; i < 2; i++) {
  const c = renderer.xr.getController(i); scene.add(c);
  const p = makePointer(c, false);
  c.addEventListener('connected', (e) => { p.source = e.data; const gp = e.data && e.data.gamepad; p.useSelect = !(gp && gp.buttons && gp.buttons.length > 1); });
  c.addEventListener('disconnected', () => { p.source = null; });
  c.addEventListener('selectstart', () => { unlockAudio(); if (p.useSelect) onPress(p); });
  c.addEventListener('selectend', () => { if (p.useSelect) onRelease(p, 'trigger'); });
  c.addEventListener('squeezestart', () => { if (p.useSelect) startGrab(p, 'grip'); });
  c.addEventListener('squeezeend', () => { if (p.useSelect) endGrab(p, 'grip'); });
}
const mouse = makePointer(null, true);
const ndc = new THREE.Vector2(-10, -10);
renderer.domElement.addEventListener('pointermove', (e) => { ndc.set((e.clientX / window.innerWidth) * 2 - 1, -(e.clientY / window.innerHeight) * 2 + 1); });
renderer.domElement.addEventListener('pointerdown', () => { unlockAudio(); if (!renderer.xr.isPresenting) onPress(mouse); });
window.addEventListener('pointerup', () => { if (!renderer.xr.isPresenting) onRelease(mouse, 'trigger'); });

function pick(p) {
  if (p.isMouse) raycaster.setFromCamera(ndc, camera);
  else {
    tmpM.identity().extractRotation(p.ctrl.matrixWorld);
    tmpV.set(0, 0, -1).applyMatrix4(tmpM);
    p.dir.lerp(tmpV, 0.45).normalize();
    raycaster.ray.origin.setFromMatrixPosition(p.ctrl.matrixWorld);
    raycaster.ray.direction.copy(p.dir);
  }
  const h = raycaster.intersectObjects(hits, false);
  return h[0] || null;
}
function haptic(p, strength, ms) {
  try {
    const gp = p.source && p.source.gamepad; if (!gp) return;
    if (gp.hapticActuators && gp.hapticActuators[0]) gp.hapticActuators[0].pulse(strength, ms);
    else if (gp.vibrationActuator) gp.vibrationActuator.playEffect('dual-rumble', { duration: ms, strongMagnitude: strength, weakMagnitude: strength });
  } catch (e) {}
}
function flash(m) { m.userData.down = true; drawKey(m); setTimeout(() => { if (m.userData.canvas) { m.userData.down = false; drawKey(m); } }, 90); }
function pressMesh(p, m) {
  if (!m) return;
  if (m.userData.handle) { startGrab(p, 'trigger'); return; }
  flash(m); haptic(p, 0.4, 16);
  press(m.userData.key);
  if (m.userData.key.act === 'back') { clearInterval(p.repeat); const t0 = Date.now(); p.repeat = setInterval(() => { if (Date.now() - t0 > 420) press(m.userData.key, true); }, 55); }
}
function onPress(p) { if (grab.p === p) return; pressMesh(p, p.hovered); }
function onRelease(p, by) { clearInterval(p.repeat); p.repeat = null; if (grab.p === p && grab.by === by) endGrab(p, by); }

/* ---- moving: the keyboard follows your hand's position and keeps facing you */
const grab = { p: null, by: null, offset: new THREE.Vector3(), dist: 0.5 };
const rayO = new THREE.Vector3(), rayD = new THREE.Vector3();
function ctrlRay(p) { p.ctrl.getWorldPosition(rayO); tmpM.identity().extractRotation(p.ctrl.matrixWorld); rayD.set(0, 0, -1).applyMatrix4(tmpM).normalize(); }
function headPosition(v) { (renderer.xr.isPresenting ? renderer.xr.getCamera() : camera).getWorldPosition(v); return v; }
function startGrab(p, by) {
  if (p.isMouse || !p.ctrl || grab.p) return;
  ctrlRay(p);
  // grab point: where the laser hits, or the keyboard centre when grabbing with the grip
  const hitPt = (p.lastHit && by === 'trigger') ? p.lastHit.clone() : root.position.clone();
  grab.dist = Math.max(0.15, hitPt.distanceTo(rayO));
  grab.offset.copy(root.position).sub(rayO.clone().addScaledVector(rayD, grab.dist));
  grab.p = p; grab.by = by;
  haptic(p, 0.5, 30);
}
function endGrab(p, by) { if (grab.p !== p || (by && grab.by !== by)) return; grab.p = null; grab.by = null; }
function updateGrab() {
  const p = grab.p; if (!p) return;
  const gp = p.source && p.source.gamepad;
  if (gp && gp.axes && gp.axes.length >= 4) {
    const x = gp.axes[2] || 0, y = gp.axes[3] || 0;
    if (Math.abs(y) > 0.2) grab.dist = Math.min(4, Math.max(0.15, grab.dist - y * 0.012)); // forward = push away
    if (Math.abs(x) > 0.2) root.rotation.y -= x * 0.025;                               // left/right = turn it
  }
  ctrlRay(p);
  root.position.copy(rayO).addScaledVector(rayD, grab.dist).add(grab.offset);
}

/* --------------------------------------------------------------- actions */
let rebuildQueued = false;
function rebuild() { if (rebuildQueued) return; rebuildQueued = true; requestAnimationFrame(() => { rebuildQueued = false; buildKeyboard(); drawPanel(); }); }
function setStatus(t, ms) { S.status = t; drawPanel(); if (ms) setTimeout(() => { if (S.status === t) { S.status = ''; drawPanel(); } }, ms); }
function pushHist() { S.hist.push(S.text); if (S.hist.length > 80) S.hist.shift(); }
function insert(s) {
  pushHist(); if (S.sel) { S.text = ''; S.sel = false; }
  S.text += s;
  if (S.shift) { S.shift = false; rebuild(); }
  drawPanel();
}

let actx = null;
function getAC() { try { actx = actx || new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {} return actx; }
function unlockAudio() { const ac = getAC(); if (ac && ac.state !== 'running') ac.resume().catch(() => {}); }
function click(freq) {
  if (!S.sounds) return;
  const ac = getAC(); if (!ac) return;
  try {
    const o = ac.createOscillator(), gn = ac.createGain();
    o.type = 'triangle'; o.frequency.value = freq || 1500;
    gn.gain.setValueAtTime(0.05, ac.currentTime); gn.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + 0.035);
    o.connect(gn); gn.connect(ac.destination); o.start(); o.stop(ac.currentTime + 0.045);
  } catch (e) {}
}

function press(k, repeat) {
  if (!repeat) click(k.bar ? 1100 : 1500);
  if (k.ch) { insert((S.shift !== S.caps) ? k.ch.toUpperCase() : k.ch); return; }
  if (k.sym) { insert(S.shift ? k.sym[1] : k.sym[0]); return; }
  if (k.ins) { insert(k.ins); return; }
  switch (k.act) {
    case 'back': pushHist(); if (S.sel) { S.text = ''; S.sel = false; } else S.text = Array.from(S.text).slice(0, -1).join(''); drawPanel(); break;
    case 'space': insert(' '); break;
    case 'tab': insert('    '); break;
    case 'enter': enter(); break;
    case 'shift': { const now = Date.now(); if (now - S.lastShift < 350) { S.caps = !S.caps; S.shift = false; } else S.shift = !S.shift; S.lastShift = now; rebuild(); break; }
    case 'caps': S.caps = !S.caps; S.shift = false; rebuild(); break;
    case 'l123': S.layer = '123'; S.shift = false; rebuild(); break;
    case 'lsym': S.layer = 'sym'; rebuild(); break;
    case 'abc': S.layer = 'abc'; rebuild(); break;
    case 'emoji': S.layer = 'emoji'; rebuild(); break;
    case 'esc': S.sel = false; drawPanel(); break;
    case 'fkey': setStatus(k.label + ' will go to the app you\u2019re typing in', 1600); break;
    case 'undo': if (S.hist.length) { S.text = S.hist.pop(); S.sel = false; drawPanel(); } else setStatus('Nothing to undo', 1200); break;
    case 'copy': case 'cut': {
      if (!S.text) { setStatus('Nothing to copy', 1200); break; }
      S.clip = S.text; try { navigator.clipboard && navigator.clipboard.writeText(S.text).catch(() => {}); } catch (e) {}
      if (k.act === 'cut') { pushHist(); S.text = ''; S.sel = false; }
      setStatus(k.act === 'cut' ? 'Cut' : 'Copied', 1200); break;
    }
    case 'paste': pasteText(); break;
    case 'selall': if (S.text) { S.sel = true; setStatus('All selected. Typing replaces it.', 1600); } break;
    case 'speak': S.speak = !S.speak; savePrefs(); rebuild(); break;
    case 'mic': toggleLive(); break;
    case 'recenter': placeInFront(); break;
    case 'lay-full': case 'lay-compact': case 'lay-split': S.layout = k.act.slice(4); if (S.layer !== 'abc') S.layer = 'abc'; savePrefs(); rebuild(); break;
    default: break;
  }
}
async function pasteText() {
  let t = '';
  try { if (navigator.clipboard && navigator.clipboard.readText) t = await navigator.clipboard.readText(); } catch (e) {}
  if (!t) t = S.clip;
  if (t) { insert(t); setStatus('Pasted', 1000); } else setStatus('Copy something first', 1400);
}
function enter() {
  const grey = greyText(); if (grey) { S.text += (S.text && !/\s$/.test(S.text) ? ' ' : '') + grey; S.partial = ''; S.pend = []; L.segId++; }
  const t = S.text.trim(); if (!t) return; pushHist(); S.text = ''; S.sel = false; send(t);
}
async function send(t) {
  const item = { t, spoken: false }; S.sent.push(item); if (S.sent.length > 20) S.sent.shift(); drawPanel();
  if (S.speak) { item.spoken = await speak(t); drawPanel(); }
}

/* ------------------------------------------------------- speech (TTS) */
let voiceSrc = null;
async function speak(t) {
  if (helper.tts) {
    try {
      const r = await fetch('/api/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: t, rate: S.rate }) });
      if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.error || ('helper error ' + r.status)); }
      const ab = await r.arrayBuffer();
      const ac = getAC(); await ac.resume();
      const buf = await ac.decodeAudioData(ab);
      if (voiceSrc) { try { voiceSrc.stop(); } catch (e) {} }
      voiceSrc = ac.createBufferSource(); voiceSrc.buffer = buf; voiceSrc.connect(ac.destination); voiceSrc.start();
      return true;
    } catch (e) { setStatus('Speak failed: ' + (e.message || e), 3500); return false; }
  }
  try {
    if ('speechSynthesis' in window && speechSynthesis.getVoices().length) {
      const u = new SpeechSynthesisUtterance(t); u.rate = S.rate; speechSynthesis.cancel(); speechSynthesis.speak(u); return true;
    }
  } catch (e) {}
  setStatus('No voice available. Run the setup to add one.', 2600);
  return false;
}

/* ------------------------------------------- live dictation (speech to text)
   Live words come from a real-time recognizer (sherpa-onnx), fed about every 50 ms while you talk.
   When you pause, Whisper rewrites that sentence with punctuation and capitals and it is typed for real. */
const L = { stream: null, src: null, proc: null, seg: [], segLen: 0, pre: [], preLen: 0, speaking: false, silence: 0, floor: 0.006,
  sinceDraft: 0, draftBusy: false, segId: 0, chain: Promise.resolve(), timer: null, q: [], qLen: 0, sending: false, sid: Math.random().toString(36).slice(2, 8) };
S.pend = [];
const SR = 16000;
function wavFromChunks(chunks, n) {
  const out = new DataView(new ArrayBuffer(44 + n * 2));
  const w = (o, s) => { for (let i = 0; i < s.length; i++) out.setUint8(o + i, s.charCodeAt(i)); };
  w(0, 'RIFF'); out.setUint32(4, 36 + n * 2, true); w(8, 'WAVE'); w(12, 'fmt ');
  out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true); out.setUint32(24, SR, true);
  out.setUint32(28, SR * 2, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true); w(36, 'data'); out.setUint32(40, n * 2, true);
  let o = 44;
  for (const c of chunks) for (let i = 0; i < c.length; i++) { const s = Math.max(-1, Math.min(1, c[i])); out.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true); o += 2; }
  return new Blob([out.buffer], { type: 'audio/wav' });
}
function pcm16(chunks, n) {
  const out = new Int16Array(n); let o = 0;
  for (const c of chunks) for (let i = 0; i < c.length; i++) { const s = Math.max(-1, Math.min(1, c[i])); out[o++] = s < 0 ? s * 0x8000 : s * 0x7fff; }
  return out.buffer;
}
function downsample(buf, rate) {
  const ratio = rate / SR, n = Math.floor(buf.length / ratio), out = new Float32Array(n);
  for (let i = 0; i < n; i++) { const a = Math.floor(i * ratio), b = Math.min(buf.length, Math.floor((i + 1) * ratio)); let s = 0; for (let j = a; j < b; j++) s += buf[j]; out[i] = s / Math.max(1, b - a); }
  return out;
}
function greyText() { return S.pend.map((x) => x.text).concat(S.partial ? [S.partial] : []).filter(Boolean).join(' '); }
function prettyLive(t) {
  let s = (t || '').toLowerCase().replace(/\bi\b/g, 'I').replace(/\bi'/g, 'I\'');
  if ((!S.text.trim() || /[.?!]\s*$/.test(S.text)) && !S.pend.length) s = s.charAt(0).toUpperCase() + s.slice(1);
  return s;
}
async function stt(chunks, n, mode) {
  const context = encodeURIComponent(S.text.slice(-150));
  const r = await fetch('/api/stt?mode=' + mode + '&context=' + context, { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wavFromChunks(chunks, n) });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || 'failed');
  return (j.text || '').trim();
}
function pump() { // send new audio to the real-time recognizer, one request at a time
  if (!helper.live || L.sending || !L.qLen) return;
  const id = L.segId, body = pcm16(L.q, L.qLen); L.q = []; L.qLen = 0; L.sending = true;
  fetch('/api/stream?sid=' + L.sid + '-' + id, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body })
    .then((r) => r.json()).then((j) => { if (id === L.segId && S.live && j.text !== undefined) { S.partial = prettyLive(j.text); drawPanel(); } })
    .catch(() => {}).finally(() => { L.sending = false; if (L.qLen) pump(); });
}
function draft() { // only used when the real-time recognizer isn't installed
  if (helper.live || !L.speaking || L.draftBusy || L.sinceDraft < SR * 0.25) return;
  const id = L.segId, chunks = L.seg.slice(), n = L.segLen;
  L.draftBusy = true; L.sinceDraft = 0;
  stt(chunks, n, 'draft').then((t) => { if (id === L.segId && S.live) { S.partial = t; drawPanel(); } }).catch(() => {}).finally(() => { L.draftBusy = false; });
}
function commit(item, t) {
  if (!S.pend.includes(item)) return; // already sent with Enter
  S.pend = S.pend.filter((x) => x !== item);
  if (t) insert((S.text && !/\s$/.test(S.text) ? ' ' : '') + t); else drawPanel();
}
function finishSegment() {
  if (!L.segLen) return;
  const chunks = L.seg, n = L.segLen, liveText = S.partial;
  L.seg = []; L.segLen = 0; L.speaking = false; L.silence = 0; L.sinceDraft = 0; L.segId++; L.q = []; L.qLen = 0;
  S.partial = '';
  if (n < SR * 0.3 && !liveText) { drawPanel(); return; }
  const item = { text: liveText }; S.pend.push(item); drawPanel();
  if (!helper.stt) { commit(item, liveText); return; }
  L.chain = L.chain.then(() => stt(chunks, n, 'final')).then((t) => commit(item, t || liveText))
    .catch((e) => { commit(item, liveText); if (!liveText) setStatus('Voice typing failed: ' + (e.message || e), 4000); });
}
function onAudio(e) {
  const ac = getAC();
  const d = downsample(e.inputBuffer.getChannelData(0), ac.sampleRate);
  let sum = 0; for (let i = 0; i < d.length; i++) sum += d[i] * d[i];
  const rms = Math.sqrt(sum / Math.max(1, d.length));
  const loud = rms > Math.max(0.012, L.floor * 2.6);
  if (!L.speaking && !loud) { L.floor = L.floor * 0.95 + rms * 0.05; }
  if (loud && !L.speaking) { L.speaking = true; L.seg = L.pre.slice(); L.segLen = L.preLen; L.q = L.pre.slice(); L.qLen = L.preLen; L.silence = 0; }
  if (L.speaking) {
    L.seg.push(d); L.segLen += d.length; L.sinceDraft += d.length;
    L.q.push(d); L.qLen += d.length; pump();
    if (loud) L.silence = 0; else L.silence += d.length;
    if (L.silence > SR * 0.45 || L.segLen > SR * 12) finishSegment();
  } else { // keep a little audio from before you started talking
    L.pre.push(d); L.preLen += d.length;
    while (L.preLen > SR * 0.35 && L.pre.length > 1) L.preLen -= L.pre.shift().length;
  }
  e.outputBuffer.getChannelData(0).fill(0);
}
async function toggleLive() {
  if (S.live) { stopLive(); return; }
  if (!helper.stt && !helper.live) { setStatus('Voice typing needs the helper running. See the setup steps.', 3200); return; }
  try { L.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } }); }
  catch (e) { setStatus('Microphone blocked. Allow it on the start page, then try again.', 3600); return; }
  const ac = getAC(); await ac.resume();
  L.src = ac.createMediaStreamSource(L.stream);
  L.proc = ac.createScriptProcessor(1024, 1, 1);
  L.proc.onaudioprocess = onAudio;
  L.src.connect(L.proc); L.proc.connect(ac.destination);
  L.seg = []; L.segLen = 0; L.pre = []; L.preLen = 0; L.q = []; L.qLen = 0; L.speaking = false;
  L.timer = setInterval(draft, 300);
  S.live = true; S.partial = ''; rebuild();
}
function stopLive() {
  if (L.speaking) finishSegment();
  clearInterval(L.timer);
  try { L.proc && L.proc.disconnect(); L.src && L.src.disconnect(); } catch (e) {}
  if (L.stream) L.stream.getTracks().forEach((t) => t.stop());
  L.stream = L.src = L.proc = null;
  S.live = false; rebuild();
}

/* --------------------------------------------------------------- render */
const camPos = new THREE.Vector3(), worldPos = new THREE.Vector3(), worldN = new THREE.Vector3(), up = new THREE.Vector3(), q = new THREE.Quaternion();
let placed = false;
function placeInFront() {
  if (grab.p) endGrab(grab.p);
  const cam = renderer.xr.isPresenting ? renderer.xr.getCamera() : camera;
  cam.getWorldPosition(camPos);
  const dir = new THREE.Vector3(); cam.getWorldDirection(dir); dir.y = 0; if (dir.lengthSq() < 1e-4) dir.set(0, 0, -1); dir.normalize();
  root.position.copy(camPos).addScaledVector(dir, 0.52); root.position.y = camPos.y - 0.26;
  root.rotation.set(0, Math.atan2(-dir.x, -dir.z), 0);
}
renderer.xr.addEventListener('sessionstart', () => { placed = false; $('start').style.display = 'none'; });
renderer.xr.addEventListener('sessionend', () => { $('start').style.display = ''; scene.background = BG; grid.visible = true; grab.p = null; root.position.set(0, 1.2, -0.55); root.rotation.set(0, 0, 0); });

function pollButtons(p) {
  const gp = p.source && p.source.gamepad; if (!gp || !gp.buttons || p.useSelect) return;
  const trig = gp.buttons[0] ? (gp.buttons[0].value || (gp.buttons[0].pressed ? 1 : 0)) : 0;
  if (!p.down && trig > 0.3) { p.down = true; unlockAudio(); onPress(p); }
  else if (p.down && trig < 0.15) { p.down = false; onRelease(p, 'trigger'); }
  const grip = !!(gp.buttons[1] && gp.buttons[1].pressed);
  if (grip && !p.gripDown) startGrab(p, 'grip');
  if (!grip && p.gripDown) endGrab(p, 'grip');
  p.gripDown = grip;
}
function touchTyping(p) {
  if (!S.touch || !p.tip || grab.p === p) return;
  p.tip.getWorldPosition(tmpV);
  let found = null;
  for (const m of keys) {
    tmpV2.copy(tmpV); m.worldToLocal(tmpV2);
    const d = m.userData;
    if (Math.abs(tmpV2.x) < d.w / 2 + 0.002 && Math.abs(tmpV2.y) < d.h / 2 + 0.002 && tmpV2.z < 0.008 && tmpV2.z > -0.035) { found = m; break; }
  }
  if (found && found !== p.touchKey && p.touchArmed) { pressMesh(p, found); p.touchArmed = false; }
  if (!found) { p.touchArmed = true; if (p.touchKey) onRelease(p, 'touch'); }
  p.touchKey = found;
}
function setHot(m, on) { if (!m || !m.userData.canvas || m.userData.hot === on) return; m.userData.hot = on; drawKey(m); }

renderer.setAnimationLoop(() => {
  const xr = renderer.xr.isPresenting;
  if (xr && !placed) { placeInFront(); placed = true; }
  const active = xr ? pointers.filter((p) => !p.isMouse && p.source) : [mouse];
  const hot = new Set();
  pointers.forEach((p) => {
    const on = active.includes(p);
    if (p.line) p.line.visible = on && grab.p !== p;
    if (!on) { p.hovered = null; p.dot.visible = false; p.bubble.visible = false; return; }
    if (!p.isMouse) { pollButtons(p); touchTyping(p); }
    if (grab.p === p) { p.dot.visible = false; p.bubble.visible = false; return; }
    const h = pick(p);
    const m = h ? h.object.userData.mesh : null;
    if (m !== p.hovered) {
      if (m === p.cand) p.candN++; else { p.cand = m; p.candN = 1; }
      if (p.candN >= 2 || !p.hovered || p.isMouse) { p.hovered = m; p.cand = null; if (m && !p.isMouse) haptic(p, 0.08, 5); if (!m) clearInterval(p.repeat); }
    } else p.cand = null;
    if (p.line) {
      p.line.position.copy(raycaster.ray.origin);
      p.line.quaternion.setFromUnitVectors(tmpV.set(0, 0, -1), raycaster.ray.direction);
      p.line.scale.z = h ? h.distance : 2;
    }
    if (h) { p.dot.position.copy(h.point); p.dot.visible = true; p.lastHit = h.point.clone(); } else { p.dot.visible = false; p.lastHit = null; }
    if (p.hovered) hot.add(p.hovered);
    const pm = p.hovered, k = pm && pm.userData.key;
    if (k && k.char && pm.userData.shown) {
      setBubble(p.bubble, pm.userData.shown, k.emoji);
      pm.getWorldPosition(worldPos); pm.getWorldQuaternion(q);
      up.set(0, 1, 0).applyQuaternion(q); worldN.set(0, 0, 1).applyQuaternion(q);
      p.bubble.position.copy(worldPos).addScaledVector(up, pm.userData.h * 0.5 + 0.022).addScaledVector(worldN, 0.02);
      headPosition(camPos); p.bubble.lookAt(camPos); p.bubble.visible = true;
    } else p.bubble.visible = false;
  });
  updateGrab();
  keys.forEach((m) => { const h = hot.has(m); setHot(m, h); const d = m.userData; d.hover += ((h ? 1 : 0) - d.hover) * 0.4; m.position.z = d.baseZ + d.hover * 0.004; });
  if (handle) { const h = hot.has(handle) || grab.p; handle.scale.set(h ? 1.15 : 1, h ? 1.3 : 1, 1); }
  renderer.render(scene, camera);
});
window.addEventListener('resize', () => { camera.aspect = window.innerWidth / window.innerHeight; camera.updateProjectionMatrix(); renderer.setSize(window.innerWidth, window.innerHeight); });

/* ------------------------------------------------------------- start page */
async function setupXR() {
  const msg = $('xrMsg');
  if (!navigator.xr) { msg.textContent = 'No WebXR in this browser. Open this page in Chromium XR on the Frame. You can still try it here with the mouse.'; return; }
  let vr = false, ar = false;
  try { vr = await navigator.xr.isSessionSupported('immersive-vr'); } catch (e) {}
  try { ar = await navigator.xr.isSessionSupported('immersive-ar'); } catch (e) {}
  msg.textContent = vr ? 'VR is ready. Put the headset on and press Enter VR.' : 'This browser has WebXR but can\u2019t start VR. Use Chromium XR on the Frame.';
  const start = async (mode) => {
    unlockAudio();
    try {
      const session = await navigator.xr.requestSession(mode, { optionalFeatures: ['local-floor', 'bounded-floor'] });
      try { const nat = XRWebGLLayer.getNativeFramebufferScaleFactor(session) || 1; renderer.xr.setFramebufferScaleFactor(Math.min(2, Math.max(1.75, nat))); } catch (e) {}
      try { renderer.xr.setFoveation(0); } catch (e) {}
      if (mode === 'immersive-ar') { scene.background = null; grid.visible = false; }
      await renderer.xr.setSession(session);
    } catch (e) { msg.textContent = 'Couldn\u2019t start VR: ' + (e.message || e); }
  };
  const b = $('enterVR'); b.disabled = !vr; b.onclick = () => start('immersive-vr');
  if (ar) { const a = $('enterAR'); a.hidden = false; a.onclick = () => start('immersive-ar'); }
}
async function checkHelper() {
  try { const j = await (await fetch('/api/status', { cache: 'no-store' })).json(); helper.stt = !!j.stt; helper.tts = !!j.tts; helper.live = !!j.live; helper.model = j.model || ''; } catch (e) {}
  $('sttStat').textContent = helper.live ? 'ready: live words + ' + helper.model + ' clean-up' : helper.stt ? 'ready (' + helper.model + '), live words off: run setup.sh' : 'off: start the helper with start.sh';
  $('sttStat').className = helper.live ? 'ok' : 'warn';
  const browserVoice = ('speechSynthesis' in window) && speechSynthesis.getVoices().length > 0;
  $('ttsStat').textContent = helper.tts ? 'ready (Piper voice)' : browserVoice ? 'using the browser\u2019s voice' : 'no voice yet: run setup.sh';
  $('ttsStat').className = helper.tts || browserVoice ? 'ok' : 'warn';
}
$('micBtn').onclick = async () => {
  unlockAudio();
  try { const s = await navigator.mediaDevices.getUserMedia({ audio: true }); s.getTracks().forEach((t) => t.stop()); $('micStat').textContent = 'allowed'; $('micStat').className = 'ok'; }
  catch (e) { $('micStat').textContent = 'blocked: ' + (e.name || e); $('micStat').className = 'warn'; }
};
$('testVoice').onclick = async () => { unlockAudio(); await checkHelper(); const ok = await speak('Hi, this is your BetterFrame keyboard.'); $('ttsStat').textContent = ok ? 'played a test sentence' : (S.status || 'no sound'); };
$('hide').onclick = () => { $('start').style.display = 'none'; };
function bindOpt(id, key, parse, live) {
  const el = $(id); if (!el) return;
  el.value = key === 'sounds' || key === 'touch' ? (S[key] ? '1' : '0') : String(S[key]);
  el.addEventListener(live ? 'input' : 'change', () => { S[key] = parse(el.value); savePrefs(); rebuild(); });
}
bindOpt('optCurve', 'curve', Number, true);
bindOpt('optSize', 'size', String, false);
bindOpt('optSnd', 'sounds', (v) => v === '1', false);
bindOpt('optTouch', 'touch', (v) => v === '1', false);
bindOpt('optRate', 'rate', Number, true);
try { if ('speechSynthesis' in window) speechSynthesis.onvoiceschanged = checkHelper; } catch (e) {}
// warm the speech model up so the first dictation is quick
fetch('/api/status').catch(() => {});

buildKeyboard();
drawPanel();
setupXR();
checkHelper();
