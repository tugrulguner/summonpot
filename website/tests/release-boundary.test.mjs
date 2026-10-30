import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

for (const [name, path] of [
  ['homepage', '../dist/index.html'],
  ['operation reference', '../dist/reference/operations/index.html'],
]) {
  test(`${name} states the 0.11.0 and 0.12.0 chain boundaries`, async () => {
    const html = await readFile(new URL(path, import.meta.url), 'utf8');
    assert.match(html, /0\.11\.0/);
    assert.match(html, /0\.12\.0/);
    assert.match(html, /fully resolved/);
    assert.doesNotMatch(html, /not yet published|Unreleased source/);
    assert.match(html, /agent-mediated/);
    assert.match(html, /model-free/);
    assert.match(html, /128/);
    assert.match(html, /65,536/);
  });
}


test('homepage and operation reference describe the 0.14.0 execution boundary', async () => {
  const homepage = await readFile(new URL('../dist/index.html', import.meta.url), 'utf8');
  const reference = await readFile(new URL('../dist/reference/operations/index.html', import.meta.url), 'utf8');
  for (const html of [homepage, reference]) {
    assert.match(html, /0\.14\.0/);
    assert.match(html, /exactly one[^.]{0,120}(producer-backed choice|AgentChoice)/i);
    assert.match(html, /Pydantic request/i);
    assert.match(html, /FromRequest/i);
    assert.match(html, /historical v0\.13\.0/i);
    assert.match(html, /current source \(unreleased\)/i);
    assert.match(html, /one or more producer-backed/i);
    assert.match(html, /framework-owned progression/i);
    assert.match(html, /without a final model acknowledgment/i);
    assert.match(html, /tool_calls_limit/);
    assert.doesNotMatch(html, /0\.14\.0[^<.]{0,80}(?:includes|ships) multiple choices/i);
  }
  assert.match(reference, /128/);
  assert.match(reference, /65,536/);
  assert.match(reference, /provider-configuration failure/i);
});
