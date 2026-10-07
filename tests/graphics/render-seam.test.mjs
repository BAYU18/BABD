import test from 'node:test';
import assert from 'node:assert/strict';
import { loadGame } from './_load-game.mjs';

test('computeRenderState returns the six layers for a start frame', () => {
  const { computeRenderState, makeGameState } = loadGame();
  const rs = computeRenderState(makeGameState({ state: 'start' }), 0);
  assert.deepEqual(rs.canvas, { w: 400, h: 600, dpr: 1 });
  assert.deepEqual(rs.layers.map(l => l.id),
    ['road', 'scenery', 'cars', 'effects', 'hud', 'lighting']);
  assert.ok(rs.hud.texts.some(x => x.text === 'SCORE 0'));
  assert.ok(rs.hud.texts.some(x => x.text === 'HI 0'));
  assert.equal(rs.effects.length, 0);
});

test('computeRenderState is pure: same input, deep-equal output', () => {
  const { computeRenderState, makeGameState } = loadGame();
  const gs = makeGameState({ state: 'playing' });
  assert.deepEqual(computeRenderState(gs, 1.25), computeRenderState(gs, 1.25));
});
