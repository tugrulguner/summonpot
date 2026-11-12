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
    assert.doesNotMatch(html, /not yet published/);
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
    assert.match(html, /version 0\.15\.0/i);
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

test('version 0.15.0 checkpoint progression stays bounded', async () => {
  const [architecture, operations, home] = await Promise.all([
    readFile(new URL('../src/content/docs/architecture.mdx', import.meta.url), 'utf8'),
    readFile(new URL('../src/content/docs/reference/operations.mdx', import.meta.url), 'utf8'),
    readFile(new URL('../src/content/docs/index.mdx', import.meta.url), 'utf8'),
  ]);
  for (const page of [architecture, operations, home]) {
    assert.match(page, /Version 0\.15\.0 bounded checkpoint progression/);
    assert.match(page, /stored, non-null strict Boolean field/);
    assert.match(page, /Mth false closes unresolved/);
    assert.match(page, /redacted 409, not an unresolved result/);
    assert.match(page, /Published v0\.14\.0 is unchanged/);
    assert.match(page, /No rollback, replay, durable resume or recovery/);
  }
});

test('new choice graph is explicitly unreleased without relabeling historical graphs', async () => {
  const html = await readFile(new URL('../dist/reference/operations/index.html', import.meta.url), 'utf8');
  const section = html.match(/<h[23] id="unreleased-source[^\"]*">[\s\S]*?(?=<h[23]|$)/)?.[0];
  assert.ok(section, 'unreleased choice-graph section must render');
  const text = section.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ');
  assert.match(text, /exactly one producer-backed/i);
  assert.match(text, /unique sink/i);
  assert.match(text, /no global choice barrier/i);
  assert.match(text, /allow_direct=False/i);
  assert.match(text, /Historical version 0\.15\.0 branch\/join remains zero-choice/i);
});
