import test from 'node:test';
import assert from 'node:assert/strict';
import { loadGame } from './_load-game.mjs';

test('road layer has gradient asphalt, edges and scrolling dashes', () => {
  const { computeRenderState, makeGameState } = loadGame();
  const road = computeRenderState(makeGameState({ state: 'playing', dashOffset: 20 }), 0)
    .layers.find(l => l.id === 'road');
  const asphalt = road.draw.find(d => d.role === 'asphalt');
  assert.ok(asphalt.gradient && asphalt.gradient.from && asphalt.gradient.to);
  assert.equal(road.draw.filter(d => d.role === 'edge').length, 2);
  const dashes = road.draw.filter(d => d.role === 'laneDash');
  assert.ok(dashes.length > 0);
  assert.ok(dashes.every(d => d.w === 4 && d.h === 24 && d.color === '#cfcfcf'));
  // dividers at x = 100, 200, 300 (3 lane boundaries) — 4 lanes => 3 dividers
  const xs = [...new Set(dashes.map(d => d.x - 2))].sort((a, b) => a - b);
  assert.deepEqual(xs, [100, 200, 300]);
});
