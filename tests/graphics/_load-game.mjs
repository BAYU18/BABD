// Headless loader for the single-file game.
//
// Reads index.html, extracts the single inline <script>, and evaluates it in a
// node:vm context with the minimum browser surface the game touches
// (document/window/requestAnimationFrame/localStorage/canvas 2d context stub).
//
// The game is an IIFE, so it exposes nothing by default. To reach the internal
// seam functions we append a small "export" tail to the script source that
// assigns the symbols the tests need onto a global. That keeps the shipped file
// untouched while letting the pure seam be tested headlessly.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import vm from 'node:vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
// tests/ lives at <root>/workspace/tests/, and the canonical artifact is
// <root>/index.html (the plan's absolute path, expressed relative so the same
// tests run unchanged in the worktree).
const HTML_PATH = resolve(__dirname, '..', '..', 'index.html');

// The names the tests reach for. `buildX` helpers may not exist yet in early
// tasks; the exporter assigns only those that are defined at boot.
const EXPORTS = [
  'computeRenderState',
  'buildRoadLayer',
  'buildCarDescriptors',
  'buildObstacleDescriptors',
  'buildSceneryLayer',
  'buildEffects',
  'buildHudDescriptors',
  'buildLighting',
  'qualityTier',
  'feedFrameTime',
  'resizeBackingStore',
];

function makeCtxStub() {
  const noop = function () {};
  return {
    // state
    fillStyle: '', strokeStyle: '', lineWidth: 1, font: '', textAlign: '',
    textBaseline: '', globalAlpha: 1,
    // path + draw ops: all no-ops (the pure seam tests never inspect pixels)
    save: noop, restore: noop, translate: noop, rotate: noop, scale: noop,
    setTransform: noop, resetTransform: noop,
    beginPath: noop, closePath: noop, moveTo: noop, lineTo: noop, arc: noop,
    rect: noop, roundRect: noop, quadraticCurveTo: noop, bezierCurveTo: noop,
    fill: noop, stroke: noop, clip: noop,
    fillRect: noop, strokeRect: noop, clearRect: noop,
    fillText: noop, strokeText: noop, measureText: function () { return { width: 0 }; },
    createLinearGradient: function () { return { addColorStop: noop }; },
    createRadialGradient: function () { return { addColorStop: noop }; },
    createPattern: function () { return null; },
    drawImage: noop,
    getImageData: function () { return { data: new Uint8ClampedArray(4) }; },
    putImageData: noop,
  };
}

function makeElementStub(tag) {
  const el = {
    tagName: String(tag || '').toUpperCase(),
    style: {}, dataset: {},
    width: 400, height: 600,
    addEventListener: function () {}, removeEventListener: function () {},
    getContext: function () { return makeCtxStub(); },
    getBoundingClientRect: function () {
      return { x: 0, y: 0, left: 0, top: 0, width: 400, height: 600, right: 400, bottom: 600 };
    },
    appendChild: function () {}, setAttribute: function () {}, classList: { add: function () {}, remove: function () {} },
  };
  return el;
}

export function loadGame(options) {
  options = options || {};
  const html = options.html || readFileSync(HTML_PATH, 'utf8');

  const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
  if (!scriptMatch) throw new Error('no inline <script> found in index.html');
  let body = scriptMatch[1];

  const mathRandomCalls = { n: 0 };
  const realRandom = Math.random;

  // Export tail: the game body is an IIFE, so its internals are otherwise
  // unreachable. Inject the exporter *inside* the IIFE (just before the final
  // `})();`) so it can see the seam functions. The game's real
  // `window.__GAME__` hook is separate and stays intact.
  const tail = `
    var __exp = {};
    ${EXPORTS.map((n) => `if (typeof ${n} === 'function') __exp.${n} = ${n};`).join('\n    ')}
    (typeof window !== 'undefined' ? window : globalThis).__SEAM__ = __exp;
`;
  const closeIdx = body.lastIndexOf('})();');
  if (closeIdx === -1) throw new Error('could not find IIFE close in index.html script');
  body = body.slice(0, closeIdx) + tail + '\n' + body.slice(closeIdx);


  const canvasEl = makeElementStub('canvas');
  const doc = {
    hidden: false,
    getElementById: function (id) { return id === 'game' ? canvasEl : null; },
    addEventListener: function () {}, removeEventListener: function () {},
    createElement: function (t) { return makeElementStub(t); },
    querySelector: function () { return null; },
    body: makeElementStub('body'),
    documentElement: makeElementStub('html'),
  };

  const sandbox = {
    console: console,
    Math: Math,
    Date: Date,
    JSON: JSON,
    Infinity: Infinity,
    NaN: NaN,
    isFinite: isFinite,
    parseInt: parseInt,
    parseFloat: parseFloat,
    Uint8ClampedArray: Uint8ClampedArray,
    Float32Array: Float32Array,
    Array: Array,
    Object: Object,
    Number: Number,
    String: String,
    Boolean: Boolean,
    Map: Map,
    Set: Set,
  };

  const win = {
    devicePixelRatio: options.dpr || 1,
    innerWidth: 1024,
    innerHeight: 768,
    addEventListener: function () {}, removeEventListener: function () {},
    matchMedia: function (q) {
      const prefs = options.prefs || {};
      const matches =
        (q.indexOf('prefers-reduced-motion') !== -1 && !!prefs.reducedMotion) ||
        (q.indexOf('prefers-contrast') !== -1 && !!prefs.contrast);
      return { matches: matches, media: q, addEventListener: function () {}, addListener: function () {} };
    },
    requestAnimationFrame: function () { return 0; },
    cancelAnimationFrame: function () {},
    localStorage: {
      _s: {},
      getItem: function (k) { return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
      setItem: function (k, v) { this._s[k] = String(v); },
      removeItem: function (k) { delete this._s[k]; },
    },
    __GAME__: null,
  };

  sandbox.window = win;
  sandbox.document = doc;
  sandbox.globalThis = sandbox;
  sandbox.requestAnimationFrame = win.requestAnimationFrame;
  sandbox.cancelAnimationFrame = win.cancelAnimationFrame;
  sandbox.setTimeout = setTimeout;
  sandbox.clearTimeout = clearTimeout;
  sandbox.localStorage = win.localStorage;
  // Count Math.random calls without changing behaviour (Task 4 asserts that
  // rendering never perturbs the spawn stream).
  const mathProxy = Object.create(Math);
  mathProxy.random = function () { mathRandomCalls.n++; return realRandom(); };
  sandbox.Math = mathProxy;
  if (win.Math === undefined) win.Math = mathProxy;

  const context = vm.createContext(sandbox);
  vm.runInContext(body, context, { filename: 'index.html' });

  const seam = win.__SEAM__ || sandbox.__SEAM__ || (sandbox.globalThis && sandbox.globalThis.__SEAM__) || {};

  function makeGameState(overrides) {
    const base = {
      canvas: { w: 400, h: 600, dpr: options.dpr || 1 },
      state: 'start',
      carLane: 1,
      startLane: 1,
      carX: 1 * 100 + (100 - 40) / 2,
      carY: 510,
      obstacles: [],
      score: 0,
      highScore: 0,
      dashOffset: 0,
      obstacleSpeed: 140,
      spawnInterval: 1.1,
      laneShift: 0,
      laneVisual: 1,
      prefs: { reducedMotion: !!((options.prefs || {}).reducedMotion), contrast: !!((options.prefs || {}).contrast) },
    };
    return Object.assign(base, overrides || {});
  }

  // Values built inside the vm live in a different realm, so their prototypes
  // differ from the host's Object.prototype and strict `deepEqual` (which
  // compares prototypes) rejects otherwise-identical objects. Re-materialize
  // every seam return value in the host realm with a structured deep clone.
  function toHost(value) {
    if (value === null || typeof value !== 'object') return value;
    return JSON.parse(JSON.stringify(value));
  }
  const seamHost = {};
  Object.keys(seam).forEach(function (name) {
    const fn = seam[name];
    seamHost[name] = function () {
      return toHost(fn.apply(null, arguments));
    };
  });

  return {
    html: html,
    window: win,
    document: doc,
    canvas: canvasEl,
    mathRandomCalls: function () { return mathRandomCalls.n; },
    makeGameState: makeGameState,
    // Pull every exported seam symbol up onto the returned object.
    ...seamHost,
  };
}

export default loadGame;
