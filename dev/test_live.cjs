// Date clipping and missing-value semantics use the actual shipped frontend functions.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../hinome/template.html'), 'utf8');
const ctx = vm.createContext({exact: n => n == null ? '—' : String(n), money: n => n == null ? '—' : '¥' + n / 100});
for (const name of ['liveSum', 'liveValue', 'liveDayParts']) {
  const match = source.match(new RegExp('function ' + name + '\\([^]*?\\n}'));
  assert.ok(match, name); vm.runInContext(match[0], ctx);
}
const ts = s => Date.parse(s) / 1000;
const s = {start: ts('2026-09-30T23:30:00+09:00'), end: ts('2026-10-01T01:30:00+09:00')};
let days = ctx.liveDayParts([s], '2026-10', 9);
assert.equal(days.length, 31);
assert.equal(days[0][0].a, 0); assert.equal(days[0][0].b, 1.5);
days = ctx.liveDayParts([s], '2026-09', 9);
assert.equal(days[29][0].a, 23.5); assert.equal(days[29][0].b, 24);
days = ctx.liveDayParts([s], '2026-10', 8);
assert.equal(days[0][0].b, .5, 'time zone changes both date clipping and hours');
assert.equal(ctx.liveDayParts([], '2024-02', 9).length, 29);
assert.equal(ctx.liveDayParts([], '2025-02', 9).length, 28);
const invalid = {start: ts('2026-10-01T21:30:00+09:00'), end: null};
days = ctx.liveDayParts([invalid], '2026-10', 9);
assert.equal(days[0][0].a, 21.5); assert.equal(days[0][0].b, null, 'unknown end is a start marker, not invented duration');
assert.equal(ctx.liveSum([], 'duration').value, null);
assert.equal(ctx.liveValue([], 'duration'), '—');
assert.equal(ctx.liveValue([{revenue_cents: 0}], 'revenue_cents'), '¥0');
assert.equal(ctx.liveValue([{revenue_cents: 90681940}], 'revenue_cents', true), '90.68 万元');
assert.equal(ctx.liveSum([{revenue_cents: 12345}, {revenue_cents: 10}], 'revenue_cents').value, 12355);
assert.equal(ctx.liveSum([{duration: 60}, {duration: null}, {}], 'duration').missing, 2);
assert.equal(ctx.liveValue([{duration: 3600}, {duration: null}], 'duration'), '1 h *');
assert.ok(source.includes('SESSIONS.length || LIVE.status === "ok"'), 'header reads live archive, never dynamic-card counts');
console.log('PASS live totals, zero/missing values, time zones, leap years and sessions crossing midnight/month boundaries');
