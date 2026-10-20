// Pure timing/sampling regressions: no browser, network, or archive writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const tr = (s, ...v) => typeof s === 'string' ? s : s.reduce((out, part, i) => out + (i ? v[i - 1] : '') + part, '');
const source = fs.readFileSync(require('node:path').join(__dirname, '../hinome/template.html'), 'utf8');
const functions = ['loop', 'pickVis'].map(name => {
  const match = source.match(new RegExp(`function ${name}\\([^]*?\\n}`));
  assert.ok(match, `${name} exists`); return match[0];
}).join('\n');
function scene(overrides = {}) {
  const calls = {frames: 0, fits: 0, dt: 0};
  const R = {last: 100, lowq: false, quality: 'auto', ft: 16.7, t0: 0, smokeDt: 0, uiTime: 0, holds: new Set(), ...overrides};
  const math = Object.create(Math);
  const ctx = vm.createContext({R, Math: math, requestAnimationFrame: () => 1,
    advance: dt => { calls.frames++; calls.dt = dt; }, computeVis() {}, drawRing() {},
    smokeStep() {}, fxFrame() {}, updateKuji() {}, updateScrub() {}, hoverStillHolds() {},
    ringFit: () => calls.fits++, syncQuality() {}, ringStop() { calls.stops = (calls.stops || 0) + 1; R.raf = 0; }});
  vm.runInContext(functions, ctx);
  return {R, calls, ctx};
}
let s = scene(); s.ctx.loop(108); assert.equal(s.calls.frames, 0);
s.ctx.loop(117); assert.equal(s.calls.frames, 1); assert.equal(s.calls.dt, 17);
s = scene({lowq: true}); s.ctx.loop(117); assert.equal(s.calls.frames, 0);
s.ctx.loop(134); assert.equal(s.calls.frames, 1); assert.equal(s.calls.dt, 34);
s = scene({last: 3980, ft: 50}); s.ctx.loop(4000);
assert.equal(s.R.lowq, true); assert.equal(s.calls.fits, 1);
s = scene({quality: 'rich', last: 3980, ft: 50}); s.ctx.loop(4000);
assert.equal(s.R.lowq, false); assert.equal(s.calls.fits, 0);
s = scene({lowq: true}); s.ctx.loop(5100); assert.equal(s.calls.dt, 100);
s = scene();
for (let i = 1; i <= 144; i++) s.ctx.loop(100 + i * 1000 / 144);
assert.ok(s.calls.frames >= 59 && s.calls.frames <= 61, '144 Hz display should render about 60 frames');
// A hold (an open post, a resting pointer) freezes the dial only after a seek in flight has landed.
s = scene({holds: new Set(['drawer']), seek: {}}); s.ctx.loop(117); assert.equal(s.calls.frames, 1); assert.equal(s.calls.stops, undefined, 'the glide finishes');
s.R.seek = null; s.ctx.loop(134); assert.equal(s.calls.frames, 2); assert.equal(s.calls.stops, 1, 'then the dial stops'); assert.equal(s.R.raf, 0);
s = scene({vis: [], totalWeight: 0}); assert.equal(s.ctx.pickVis(), null);
s.R.vis = [{weightEnd: 1}, {weightEnd: 3}, {weightEnd: 10}]; s.R.totalWeight = 10;
for (const [random, index] of [[0, 0], [.15, 1], [.8, 2], [.99999, 2]]) {
  s.ctx.Math.random = () => random; assert.equal(s.ctx.pickVis(), s.R.vis[index]);
}
console.log('PASS render pacing, adaptive quality, long frames, weighted particle sampling');

const extract = name => source.match(new RegExp(`function ${name}\\([^]*?\\n}`))[0];
// The GPU queue must remain bounded, including while the worker is delayed.
const messages = [], timers = new Map(); let timerId = 0, failed = 0;
const G = {data: new Float32Array(28), count: 1, spare: null, busy: false, pending: null,
  worker: {postMessage(m, transfer) { messages.push(structuredClone(m, {transfer})); }}, canvas: {hidden: true}};
const bridge = vm.createContext({G, R: {W: 400, H: 800, portrait: true}, cFx: {width: 600, height: 1200},
  Float32Array, performance: {now: () => 10}, document: {hidden: false},
  setTimeout: fn => { timers.set(++timerId, fn); return timerId; }, clearTimeout: id => timers.delete(id),
  gpuFailed: () => failed++, clamp: (v, a, b) => Math.max(a, Math.min(b, v))});
vm.runInContext(['gpuSend', 'gpuSubmit', 'gpuQuad'].map(extract).join('\n'), bridge);
const original = G.data.buffer; bridge.gpuSubmit();
assert.equal(original.byteLength, 0, 'transfer ownership, do not clone per frame');
assert.equal(messages.length, 1); assert.equal(G.busy, true); assert.equal(G.canvas.hidden, false);
for (let i = 0; i < 100; i++) { G.data[0] = i; bridge.gpuSubmit(); }
assert.equal(messages.length, 1, 'busy worker must not accumulate queued frames');
assert.equal(G.pending.data[0], 99, 'retain only the latest frame');
G.spare = new Float32Array(messages[0].data); G.busy = false;
bridge.gpuSend(G.pending); assert.equal(messages.length, 2); assert.equal(new Float32Array(messages[1].data)[0], 99);
assert.equal(G.pending, null); assert.equal(timers.size, 1); [...timers.values()][0](); assert.equal(failed, 1);
G.count = 0; bridge.gpuQuad(10, 20, 0, 1, 30, 4, 0, 64, 512, 48, 2);
assert.deepEqual(Array.from(G.data.slice(0, 14)), [10, 20, 0, 30, -4, 0, 0, 64, 512, 48, 1, 1, 1, 1]);
for (let i = 0; i < 100; i++) bridge.gpuQuad(1, 2, 1, 0, 3, 4, 0, 0, 256, 4, .5);
assert.ok(G.data.length >= G.count * 14, 'dense scenes grow without dropping effects');
console.log('PASS GPU instance geometry, transferable reuse, bounded queue and stalled-worker fallback');
let fits = 0;
const adaptive = vm.createContext({G: {}, R: {quality: 'auto', lowq: false}, document: {hidden: false}, ringFit: () => fits++, syncQuality() {}});
vm.runInContext(extract('gpuAdapt'), adaptive);
for (let i = 0; i < 29; i++) adaptive.gpuAdapt(50);
assert.equal(fits, 0); adaptive.gpuAdapt(50); assert.equal(fits, 1); assert.equal(adaptive.R.lowq, true);
adaptive.R.quality = 'rich'; adaptive.R.lowq = false;
for (let i = 0; i < 40; i++) adaptive.gpuAdapt(100);
assert.equal(fits, 1); assert.equal(adaptive.R.lowq, false);
console.log('PASS sustained slow-worker adaptation without reducing explicit rich quality');

// Cancel/lost capture must release autoplay suppression and suppress drag-generated clicks only.
const dragContext = vm.createContext({dialGesture: {id: 7, moved: true}, dialSuppressClick: 0, R: {drag: true},
  performance: {now: () => 100}, cFx: {style: {}, hasPointerCapture: () => true, releasePointerCapture() {}}});
vm.runInContext(extract('dialEnd'), dragContext);
dragContext.dialEnd({pointerId: 8}); assert.equal(dragContext.R.drag, true);
dragContext.dialEnd({pointerId: 7}); assert.equal(dragContext.R.drag, false); assert.equal(dragContext.dialGesture, null);
assert.equal(dragContext.dialSuppressClick, 500);
console.log('PASS dial cancellation, pointer ownership and click suppression');

const semantics = vm.createContext({clamp: (v, a, b) => Math.max(a, Math.min(b, v)),
  R: {lowq: false, t: 0, flare: new Map()}, TAU: Math.PI * 2, wrapA: a => ((a % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)});
vm.runInContext(source.slice(source.indexOf('const METRICS ='), source.indexOf('const RANK =')) +
  extract('paintBeam'), semantics);
const a = {id: 'a', ts: 100, score: 100, stats: {like: 80, comment: 5, forward: 1}, tags: ['游戏']};
const b = {id: 'b', ts: 200, score: 100, tags: ['游戏']};
const c = {id: 'c', ts: 300, score: 400, tags: ['音乐']};
assert.equal(semantics.metricValue({stats: {like: 80, comment: 5, forward: 1}}, 'score'), 100);
assert.equal(semantics.metricValue(a, 'comment'), 5); assert.equal(semantics.metricValue(b, 'comment'), null);
assert.equal(semantics.metricValue({stats: {comment: 0}}, 'comment'), 0);
assert.equal(semantics.metricValue({stats: {comment: -1}}, 'comment'), null);
const ranks = semantics.metricRanks([a, b, c], 'score'); assert.equal(ranks.get(a), ranks.get(b)); assert.ok(ranks.get(c) > ranks.get(a));
const uniform = semantics.metricRanks([a, b], 'score'); assert.equal(uniform.get(a), .5); assert.equal(uniform.get(b), .5);
const scale = semantics.metricScale([a, b, c], 'score'); assert.equal(scale.cap, 400);
assert.equal(semantics.beamFraction(100, 400), .5); assert.equal(semantics.beamFraction(0, 400), 0);
assert.equal(semantics.beamFraction(null, 400), 0); assert.equal(semantics.beamFraction(800, 400), 1);
assert.equal(semantics.metricScale([], 'score').cap, 1);
const distribution = Array.from({length: 100}, (_, i) => ({score: i < 50 ? 137 : i < 90 ? 664 : i < 99 ? 8445 : 55101}));
const distributionScale = semantics.metricScale(distribution, 'score');
assert.ok(semantics.beamFraction(distributionScale.samples[0], distributionScale.cap) < .25, 'ordinary posts must remain visibly shorter than archive peaks');
const anchor = {value: 100, heat: .5, fa: 0, lv: .5, L: 200, strands: [{dy: 0, f: 1, a: 1}], ph: .3, per: 3, feather: false};
for (const t of [0, 1000, 100000]) {
  semantics.R.t = t; const marks = []; semantics.paintBeam(anchor, (...args) => marks.push(args));
  assert.equal(marks[0][2], 200, 'animation must not change the data length');
  assert.ok(marks.every(m => m[0] + m[2] <= 207.71), 'packets and flares must not extend the data tail');
}
const strongMarks = [];
semantics.paintBeam({...anchor, heat: .98, live: true}, (...args) => strongMarks.push(args));
assert.ok(strongMarks.some(m => m[4] === 856 && m[2] === anchor.L), 'gold must consistently identify the selected metric top tier');
assert.ok(strongMarks.some(m => m[4] === 8 && m[7] === 40 && m[2] < anchor.L), 'a gold stream post keeps a short vermilion root');
console.log('PASS metric values, tied ranks, fixed square-root scale and stable data tails');

// The OS motion preference must not silently change this project's requested autoplay default.
assert.match(source, /speed: 1, playing: true/);
assert.ok(!source.includes('一诺千金') && !source.includes('灯火长明'), 'remove editorial slogans, keep the name');
// The looks are already in place; the stage measures as the picture plus padding and her name.
const portraitClasses = new Set(), portraitImage = {style: {}, children: [{}]};
const portraitStage = {get offsetHeight() { return parseFloat(portraitImage.style.width) * .823 + 8; }};
const portraitEl = {style: {setProperty(k, v) { this[k] = v; }}, hidden: false, querySelector: () => portraitStage, classList: {
  toggle(name, enabled) { enabled ? portraitClasses.add(name) : portraitClasses.delete(name); },
  remove(name) { portraitClasses.delete(name); }, add(name) { portraitClasses.add(name); }
}};
const portraitR = {W: 1224, H: 540, cx: 140, Ri: 289, portrait: false, playing: true, lowq: false, holds: new Set()};
const portraitContext = vm.createContext({R: portraitR, META: {uid: 2094031249}, HAS_PORTRAIT: true, POSTS: [{}], state: {view: 'ring'},
  document: {hidden: false}, $: selector => selector === '#hinome-shrine' ? portraitEl : selector === '#portrait-looks' ? portraitImage : {},
  clamp: (v, a, b) => Math.max(a, Math.min(b, v)), performance: {now: () => 100},
  requestAnimationFrame: () => 1, cancelAnimationFrame() {}, loop() {}});
vm.runInContext(extract('fitShrine'), portraitContext);
portraitContext.fitShrine();
const desktopWidth = parseFloat(portraitEl.style.width);
assert.ok(desktopWidth >= 300 && desktopWidth <= 340, 'desktop portrait is about twice its former visible width');
assert.ok(portraitR.shrineRight < portraitR.cx + portraitR.Ri, 'keep the portrait inside the dial');
{ const top = parseFloat(portraitEl.style.top), portraitHeight = portraitStage.offsetHeight;
  assert.ok(top >= 16 && top + portraitHeight + 70 + 148 <= portraitR.H - 16, 'portrait, ledger and letter all fit inside the dial');
  assert.ok(Math.abs(portraitR.letterTip[1] - (top + portraitHeight + 70 + 74)) < 1e-9, 'the thread leaves the middle of the letter, below the ledger');
  portraitR.visH = 480; portraitContext.fitShrine();   // a 900 px window shows 480 px of the dial before scrolling
  const seenTop = parseFloat(portraitEl.style.top), seenHeight = portraitStage.offsetHeight + 70 + 148;
  assert.ok(seenTop >= 16 && seenTop + seenHeight <= 480 - 14, 'portrait, ledger and letter are all visible without scrolling');
  assert.ok(parseFloat(portraitImage.style.width) >= 230, 'the portrait shrinks only a little');
  delete portraitR.visH; portraitContext.fitShrine(); }
for (const width of [281, 351, 430]) {
  Object.assign(portraitR, {W: width, H: 700, portrait: true}); portraitContext.fitShrine();
  const w = parseFloat(portraitEl.style.width), left = parseFloat(portraitEl.style.left), top = parseFloat(portraitEl.style.top);
  const imageWidth = parseFloat(portraitImage.style.width);
  assert.ok(imageWidth >= 84 && imageWidth <= 104 && imageWidth < desktopWidth / 2.5);
  assert.ok(w - imageWidth >= 160, "the letter sits beside a compact portrait");
  assert.ok(left >= 0 && left + w <= width);
  const ledgerRight = left + parseFloat(portraitEl.style['--ledger-w']), ledgerBottom = top + 108 + 6 + 50;
  assert.ok(top + 108 <= 116 && portraitR.letterTip[1] <= 121, 'the portrait and letter row ends near the top');
  assert.ok(portraitR.letterTip[0] - ledgerRight >= 60, 'the thread to the beam starts well to the right of the ledger');
  assert.ok(ledgerBottom <= 176, 'the ledger stays above the dial band');
}
portraitContext.HAS_PORTRAIT = false; portraitContext.fitShrine(); assert.equal(portraitStage.hidden, true); assert.equal(portraitEl.hidden, false);
console.log('PASS default autoplay and responsive portrait sizing');

// Manual seeking remains useful while paused; rapid updates must not keep restarting the paper flip.
const letterNodes = Object.fromEntries(['#now', '#now-when', '#now-type', '#now-txt', '#letter-stamp'].map(k => [k, {dataset: {}, textContent: ''}]));
let letterTime = 0;
const letterContext = vm.createContext({tr, state: {lang: 'zh'}, R: {playing: false, drag: false}, document: {hidden: false},
  $: k => letterNodes[k], performance: {now: () => letterTime}, fdate: t => String(t), tzName: () => 'JST',
  fnum: n => n == null ? '—' : String(n), isLiveNotice: p => p.type === 'live'});
vm.runInContext([/const postText = [^\n]+/, /const STAMP_JA = [^\n]+/, /const letterStamp = [^\n]+/].map(re => source.match(re)[0]).join('\n') + '\n' + extract('setNow'), letterContext);
letterContext.setNow({id: 'a', ts: 1, text: '<img onerror=bad()>', stats: {like: 0}});
assert.equal(letterNodes['#now-txt'].textContent, '<img onerror=bad()>', 'content stays text, never HTML');
assert.equal(letterNodes['#now'].dataset.turn, undefined);
letterTime = 700; letterContext.setNow({id: 'b', ts: 2, zh: '已校订', text: '原文', type: 'live'});
assert.equal(letterNodes['#now'].dataset.turn, '1', 'paused manual selection still turns the page');
assert.equal(letterNodes['#now-txt'].textContent, '已校订'); assert.equal(letterNodes['#letter-stamp'].textContent, '开播');
letterTime = 750; letterContext.setNow({id: 'c', ts: 3, title: '一张图片'});
assert.equal(letterNodes['#now'].dataset.turn, '1', 'throttle rapid page flips without dropping selected content');
assert.equal(letterNodes['#now'].dataset.postId, 'c'); assert.equal(letterNodes['#now-txt'].textContent, '一张图片');
letterTime = 1500; letterContext.setNow({id: 'c', ts: 3}); assert.equal(letterNodes['#now'].dataset.turn, '1');
letterContext.R.drag = true; letterContext.setNow({id: 'd', ts: 4}); assert.equal(letterNodes['#now'].dataset.turn, '1');
letterContext.setNow({id: 'e', ts: 5, tags: ['直播预告']});
assert.equal(letterNodes['#letter-stamp'].textContent, '预告');
assert.match(source, /animation:letter-fade-a/);
assert.match(source, /animation:letter-fade-b/);
console.log('PASS letter selection, safe text, paused seeking and bounded flip animation');

// Jumping while paused must not leave a fortune card from the previous date.
let removedCards = 0, seekPaints = 0;
const seekContext = vm.createContext({R: {raf:0, kuji:[{el:{remove(){removedCards++;}}}], hover:{}},
  hideTip(){}, wrapA:x=>x, dWrap:x=>x, renderOnce(){seekPaints++;}, performance:{now:()=>900}});
vm.runInContext(extract('seekTo'), seekContext);
seekContext.seekTo(2, 1400);
assert.equal(removedCards,1); assert.equal(seekContext.R.kuji.length,0);
assert.equal(seekContext.R.hover,null); assert.equal(seekContext.R.b,2); assert.equal(seekPaints,1);
seekContext.R.raf=1; seekContext.R.t=900;
seekContext.seekTo(3,400);
assert.equal(seekContext.R.seek.delta,1); assert.equal(seekContext.R.seek.dur,400);
// The recording mode's HANE.seek cuts through the same jumps, paused or playing.
const card = () => ({el:{remove(){removedCards++;}}});
const filmContext = vm.createContext({R: {raf:0, kuji:[card()], hover:{}, anchors:[{b:1, p:{ts:100}}, {b:2, p:{ts:200}}]}, state:{tz:0},
  hideTip(){}, wrapA:x=>x, dWrap:x=>x, renderOnce(){}, dialRedraw(){}, fdate:String, performance:{now:()=>900}});
vm.runInContext(['seekTo', 'dialMove', 'filmSeek'].map(extract).join('\n'), filmContext);
removedCards = 0; filmContext.filmSeek(150, 0);
assert.equal(removedCards,1); assert.equal(filmContext.R.b,2+1e-7);
filmContext.R.raf=1; filmContext.R.kuji=[card()]; filmContext.filmSeek(50, 0);
assert.equal(removedCards,2); assert.equal(filmContext.R.seek,null); assert.equal(filmContext.R.b,1+1e-7);
console.log('PASS paused and playing seek, and recording-mode cuts, clear stale fortune cards');

// Rebuilding a panel keeps keyboard focus on the matching new control instead of dropping it.
function fakeButton(text, label) {
  return {tagName: 'BUTTON', textContent: text, focused: false, blurred: false, getAttribute: k => k === 'aria-label' ? label || null : null,
    focus() { this.focused = true; focusDoc.activeElement = this; }, blur() { this.blurred = true; focusDoc.activeElement = focusDoc.body; }};
}
const focusDoc = {body: {}, activeElement: null};
const oldButton = fakeButton('评论'), host = {kids: [oldButton], contains(el) { return this.kids.includes(el); },
  replaceChildren(...k) { this.kids = k; }, querySelectorAll() { return this.kids; }};
focusDoc.activeElement = oldButton;
const focusCtx = vm.createContext({document: focusDoc});
vm.runInContext(source.match(/const focusKey = [^\n]+/)[0] + '\n' + extract('rebuild'), focusCtx);
const twin = fakeButton('评论'), other = fakeButton('赞');
focusCtx.rebuild(host, other, twin);
assert.ok(oldButton.blurred, 'blur before the focused control is removed');
assert.ok(twin.focused && focusDoc.activeElement === twin, 'focus moves to the rebuilt twin');
focusDoc.activeElement = focusDoc.body; const untouched = fakeButton('评论'); focusCtx.rebuild(host, untouched);
assert.ok(!untouched.focused, 'a rebuild never pulls focus in from outside');

// In the seam the latest post stays current until the playhead is nearer 始; the first post follows.
const seam = vm.createContext({TAU: Math.PI * 2, wrapA: a => ((a % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI), dWrap: a => a, passed() {},
  R: {anchors: [{b: .1}, {b: 2}, {b: 5.8}], total: 5.9, b: 0, seek: null, drag: false, playing: false, t: 0}});
vm.runInContext(['idxAt', 'advance'].map(extract).join('\n'), seam);
for (const [b, cur] of [[.05, 0], [1, 0], [3, 1], [5.85, 2], [5.95, 2], [6.2, 0]]) { seam.R.b = b; seam.advance(0); assert.equal(seam.R.cur, cur, `playhead at ${b}`); }
seam.R.anchors = []; seam.R.b = 1; seam.advance(0); assert.equal(seam.R.cur, -1);
assert.match(source, /R\.b = !R\.anchors\.length \? 0 : Math\.max\(0, R\.anchors\[0\]\.b - 0\.015\)/, 'loading never starts on the latest post');
const months = vm.createContext({TAU: Math.PI * 2, clamp: (v, a, b) => Math.max(a, Math.min(b, v)), moved: [],
  R: {months: [{s: 0, e: 1}, {s: 1, e: 2}, {s: 2, e: 3}], total: 3, b: 6.2}});
vm.runInContext(extract('dialMonth') + '\nfunction dialMove(b) { moved.push(b); }', months);
months.dialMonth(1); assert.equal(months.moved.pop(), .5, 'next month from the lead-in is the first month');
months.dialMonth(-1); assert.equal(months.moved.pop(), 2.5, 'previous month from the lead-in wraps to the last');
months.R.b = 3.1; months.dialMonth(1); assert.equal(months.moved.pop(), 2.5, 'just past 今 stays on the last month');
months.R.b = 1.5; months.dialMonth(1); assert.equal(months.moved.pop(), 2.5); months.dialMonth(-1); assert.equal(months.moved.pop(), .5);
const glides = []; months.seekTo = (b, dur) => glides.push([b, dur]); months.wrapA = a => ((a % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
months.R.raf = 1; months.R.b = .4; months.dialMonth(1); assert.deepEqual(glides.pop(), [1.5, 520], 'playing: the month buttons glide');
months.R.seek = {from: .4, delta: 1.1}; months.dialMonth(1); assert.deepEqual(glides.pop(), [2.5, 520], 'a second press counts from where the glide is going');
months.R.raf = 0; months.R.seek = null; assert.equal(months.moved.length, 0);

// The toolbar follows the dial's month, including months without posts and the gap between loops.
const scrubEls = new Map();
const scrubEl = key => { if (!scrubEls.has(key)) scrubEls.set(key, {style: {}, setAttribute() {}}); return scrubEls.get(key); };
const scrub = vm.createContext({tr, $: scrubEl, cFx: scrubEl('canvas'), p2: n => String(n).padStart(2, '0'), scrubX: b => b / 4,
  R: {b: 0, bmax: 4, thv: .4, scrubWidth: 400, months: [{s: 0, e: 1, y: 2025, m: 12}, {s: 1, e: 2, y: 2026, m: 1, posts: []}]}});
vm.runInContext(extract('updateScrub'), scrub);
for (const [b, label] of [[0, '2025年12月'], [1, '2026年01月'], [1.5, '2026年01月'], [2, '2026年01月'], [2.5, '2026年01月']]) {
  scrub.R.b = b; scrub.updateScrub(); assert.equal(scrubEl('#dial-month').textContent, label);
}
scrub.R.months = []; scrub.updateScrub(); assert.equal(scrubEl('#dial-month').textContent, '—');

// One time-zone switch invalidates every view that groups or prints times.
const zoneCalls = {saved: 0, header: 0};
const zone = vm.createContext({state: {tz: 9}, built: {stats: true, archive: true}, R: {tex: {}, focusPost: {}},
  remember() { zoneCalls.saved++; }, renderHeader() { zoneCalls.header++; }});
vm.runInContext(extract('setTz'), zone);
zone.setTz(9); assert.equal(zoneCalls.saved, 0, 'same zone: nothing to rebuild');
zone.setTz(8); assert.equal(zone.state.tz, 8); assert.equal(zone.built.stats, false); assert.equal(zone.built.archive, false);
assert.equal(zone.R.tex, null, 'the dial month cards are redrawn'); assert.equal(zone.R.focusPost, null);
assert.equal(zoneCalls.saved, 1); assert.equal(zoneCalls.header, 1);
console.log('PASS focus-safe rebuilds, seam and lead-in navigation, one time-zone switch for every view, vermilion roots under gold');

// Kobuta: one recorded gait cycle stepped by distance, a closed lap, fitted drops, and a pet that is always shown and always running.
const pigMath = vm.createContext({clamp: (v, a, b) => Math.max(a, Math.min(b, v))});
vm.runInContext(source.match(/const PIG = [^\n]+/)[0] + '\n' + ['pigFrame', 'pigTrack', 'pigFit'].map(extract).join('\n'), pigMath);
const PIG = vm.runInContext('PIG', pigMath);
assert.equal(PIG.frames, 22); assert.equal(PIG.lift.length, PIG.frames);
assert.ok(PIG.steps.every(f => Number.isInteger(f) && f >= 0 && f < PIG.frames));
const sheet = fs.readFileSync(require('node:path').join(__dirname, '../hinome/assets/kobuta-v3.png'));
assert.equal(sheet.readUInt32BE(16), 22 * 144, 'the sheet holds exactly the 22 looped frames'); assert.equal(sheet.readUInt32BE(20), 200);
assert.ok(fs.existsSync(require('node:path').join(__dirname, '../hinome/assets/kobuta-v3.webp')));
assert.match(source, /url\("assets\/kobuta-v3\.png"\) 0 0 \/ 2200% 100%/);
assert.ok(!/kobuta-run\.|pet-toggle|pet-rest|pet-hide|pet-visible/.test(source), 'no separate switch, rest button or old sheet');
assert.equal(pigMath.pigFrame(10 * 21.99, 10), 21); assert.equal(pigMath.pigFrame(10 * 22, 10), 0, 'frame 21 flows straight into frame 0');
assert.equal(pigMath.pigFrame(-0.01, 10), 21); assert.equal(pigMath.pigFrame(10 * 22 * 1000 + 35, 10), 3);
const track = {ls: 210, r: 36, persp: .34}, lap = 2 * track.ls + 2 * Math.PI * track.r;
let prev = pigMath.pigTrack(0, track), turns = 0;
for (let i = 1; i <= 4000; i++) {
  const p = pigMath.pigTrack(lap * 2 * i / 4000, track);
  assert.ok(Math.hypot(p.x - prev.x, (p.y - prev.y) / track.persp) <= lap * 2 / 4000 + 1e-9, 'the lap has no jumps');
  if (p.hx * prev.hx < 0) turns++; prev = p;
}
assert.equal(turns, 4, 'two turns per lap');
for (const s of [0, 37.5, 250, 401, 600]) {
  const a = pigMath.pigTrack(s, track), b = pigMath.pigTrack(s + lap, track);
  assert.ok(Math.abs(a.x - b.x) < 1e-9 && Math.abs(a.y - b.y) < 1e-9, 'the path closes on itself');
}
const front = pigMath.pigTrack(20, track), back = pigMath.pigTrack(track.ls + Math.PI * track.r + 20, track);
assert.equal(front.hx, -1); assert.equal(front.depth, 0); assert.ok(front.y > 0, 'the near side runs left, as recorded');
assert.equal(back.hx, 1); assert.equal(back.depth, 1); assert.ok(back.y < 0, 'the far side runs right, mirrored and higher');
assert.equal(JSON.stringify(pigMath.pigTrack(5, {ls: 0, r: 0, persp: .34})), '{"x":0,"y":0,"depth":0,"hx":-1,"lap":0}', 'an empty track never yields NaN');
const fitBox = {x0: 200, x1: 1200, y0: 300, y1: 800};
let fit = pigMath.pigFit(600, 500, 30, track, fitBox, 0), fp = pigMath.pigTrack(fit.s, track);
assert.equal(fit.s, 30, 'a drop with room keeps its place on the lap');
assert.ok(Math.hypot(fit.cx + fp.x - 600, fit.cy + fp.y - 500) < 1e-9, 'and lands exactly where it was let go');
fit = pigMath.pigFit(600, 500, track.ls + Math.PI * track.r + 20, track, fitBox, -900);
assert.ok(pigMath.pigTrack(fit.s, track).hx < 0, 'a leftward fling carries on along a leftward stretch');
const half = track.ls / 2 + track.r, rise = track.r * track.persp;
for (let x = fitBox.x0 - half; x <= fitBox.x1 + half; x += 37) for (let y = fitBox.y0 - rise; y <= fitBox.y1 + rise; y += 23) {
  const f = pigMath.pigFit(x, y, 100, track, fitBox, 0), q = pigMath.pigTrack(f.s, track);
  assert.ok(f.cx >= fitBox.x0 && f.cx <= fitBox.x1 && f.cy >= fitBox.y0 && f.cy <= fitBox.y1, 'the whole lap stays on screen');
  assert.ok(Math.hypot(f.cx + q.x - x, f.cy + q.y - y) <= rise + lap / 48, 'a drop near an edge moves only a little');
}
console.log('PASS Kobuta seamless 22-frame cycle, distance-stepped frames, closed lap and fitted drops');

function pigScene(options = {}) {
  const clock = {t: 1000}, frames = new Map(), winEvents = {}, docEvents = {}, animations = []; let seq = 0;
  const store = new Map(Object.entries(options.saved || {})), removed = [];
  const element = () => { const el = {hidden: false, dataset: {}, style: {setProperty(k, v) { this[k] = v; }}, textContent: '', kids: [], events: {}, attrs: {}, captured: null, clientWidth: 1440, clientHeight: 900,
    replaceChildren(...k) { this.kids = k; this.textContent = k.map(c => c.textContent).join(''); },
    setAttribute(k, v) { this.attrs[k] = v; }, addEventListener(k, fn) { (this.events[k] ||= []).push(fn); },
    fire(k, e = {}) { for (const fn of this.events[k] || []) fn({preventDefault() {}, isPrimary: true, button: 0, pointerType: 'mouse', pointerId: 1, clientX: 0, clientY: 0, ...e}); },
    append(c) { this.kids.push(c); c.parent = this; }, remove() { if (this.parent) this.parent.kids.splice(this.parent.kids.indexOf(this), 1); },
    get childElementCount() { return this.kids.length; },
    setPointerCapture(id) { this.captured = id; }, hasPointerCapture(id) { return this.captured === id; }, releasePointerCapture() { this.captured = null; }};
    el.classList = {set: new Set(), add(k) { this.set.add(k); }, remove(k) { this.set.delete(k); }, contains(k) { return this.set.has(k); }};
    if (!options.noAnimate) el.animate = frames => { const a = {frames}; animations.push(a); return a; };
    return el; };
  const nodes = Object.fromEntries(['kobuta', 'kobuta-pet', 'kobuta-body', 'kobuta-sprite', 'kobuta-shadow', 'kobuta-bubble'].map(k => ['#' + k, element()]));
  nodes['#kobuta'].hidden = true;
  [nodes['#kobuta-shadow'], nodes['#kobuta-pet']].forEach(n => nodes['#kobuta'].append(n));
  const reduced = {matches: !!options.reduced};
  const doc = {hidden: false, addEventListener(k, fn) { docEvents[k] = fn; }, createElement: () => element()};
  const blocked = () => { if (options.storageBlocked) throw Error('blocked'); };
  const ctx = vm.createContext({$: s => nodes[s], document: doc, R: {lowq: false}, clamp: (v, a, b) => Math.max(a, Math.min(b, v)),
    matchMedia: () => reduced, innerWidth: 1440, innerHeight: 900, performance: {now: () => clock.t},
    getComputedStyle: () => ({getPropertyValue: k => k === '--pig-w' ? ' 88px' : '0px'}),
    localStorage: {getItem(k) { blocked(); return store.has(k) ? store.get(k) : null; }, setItem(k, v) { blocked(); store.set(k, String(v)); }, removeItem(k) { blocked(); removed.push(k); store.delete(k); }},
    requestAnimationFrame(fn) { frames.set(++seq, fn); return seq; }, cancelAnimationFrame(id) { frames.delete(id); },
    addEventListener(k, fn) { winEvents[k] = fn; }});
  vm.runInContext(source.match(/const PIG = [^\n]+/)[0] + '\n' + ['pigFrame', 'pigTrack', 'pigFit', 'initKobuta'].map(extract).join('\n'), ctx);
  ctx.initKobuta();
  const run = (ms = 1000, step = 17) => { for (let t = 0; t < ms; t += step) { clock.t += step; const [id, fn] = [...frames][0] || []; if (!fn) return; frames.delete(id); fn(clock.t); } };
  const at = () => { const m = /translate3d\(([-\d.]+)px,([-\d.]+)px/.exec(nodes['#kobuta-pet'].style.transform); return [+m[1], +m[2]]; };
  const fx = () => nodes['#kobuta'].kids.filter(k => k !== nodes['#kobuta-shadow'] && k !== nodes['#kobuta-pet']);
  return {ctx, nodes, clock, frames, winEvents, docEvents, animations, store, removed, reduced, run, at, fx, pet: nodes['#kobuta-pet']};
}
let pig = pigScene({saved: {'hane-kobuta': 'hidden'}});
assert.equal(pig.nodes['#kobuta'].hidden, false, 'shown by default, and the old hide preference is ignored');
assert.ok(pig.removed.includes('hane-kobuta')); assert.equal(pig.frames.size, 1);
let from = pig.at(), seen = new Set();
for (let i = 0; i < 80; i++) { pig.run(17); seen.add(pig.nodes['#kobuta-sprite'].style.backgroundPosition); }
assert.ok(Math.hypot(pig.at()[0] - from[0], pig.at()[1] - from[1]) > 50, 'it keeps running'); assert.equal(seen.size, 22, 'every frame of the cycle is used');
assert.ok(pig.fx().length > 0, 'footsteps raise dust');
for (let i = 0; i < 3; i++) { pig.ctx.document.hidden = true; pig.docEvents.visibilitychange(); assert.equal(pig.frames.size, 0); pig.ctx.document.hidden = false; pig.docEvents.visibilitychange(); }
pig.docEvents.visibilitychange(); assert.equal(pig.frames.size, 1, 'resuming never starts a second loop');
pig.winEvents.pagehide(); assert.equal(pig.frames.size, 0); pig.winEvents.pageshow(); assert.equal(pig.frames.size, 1);
pig.ctx.R.playing = false; from = pig.at(); pig.run(300); assert.notDeepEqual(pig.at(), from, 'pausing the dial does not stop the pig');
// a tap pats: bubble and hearts, with a hop
const tapAt = pig.at(); pig.pet.fire('pointerdown', {clientX: tapAt[0] + 44, clientY: tapAt[1] + 60}); pig.pet.fire('pointerup', {clientX: tapAt[0] + 44, clientY: tapAt[1] + 60});
let before = pig.fx().length; pig.pet.fire('click'); pig.run(34);
const bubble = pig.nodes['#kobuta-bubble'], lit = () => bubble.kids.filter(w => w.classList.contains('on')).length;
assert.ok('say' in pig.pet.dataset); assert.equal(JSON.stringify(PIG.chant), JSON.stringify(['火羽', 'こぶた', 'こぶた', 'こぶた', 'こぶた']));
assert.equal(bubble.textContent, '火羽こぶたこぶたこぶたこぶた', 'it says her closing chant'); assert.equal(lit(), 1, '火羽 comes first, on the upbeat');
assert.ok(bubble.kids[0].className.includes('name') && bubble.kids.every(w => w.className.includes('pig-word')));
assert.ok(pig.animations.some(a => /scale\(\.3\)/.test(a.frames[0].transform)) && pig.fx().length > before, 'hearts rise');
const notes = () => pig.fx().filter(k => /♪|♫/.test(k.textContent)).length;
assert.equal(notes(), 0); pig.run(300); assert.equal(lit(), 2, 'one こぶた per beat'); assert.ok(notes() >= 1, 'each こぶた comes with a note');
pig.run(300); assert.equal(lit(), 3);
pig.pet.fire('click'); pig.run(17); assert.equal(lit(), 3, 'a pat during the chant does not restart it');
pig.run(600); assert.equal(lit(), 5, 'four こぶた in all');
const rhythm = PIG.chant.length * PIG.beat; assert.ok(PIG.beat >= 250 && PIG.beat <= 400 && rhythm < 2000, 'a brisk beat');
pig.run(1400); assert.ok(!('say' in pig.pet.dataset), 'the bubble goes away after the last word');
// a 大吉 card on the dial makes it cheer, but not for every card
assert.match(source, /if \(f === "大吉"\) document\.dispatchEvent\(new CustomEvent\("hane-daikichi"\)\)/);
pig.docEvents['hane-daikichi'](); assert.equal(pig.nodes['#kobuta-bubble'].textContent, '火羽こぶたこぶたこぶたこぶた');
pig.run(3000); pig.nodes['#kobuta-bubble'].textContent = ''; pig.docEvents['hane-daikichi']();
assert.equal(pig.nodes['#kobuta-bubble'].textContent, '', 'at most one cheer every 25 s');
assert.equal(typeof pig.docEvents['hane-ring-end'], 'function', 'playback reaching the newest post also cues the chant');
pig.clock.t += 25000; pig.run(17); pig.docEvents['hane-ring-end'](); assert.equal(pig.nodes['#kobuta-bubble'].textContent, '火羽こぶたこぶたこぶたこぶた');
pig.run(3000);
// drag anywhere: the grabbed point follows the pointer, a still release drops in place, and the spot is kept
let p0 = pig.at(); const gx = p0[0] + 44, gy = p0[1] + 60;
pig.pet.fire('pointerdown', {clientX: gx, clientY: gy}); pig.pet.fire('pointermove', {clientX: gx - 3, clientY: gy});
pig.run(17); assert.ok(!pig.pet.classList.contains('held'), 'a small wobble is still a tap');
pig.pet.fire('pointermove', {clientX: 400, clientY: 300}); pig.run(170);
assert.ok(pig.pet.classList.contains('held')); assert.equal(pig.nodes['#kobuta-bubble'].textContent, 'こぶっ!?');
let held = pig.at(); assert.ok(Math.abs(held[0] + 44 - 400) < 1 && Math.abs(held[1] + 60 - 300) < 1, 'the grabbed point stays under the pointer');
assert.ok(/scale\(-?[\d.]+,[\d.]+\)/.test(pig.nodes['#kobuta-body'].style.transform));
pig.clock.t += 250; pig.pet.fire('pointerup', {clientX: 400, clientY: 300}); pig.pet.fire('click');
assert.equal(pig.nodes['#kobuta-bubble'].textContent, 'こぶっ!?', 'the click ending a drag is not a pat');
pig.run(400); let spot = JSON.parse(pig.store.get('hane-kobuta-spot'));
assert.ok(Number.isFinite(spot.x) && Number.isFinite(spot.t) && Number.isFinite(spot.s), 'the new spot is remembered');
const track2 = {ls: 210, r: 36, persp: .34}, landed = pigMath.pigTrack(spot.s, track2);
assert.ok(Math.abs(spot.x * 1440 + landed.x - 400) < 2, 'a still release lands where it was let go');
// a fling flies, stays on screen, bounces and lands
p0 = pig.at(); pig.pet.fire('pointerdown', {clientX: p0[0] + 44, clientY: p0[1] + 60});
for (let i = 1; i <= 6; i++) { pig.clock.t += 16; pig.pet.fire('pointermove', {clientX: p0[0] + 44 - 60 * i, clientY: p0[1] + 60}); }
pig.pet.fire('pointerup', {clientX: p0[0] + 44 - 360, clientY: p0[1] + 60});
for (let i = 0; i < 120; i++) { pig.run(17); const [x, y] = pig.at(); assert.ok(x >= 0 && x + 88 <= 1440 && y >= 0 && y + 122.3 <= 900, 'never leaves the screen'); }
spot = JSON.parse(pig.store.get('hane-kobuta-spot'));
assert.ok(spot.x * 1440 + pigMath.pigTrack(spot.s, track2).x < p0[0] + 44 - 100, 'the fling carried it left');
// keyboard: arrows hop to a new place, Enter pats through the button's click
from = pig.at(); pig.pet.fire('keydown', {key: 'ArrowUp'}); pig.run(500); assert.ok(pig.at()[1] < from[1] - 30);
// the saved spot is restored on the next visit
const again = pigScene({saved: {'hane-kobuta-spot': JSON.stringify({x: .25, t: 400, s: 50})}}), back50 = pigMath.pigTrack(50, track2);
assert.ok(Math.abs(again.at()[0] + 44 - (.25 * 1440 + back50.x)) < 1, 'it returns to where it was dropped');
// a long chant shifts sideways to stay on screen, wherever the pig runs
const edge = pigScene(); edge.nodes['#kobuta-bubble'].offsetWidth = 220; edge.pet.fire('click');
for (let i = 0; i < 60; i++) {
  edge.run(34); const x = edge.at()[0] + 44, dx = parseFloat(edge.nodes['#kobuta-bubble'].style['--say-dx'] || '0');
  assert.ok(x - 110 + dx >= 5.9 && x + 110 + dx <= 1440 - 5.9, 'the bubble stays inside the window');
}
// reduced motion keeps it running but without particles, hops or squash; the words still arrive on the beat
const calm = pigScene({reduced: true}); from = calm.at(); calm.run(600); assert.notDeepEqual(calm.at(), from);
calm.pet.fire('click'); calm.run(100); assert.equal(calm.fx().length, 0); assert.ok('say' in calm.pet.dataset);
calm.run(700); assert.equal(calm.nodes['#kobuta-bubble'].kids.filter(w => w.classList.contains('on')).length, 3); assert.equal(calm.fx().length, 0, 'no notes');
assert.match(calm.nodes['#kobuta-body'].style.transform, /rotate\(0\.00deg\) scale\(-?1\.000,1\.000\)$/, 'no tilt or squash');
// blocked storage and missing animation support never break the pet
const locked = pigScene({storageBlocked: true, noAnimate: true}); locked.run(200); locked.pet.fire('click');
let lp = locked.at(); locked.pet.fire('pointerdown', {clientX: lp[0] + 40, clientY: lp[1] + 50}); locked.pet.fire('pointermove', {clientX: 300, clientY: 300});
locked.run(50); locked.clock.t += 200; locked.pet.fire('pointerup', {clientX: 300, clientY: 300}); locked.run(500); assert.equal(locked.fx().length, 0);
assert.match(source, /\.kobuta-layer \{[^}]*pointer-events:none/);
assert.match(source, /\.kobuta-pet \{[^}]*pointer-events:auto[^}]*touch-action:none/);
assert.match(source, /<div class="kobuta-layer" id="kobuta" hidden>/, 'the pet stays hidden when the page has no data or no script');
assert.match(source, /@media \(prefers-reduced-motion:reduce\) \{ \.pig-word\.on \{ animation:none; \} \}/, 'reduced motion: the words light up without popping');
console.log('PASS Kobuta always on: endless run, pause-safe loop, pats, drag, fling, keyboard, restore, reduced motion and storage failures');

// Holds: reading a post, or resting on content that changes with playback, pauses the dial for a while only.
// Closing the post resumes from the same spot; an explicit pause stays a pause.
{
  const shrine = {classList: {add() {}, remove() {}}}, frames = [];
  const R = {playing: true, raf: 0, seek: null, holds: new Set()};
  const holds = vm.createContext({R, state: {view: 'ring'}, document: {hidden: false, activeElement: null, body: {}}, $: () => shrine,
    performance: {now: () => 0}, requestAnimationFrame: fn => { frames.push(fn); return frames.length; }, cancelAnimationFrame() {}, loop() {}});
  vm.runInContext(['ringStart', 'ringStop'].map(name => source.match(new RegExp(`function ${name}\\(\\) \\{[^\\n]+`))[0]).join('\n') + '\n' +
    source.match(/function holdRing\([^\n]+/)[0] + '\n' + source.match(/function releaseRing\([^\n]+/)[0] + '\n' + source.match(/function dropRests\([^\n]+/)[0], holds);
  holds.ringStart(); assert.ok(R.raf > 0, 'playing by default');
  holds.holdRing('drawer'); assert.equal(R.raf, 0, 'an open post holds the dial');
  holds.ringStart(); assert.equal(R.raf, 0, 'nothing restarts it while held');
  holds.releaseRing('drawer'); assert.ok(R.raf > 0, 'closing resumes playback');
  holds.holdRing('hover0'); holds.holdRing('drawer'); holds.releaseRing('drawer'); assert.equal(R.raf, 0, 'another hold still applies');
  R.holds.add('focus1'); holds.dropRests(); assert.equal(R.holds.size, 0, 'pointer and keyboard rests both go'); holds.releaseRing('hover0'); assert.equal(R.raf, 0, 'releasing a dropped hold is a no-op');
  holds.ringStart(); assert.ok(R.raf > 0);
  R.seek = {}; holds.holdRing('drawer'); assert.ok(R.raf > 0, 'a glide in flight lands before the hold freezes it (see loop)'); R.seek = null;
  holds.releaseRing('drawer'); R.playing = false; holds.ringStop(); holds.holdRing('drawer'); holds.releaseRing('drawer');
  assert.equal(R.raf, 0, 'a manual pause survives opening and closing a post');
  // the drawer: open holds, close drops pointer holds, restores focus without a new hold, then resumes
  const focusLog = [], ret = {isConnected: true, focus() { focusLog.push(holds.restoringFocus); }};
  const drawerEl = {hidden: true, focus() {}};
  Object.assign(holds, {drawer: drawerEl, drawerReturn: null, restoringFocus: false});
  vm.runInContext('var drawerReturn = null, restoringFocus = false;\n' + ['showDrawer', 'closeDrawer'].map(extract).join('\n'), holds);
  R.playing = true; holds.ringStart(); holds.document.activeElement = ret;
  holds.showDrawer(); assert.equal(drawerEl.hidden, false); assert.ok(R.holds.has('drawer')); assert.equal(R.raf, 0);
  R.holds.add('hover2'); holds.closeDrawer();
  assert.equal(drawerEl.hidden, true); assert.deepEqual(focusLog, [true], 'focus goes back while restoringFocus is set');
  assert.equal(vm.runInContext('restoringFocus', holds), false); assert.equal(R.holds.size, 0); assert.ok(R.raf > 0, 'closing the post plays on');
  assert.match(source, /\$\("#now"\)\.addEventListener\("click", \(\) => \{ if \(R\.focusPost\) openPost\(R\.focusPost\); \}\);/, 'reading the current post no longer turns playback off');
  assert.ok(!/R\.playing = false; R\.seek = null; ringStop\(\); syncPlayback\(\)/.test(source), 'no hidden permanent pauses');
  assert.match(source, /if \(R\.playing\) \{ R\.holds\.delete\("drawer"\); dropRests\(\); ringStart\(\); \}/, 'pressing play while a post is open plays at once');
}
console.log('PASS holds: an open post or resting pointer pauses for a while, closing resumes in place, manual pause persists, month buttons glide');

// The newest post is the end of the broadcast: the dial tells Kobuta, once per pass.
{
  const sent = [], last = {q: 0, value: 0, lv: 0}, other = {q: 0, value: 0, lv: 0};
  const end = vm.createContext({R: {flare: new Map(), lowq: false, t: 0, lastKuji: 0, anchors: [other, last]}, spawnSpark() {}, showKuji() {},
    document: {dispatchEvent: e => sent.push(e.type)}, CustomEvent: class { constructor(type) { this.type = type; } }});
  vm.runInContext(extract('passed'), end);
  end.passed(other); assert.deepEqual(sent, []); end.passed(last); assert.deepEqual(sent, ['hane-ring-end']);
}

// 帳 ledger: stream counts per month and consecutive nights come from the live archive only; a night runs until 6:00.
{
  const el = () => ({kids: [], dataset: {}, replaceChildren(...k) { this.kids = k; }, get text() { return this.kids.map(x => typeof x === 'string' ? x : x.text).join(''); }});
  const ui = {'#ledger': el(), '#ledger-head': el(), '#ledger-live': el(), '#ledger-night': el()};
  const day = Date.UTC(2023, 4, 20) / 1000 - 9 * 3600;   // 2023-05-20 00:00 JST
  const S = (d, hh, mm, dur) => ({start: day + d * 86400 + hh * 3600 + mm * 60, duration: dur});
  const sessions = [S(-2, 23, 0, 3600), S(-1, 23, 5, 3600), S(0, 23, 2, 6720), S(1, 0, 40, 1800), S(3, 23, 0, 3600)];
  const ledger = vm.createContext({tr, state: {tz: 9}, SESSIONS: sessions, POSTS: [{ts: day - 100 * 86400}], $: k => ui[k],
    h: (tag, attrs, ...kids) => ({tag, text: (attrs || {}).text || kids.flat().map(k => typeof k === 'string' ? k : k ? k.text : '').join(''), cls: (attrs || {}).class})});
  const line = re => source.match(re)[0];
  vm.runInContext([line(/function tp\(ts, tz\) \{[^\n]+/), line(/const p2 = [^\n]+/), line(/const fday = [^\n]+/), line(/const monthKey = [^\n]+/),
    line(/const exact = [^\n]+/), line(/const duration = [^\n]+/), line(/const money = [^\n]+/), extract('liveSum'), extract('liveValue'),
    line(/const LEDGER = [^\n]+/), extract('ledgerIndex'), extract('renderLedger')].join('\n'), ledger);
  const at = (d, hh) => ({ts: day + d * 86400 + hh * 3600});
  ledger.renderLedger(at(0, 15));   // an afternoon post announcing that night's stream
  assert.equal(ui['#ledger-head'].text, '2023 年 5 月自首条动态第 101 天');
  assert.equal(ui['#ledger-live'].text, '本月直播 5 场 · 5.4 h ›', 'the month counts streams in the archive');
  assert.equal(ui['#ledger-night'].text, '当晚 2 场 · 23:02 起 · 2时22分 · 连播第 3 天', 'a stream after midnight still belongs to that night');
  assert.equal(ui['#ledger'].dataset.month, '2023-05');
  ledger.renderLedger(at(1, 3)); assert.equal(ui['#ledger-night'].text, '当晚 2 场 · 23:02 起 · 2时22分 · 连播第 3 天', '03:00 is still the same night');
  ledger.renderLedger(at(2, 15)); assert.equal(ui['#ledger-night'].text, '当晚没有直播记录', 'a rest night says so, without guessing');
  ledger.renderLedger(at(3, 15)); assert.equal(ui['#ledger-night'].text, '当晚 23:00 开播 · 1时0分', 'a streak of one is not announced');
  ledger.renderLedger({ts: Date.UTC(2023, 7, 1) / 1000}); assert.equal(ui['#ledger-live'].text, '本月没有直播档案 ›'); assert.equal(ui['#ledger-night'].text, '');
  ledger.renderLedger({ts: Date.UTC(2023, 0, 5) / 1000}); assert.equal(ui['#ledger-live'].text, '直播档案从 2023 年 5 月开始 ›', 'before the archive begins, say so');
  const before = ui['#ledger-live'].kids; ledger.renderLedger({ts: Date.UTC(2023, 0, 5) / 1000 + 60}); assert.equal(ui['#ledger-live'].kids, before, 'the same night does not rebuild');
  ledger.state.tz = 8; ledger.renderLedger(at(0, 15)); assert.equal(ui['#ledger-night'].text, '当晚 2 场 · 22:02 起 · 2时22分 · 连播第 3 天', 'Beijing time regroups the nights');
  assert.ok(!/R\.nodes|nodePos|铃＝/.test(source), 'no @-mention bells or names inside the dial');
}
console.log('PASS ledger: archive-only month and night, 6:00 night boundary, honest gaps, zone switch; the end of playback cues Kobuta');
// The LIVE year buttons cover every year with posts, so the ledger's month survives the jump even when the archive lags.
{
  const years = vm.createContext({state: {tz: 9}, POSTS: []});
  vm.runInContext(source.match(/function tp\(ts, tz\) \{[^\n]+/)[0] + '\n' + extract('liveYears'), years);
  const at = (y, m) => Date.UTC(y, m - 1, 15) / 1000;
  assert.equal(years.liveYears(at(2021, 10), at(2025, 12)).join(), '2021,2022,2023,2024,2025', 'no posts: the archive years');
  years.POSTS = [{ts: at(2021, 2)}, {ts: at(2026, 5)}];
  assert.equal(years.liveYears(at(2021, 10), at(2025, 12)).join(), '2021,2022,2023,2024,2025,2026', 'posts after the last archived stream keep their year');
  years.POSTS = [{ts: at(2019, 7)}, {ts: at(2022, 1)}];
  assert.equal(years.liveYears(at(2021, 10), at(2025, 12)).join(), '2019,2020,2021,2022,2023,2024,2025', 'and so do posts before the first');
  assert.match(source, /const years = liveYears\(earliest, latest\);\r?\n  if \(!years\.includes\(LV\.year\)\) LV\.year = String\(tp\(latest\)\.y\);/);
}
console.log('PASS LIVE years cover the posts, so a ledger month opens as itself');

// Months without a single archived stream are named as runs next to the totals; the chosen time zone decides the month.
{
  const line = re => source.match(re)[0];
  const ctx = vm.createContext({tr, state: {tz: 9}});
  vm.runInContext([line(/function tp\(ts, tz\) \{[^\n]+/), line(/const p2 = [^\n]+/), line(/const monthKey = [^\n]+/), extract('liveGaps'),
    line(/const gapText = [^\n]+/)].join('\n') + '\nthis.liveGaps = liveGaps; this.text = gapText;', ctx);
  const plain = v => JSON.parse(JSON.stringify(v));   // arrays made inside the context have another prototype
  ctx.gaps = (...a) => plain(ctx.liveGaps(...a));
  const utc = (y, m, d, h = 12, mi = 0) => Date.UTC(y, m - 1, d, h, mi) / 1000;
  const starts = [utc(2021, 10, 5), utc(2023, 8, 31, 15, 30), utc(2025, 7, 26)];   // the second is 00:30 on 1 September in Japan
  assert.deepEqual(ctx.gaps(starts, utc(2021, 2, 1)), [['2021-02', '2021-09'], ['2021-11', '2023-08'], ['2023-10', '2025-06']]);
  ctx.state.tz = 8;
  assert.deepEqual(ctx.gaps(starts, utc(2021, 2, 1)), [['2021-02', '2021-09'], ['2021-11', '2023-07'], ['2023-09', '2025-06']]);
  assert.deepEqual(ctx.gaps([utc(2026, 9, 1), utc(2026, 10, 1)], utc(2026, 9, 2)), [], 'consecutive months leave no gap');
  assert.deepEqual(ctx.gaps([], utc(2021, 2, 1)), [], 'no archive gives no gaps and no endless loop');
  assert.equal(ctx.text([['2024-01', '2024-01'], ['2023-09', '2025-06']]), '2024-01、2023-09 至 2025-06');
}
console.log('PASS LIVE gaps: month runs without streams, time-zone aware, named as ranges');

// The portrait follows her outfit reveals (streams from 22:00 JST on 14 February 2022 and 2023).
{
  const jaStart = source.indexOf('const JA = {'), ctx = vm.createContext({});
  vm.runInContext(source.slice(jaStart, source.indexOf('\n};', jaStart) + 3).replace('const JA', 'this.JA') + '\n' +
    source.match(/const LOOKS = \[[^]*?\];/)[0] + '\n' + source.match(/const lookAt = [^\n]+/)[0] + '\nthis.LOOKS = LOOKS; this.lookAt = lookAt;', ctx);
  const jst = (y, m, d, h, mi = 0) => Date.UTC(y, m - 1, d, h - 9, mi) / 1000;
  assert.equal(ctx.lookAt(jst(2021, 2, 1, 16)), 0);
  assert.equal(ctx.lookAt(jst(2022, 2, 14, 21, 59)), 0, 'the first outfit until the reveal stream starts');
  assert.equal(ctx.lookAt(jst(2022, 2, 14, 22)), 1);
  assert.equal(ctx.lookAt(jst(2023, 2, 14, 21, 59)), 1);
  assert.equal(ctx.lookAt(jst(2026, 10, 15, 1)), 2);
  for (const look of ctx.LOOKS) {
    assert.ok(fs.existsSync(require('node:path').join(__dirname, '../hinome', look.src)), look.src);
    for (const word of [look.outfit, look.hair]) assert.ok(Object.hasOwn(ctx.JA, word), `Japanese caption for ${word}`);
  }
}
console.log('PASS portrait looks switch at the outfit reveals; captions and images exist');

// 奉纳提灯: the playhead month's likes light a square-root share of the lantern rows behind her portrait.
{
  const line = re => source.match(re)[0], plain = v => JSON.parse(JSON.stringify(v));
  const ctx = vm.createContext({});
  vm.runInContext([line(/function rng\(seed\) \{[^\n]+/), line(/const lanternShare = [^\n]+/), line(/const LANTERN_PAD = [^\n]+/),
    source.match(/const LANTERN_ROWS = \[[^]*?\];/)[0], extract('layoutLanterns')].join('\n') + '\nthis.share = lanternShare; this.PAD = LANTERN_PAD;', ctx);
  assert.equal(ctx.share(0, 0), 0); assert.equal(ctx.share(25, 100), 0.5); assert.equal(ctx.share(100, 100), 1); assert.equal(ctx.share(150, 100), 1);
  const [px, py] = ctx.PAD;
  for (const [w, h, label] of [[320, 263, 'desktop'], [100, 82, 'phone']]) {   // her picture's box: 840 x 691
    const L = ctx.layoutLanterns(w, h), hung = L.filter(l => !l.bokeh), named = hung.filter(l => l.w >= 20);
    assert.deepEqual(plain(ctx.layoutLanterns(w, h)), plain(L), 'the same rows every time');
    assert.ok(L.length >= 50 && L.length <= 80, `${label}: ${L.length} lanterns`);
    assert.ok(hung.every(l => l.x - l.w / 2 >= -px * w && l.x + l.w / 2 <= (1 + px) * w && l.y >= -py * h && l.y + l.w * 1.62 <= h),
      `${label}: every lantern hangs inside the backdrop`);
    assert.ok(L.every((l, i) => !i || L[i - 1].s <= l.s), `${label}: painted far to near`);
    assert.ok(hung.filter(l => l.x < 0.3 * w || l.x > 0.7 * w).length >= 12, `${label}: the rows come out beside her, where the cutout is clear`);
    assert.ok(hung.some(l => l.y > 0.45 * h && (l.x < 0.2 * w || l.x > 0.8 * w)), `${label}: a lower pair of rows fills her sides`);
    assert.ok(hung.some(l => l.white) && hung.some(l => !l.white), `${label}: red lanterns and red-and-white ones`);
    assert.ok(label === 'desktop' ? named.length >= 2 : !named.length, `${label}: only lanterns big enough to read carry 火羽 / 奉納`);
    const lit = L.filter(l => l.rank < 0.15).length / L.length;
    assert.ok(lit > 0.05 && lit < 0.3, `${label}: a quiet month lights only a scattered few`);
  }
  const drawRing = extract('drawRing');
  assert.ok(drawRing.indexOf('drawLanterns(') < drawRing.indexOf('drawImage(R.tex'), 'the lanterns hang under the ring');
  assert.match(extract('drawLanterns'), /if \(!HAS_PORTRAIT\) return;/, 'no portrait, no lanterns');
}
console.log('PASS lanterns: square-root share of the busiest month lights the rows behind her portrait');

// Locale changes affect authored UI only; archived text, time zones and playback stay intact.
{
  const localeSource = source.slice(source.indexOf('const state ='), source.indexOf('// Capture static HTML'));
  const makeLocale = saved => {
    const writes = [];
    const ctx = vm.createContext({localStorage: {getItem() { if (saved instanceof Error) throw saved; return saved; }, setItem(k, v) { writes.push([k, v]); }}});
    vm.runInContext(localeSource, ctx);
    return {ctx, writes};
  };
  for (const saved of [null, '{broken', '{"lang":"en"}', new Error('storage blocked')]) {
    const {ctx} = makeLocale(saved);
    assert.equal(vm.runInContext('state.lang', ctx), 'zh');
    assert.equal(ctx.tr('动态环'), '动态环');
  }
  const {ctx, writes} = makeLocale('{"lang":"ja","tz":8}');
  assert.equal(ctx.tr('动态环'), '投稿リング');
  assert.equal(vm.runInContext('state.tz', ctx), 8);
  assert.equal(ctx.tr([' · 搜索「', '」'], '<b>{1}</b>'), ' · 検索「<b>{1}</b>」', 'substitutions remain literal data');
  assert.equal(ctx.tr('unknown text'), 'unknown text');
  assert.equal(ctx.tr('__proto__'), '__proto__');
  for (const [key, value] of Object.entries(vm.runInContext('JA', ctx))) {
    const slots = s => [...s.matchAll(/\{\d+\}/g)].map(m => m[0]).sort().join();
    assert.equal(slots(value), slots(key), `translation must preserve values: ${key}`);
  }
  // A Chinese label edited without its Japanese entry would silently stay Chinese in the Japanese UI.
  const JA = vm.runInContext('JA', ctx);
  const keys = [...source.matchAll(/\btr\("((?:[^"\\]|\\.)*)"\)/g)].map(m => JSON.parse(`"${m[1]}"`))
    .concat([...source.matchAll(/\btr`((?:[^`\\]|\\.)*)`/g)].map(m => { let i = 0; return m[1].replace(/\$\{(?:[^{}]|\{[^{}]*\})*\}/g, () => `{${i++}}`); }));
  assert.ok(keys.length > 100, 'the scan finds the tr() literals');
  assert.deepEqual(keys.filter(k => /[一-鿿]/.test(k) && !Object.hasOwn(JA, k)), [], 'every Chinese tr() literal has a Japanese entry');
  const line = re => source.match(re)[0];
  vm.runInContext([line(/const TYPES = [^\n]+/), line(/const tkey = [^\n]+/), line(/const foreign = [^\n]+/),
    line(/const postText = [^\n]+/), line(/const snippet = [^\n]+/)].join('\n') + '\nthis.body = postText; this.preview = snippet;', ctx);
  const post = {text: '今日も配信！', title: '原題', zh: '今天也开播！', title_zh: '译题', lang: 'ja'};
  assert.equal(ctx.body(post), post.text); assert.equal(ctx.preview(post), '原題 今日も配信！');
  assert.equal(ctx.body({text: '直播', lang: 'zh'}), '直播', 'Chinese originals are not UI labels');
  assert.equal(ctx.body({title: 'Original', lang: 'en'}), 'Original', 'no translated-title fallback in Japanese');
  vm.runInContext([line(/const isLiveNotice = [^\n]+/), line(/const STAMP_JA = [^\n]+/), line(/const letterStamp = [^\n]+/)].join('\n') + '\nthis.stamp = letterStamp;', ctx);
  const tags = [...fs.readFileSync(require('node:path').join(__dirname, '../hinome/translate.py'), 'utf8').match(/LLM_TAGS = \[([^\]]*)\]/)[1].matchAll(/"([^"]+)"/g)].map(m => m[1]);
  for (const tag of tags) assert.match(ctx.stamp({tags: [tag]}), /^[^぀-ヿ]{1,2}$/, `the Japanese letter stamp is never half a kana word: ${tag}`);
  assert.equal(ctx.stamp({tags: ['活动/企划']}), '催事'); assert.equal(ctx.stamp({tags: ['直播预告']}), '予告');
  const calls = [];
  Object.assign(ctx, {ST: {}, built: {}, LEDGER: {key: 'cached'}, R: {b: 1.8, speed: 2, playing: false, tex: {}},
    document: {activeElement: null}, drawer: {hidden: true},
    applyLanguage() { calls.push('apply'); }, renderHeader() {}, renderKey() {}, renderBeamGuide() {}, syncPlayback() {}, syncQuality() {}, setSpeed() {},
    showView(view) { calls.push(view); }});
  vm.runInContext('state.view = "archive";\n' + extract('setLanguage'), ctx);
  ctx.setLanguage('en'); ctx.setLanguage('ja'); assert.equal(writes.length, 0, 'ignore unsupported and unchanged language');
  ctx.setLanguage('zh');
  assert.equal(ctx.body(post), post.zh); assert.equal(ctx.preview(post), '译题 今天也开播！');
  assert.equal(ctx.stamp({tags: ['活动/企划']}), '活动', 'Chinese stamps are unchanged');
  assert.equal(JSON.parse(writes[0][1]).tz, 8); assert.equal(JSON.parse(writes[0][1]).lang, 'zh');
  assert.equal(ctx.R.b, 1.8); assert.equal(ctx.R.playing, false); assert.equal(ctx.R.speed, 2);
  assert.equal(ctx.ST.kw, 'zh'); assert.equal(ctx.LEDGER.key, ''); assert.deepEqual(calls, ['apply', 'archive']);
  ctx.localStorage.setItem = () => { throw new Error('storage blocked'); };
  assert.doesNotThrow(() => ctx.setLanguage('ja'), 'switching works even when preferences cannot be saved');
}
console.log('PASS Chinese/Japanese defaults, persistence, literal originals, translation values and live switching');
