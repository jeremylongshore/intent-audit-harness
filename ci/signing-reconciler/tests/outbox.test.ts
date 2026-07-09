/**
 * outbox.test.ts — the append-only OUTBOX guarantee (AC-2), for both impls.
 */

import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { InMemoryOutbox, JsonFileOutbox } from '../src/outbox.ts';
import type { OutboxRecord } from '../src/types.ts';

function rec(id: string, outcome: OutboxRecord['outcome']): OutboxRecord {
  return { at: '2026-07-09T00:00:00Z', skill_version_id: id, skill_id: 'x', outcome, retry_count: 0, detail: 'd' };
}

test('InMemoryOutbox: appends in order and all() returns a defensive copy', async () => {
  const box = new InMemoryOutbox();
  await box.append(rec('a', 'success'));
  await box.append(rec('b', 'failure'));

  const first = await box.all();
  assert.deepEqual(
    first.map((r) => r.skill_version_id),
    ['a', 'b'],
  );

  // Mutating the returned array must NOT rewrite history.
  (first as OutboxRecord[]).push(rec('c', 'terminal'));
  const second = await box.all();
  assert.equal(second.length, 2);
});

test('SigningOutbox interface exposes no update/delete — append-only by construction', () => {
  const box = new InMemoryOutbox();
  // Structurally: the only mutator on the surface is append().
  assert.equal(typeof box.append, 'function');
  assert.equal(typeof box.all, 'function');
  // @ts-expect-error — there is intentionally no update/delete method
  assert.equal(box.update, undefined);
  // @ts-expect-error — there is intentionally no update/delete method
  assert.equal(box.delete, undefined);
});

test('JsonFileOutbox: appends one JSONL line per record; history round-trips', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'reconciler-outbox-'));
  const path = join(dir, 'outbox.jsonl');
  try {
    const box = new JsonFileOutbox(path);
    await box.append(rec('a', 'success'));
    await box.append(rec('b', 'terminal'));

    const raw = await readFile(path, 'utf8');
    const lines = raw.split('\n').filter((l) => l.trim() !== '');
    assert.equal(lines.length, 2); // exactly one line appended per record

    const all = await box.all();
    assert.deepEqual(
      all.map((r) => r.outcome),
      ['success', 'terminal'],
    );
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('JsonFileOutbox: missing ledger file reads as empty history (not an error)', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'reconciler-outbox-'));
  try {
    const box = new JsonFileOutbox(join(dir, 'does-not-exist.jsonl'));
    assert.deepEqual(await box.all(), []);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
