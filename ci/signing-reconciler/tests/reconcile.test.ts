/**
 * reconcile.test.ts — deterministic tests for the SkillVersion signing reconciler.
 *
 * Every seam is INJECTED: a fixed `now`, a scripted transport, and an in-memory
 * append-only outbox. No globals mocked, no wall clock read, no network. Run with:
 *   node --experimental-strip-types --test tests/
 *
 * Coverage (per aon3.4 AC-2 acceptance):
 *   - happy path: pending row past retry_after + success → active, index set,
 *     kernel-validator passes, outbox success record.
 *   - retry: failure → retry_count++, new retry_after, stays pending, failure record.
 *   - exhaustion: retry_count at ceiling → signing_failed + human-review record.
 *   - state-machine enforcement: illegal transition refused via kernel canTransition.
 *   - cross-field invariant: active+production row carries its index (validator passes);
 *     an active row missing the index is refused (fail-closed).
 *   - Noop transport never fakes delivery.
 */

import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  SKILL_VERSION_MAX_SIGNING_RETRIES,
  canTransition,
  skillVersionSigningTransitions,
} from '@intentsolutions/core';
import { SkillVersionSchema } from '@intentsolutions/core/validators/v1/skill-version';
import { InMemoryOutbox } from '../src/outbox.ts';
import { reconcile } from '../src/reconcile.ts';
import { NoopRekorTransport } from '../src/transport.ts';
import {
  ScriptedRekorTransport,
  activeRow,
  delivered,
  pendingRow,
  stagingRow,
  undelivered,
} from './helpers.ts';

const NOW = '2026-07-09T01:00:00Z';

test('happy path: due pending_production + success transport → active, index set, kernel-valid, outbox success', async () => {
  const outbox = new InMemoryOutbox();
  const transport = new ScriptedRekorTransport([delivered(1809941999)]);
  const row = pendingRow({ retry_after: '2026-07-09T00:30:00Z', retry_count: 1 });

  const report = await reconcile([row], { now: NOW, rekorTransport: transport, outbox });

  assert.deepEqual(report.signed, [row.id]);
  assert.equal(report.retried.length, 0);
  assert.equal(report.failed.length, 0);

  const signed = report.rows.find((r) => r.id === row.id);
  assert.ok(signed);
  assert.equal(signed.status, 'active');
  assert.equal(signed.signing_mode, 'rekor_production');
  assert.equal(signed.rekor_log_index, 1809941999);

  // The resulting row passes the kernel validator (cross-field invariant holds).
  assert.equal(SkillVersionSchema.safeParse(signed).success, true);

  const records = await outbox.all();
  assert.equal(records.length, 1);
  assert.equal(records[0]?.outcome, 'success');
  assert.equal(records[0]?.rekor_log_index, 1809941999);
  assert.equal(records[0]?.at, NOW);
});

test('retry: failure with budget → retry_count++, new retry_after, stays pending_production, failure record', async () => {
  const outbox = new InMemoryOutbox();
  const transport = new ScriptedRekorTransport([undelivered('rekor 503')]);
  const row = pendingRow({ retry_after: '2026-07-09T00:30:00Z', retry_count: 1 });

  const report = await reconcile([row], { now: NOW, rekorTransport: transport, outbox });

  assert.deepEqual(report.retried, [row.id]);
  assert.equal(report.signed.length, 0);
  assert.equal(report.failed.length, 0);

  const retriedRow = report.rows.find((r) => r.id === row.id);
  assert.ok(retriedRow);
  assert.equal(retriedRow.status, 'pending_production'); // STAYS pending — not a state transition
  assert.equal(retriedRow.retry_count, 2);
  assert.ok(retriedRow.retry_after);
  // New retry_after is strictly in the future relative to now (bounded backoff).
  assert.ok(Date.parse(retriedRow.retry_after) > Date.parse(NOW));

  const records = await outbox.all();
  assert.equal(records.length, 1);
  assert.equal(records[0]?.outcome, 'failure');
  assert.equal(records[0]?.retry_count, 2);
});

test('exhaustion: retry_count at ceiling minus one + failure → signing_failed + human-review record', async () => {
  const outbox = new InMemoryOutbox();
  const transport = new ScriptedRekorTransport([undelivered('rekor down')]);
  // retry_count = 4; this attempt makes 5 (=== MAX) → terminal.
  const row = pendingRow({
    retry_after: '2026-07-09T00:30:00Z',
    retry_count: SKILL_VERSION_MAX_SIGNING_RETRIES - 1,
  });

  const report = await reconcile([row], { now: NOW, rekorTransport: transport, outbox });

  assert.deepEqual(report.failed, [row.id]);
  assert.equal(report.retried.length, 0);
  assert.equal(report.humanReview.length, 1);
  assert.equal(report.humanReview[0]?.skill_version_id, row.id);
  assert.equal(report.humanReview[0]?.retry_count, SKILL_VERSION_MAX_SIGNING_RETRIES);

  const failedRow = report.rows.find((r) => r.id === row.id);
  assert.ok(failedRow);
  assert.equal(failedRow.status, 'signing_failed');
  assert.equal(failedRow.retry_count, SKILL_VERSION_MAX_SIGNING_RETRIES);
  // signing_failed keeps staging mode + no rekor index → kernel invariant holds.
  assert.equal(SkillVersionSchema.safeParse(failedRow).success, true);

  const records = await outbox.all();
  assert.equal(records.length, 1);
  assert.equal(records[0]?.outcome, 'terminal');
});

test('ceiling is read from the kernel const, never hardcoded (loop count matches SKILL_VERSION_MAX_SIGNING_RETRIES)', async () => {
  // Walk a fresh row through repeated failures; it must land signing_failed after
  // exactly SKILL_VERSION_MAX_SIGNING_RETRIES attempts — proving the bound tracks
  // the kernel const, not a literal.
  let row = pendingRow({ retry_after: '2026-07-09T00:00:00Z', retry_count: 0 });
  const outbox = new InMemoryOutbox();
  let attempts = 0;
  for (let pass = 0; pass < SKILL_VERSION_MAX_SIGNING_RETRIES + 2; pass++) {
    if (row.status !== 'pending_production') break;
    const transport = new ScriptedRekorTransport([undelivered()]);
    // Make the row due each pass by reconciling at a time past its retry_after.
    const passNow = new Date(Date.parse('2026-07-09T00:00:00Z') + (pass + 1) * 3_600_000).toISOString();
    const report = await reconcile([row], { now: passNow, rekorTransport: transport, outbox });
    row = report.rows[0]!;
    attempts++;
  }
  assert.equal(row.status, 'signing_failed');
  assert.equal(attempts, SKILL_VERSION_MAX_SIGNING_RETRIES);
});

test('state-machine enforcement: an active row is terminal — reconcile never transitions it (kernel canTransition=false)', async () => {
  // Sanity on the kernel map itself: active has no outgoing edges.
  assert.equal(canTransition(skillVersionSigningTransitions, 'active', 'pending_production'), false);
  assert.equal(canTransition(skillVersionSigningTransitions, 'active', 'active'), false);

  const outbox = new InMemoryOutbox();
  const transport = new ScriptedRekorTransport([delivered(42)]);
  const already = activeRow();

  const report = await reconcile([already], { now: NOW, rekorTransport: transport, outbox });

  // Active is not pending_production → skipped, untouched, transport never called.
  assert.deepEqual(report.skipped, [already.id]);
  assert.equal(report.signed.length, 0);
  assert.equal(transport.calls.length, 0);
  const passthrough = report.rows.find((r) => r.id === already.id);
  assert.deepEqual(passthrough, already);
});

test('cross-field invariant: signed active+production row carries a non-null rekor_log_index and passes the kernel validator', async () => {
  const outbox = new InMemoryOutbox();
  const transport = new ScriptedRekorTransport([delivered(7)]);
  const row = pendingRow({ retry_after: NOW, retry_count: 0 });

  const report = await reconcile([row], { now: NOW, rekorTransport: transport, outbox });
  const signed = report.rows.find((r) => r.id === row.id)!;

  // Direction A of the invariant: active+production ⇒ index present.
  assert.equal(signed.status, 'active');
  assert.equal(signed.signing_mode, 'rekor_production');
  assert.equal(typeof signed.rekor_log_index, 'number');
  assert.equal(SkillVersionSchema.safeParse(signed).success, true);
});

test('cross-field invariant: a would-be active row missing the index is refused (fail-closed, not persisted)', async () => {
  // A misbehaving transport reports delivered but with a NaN/invalid index the
  // kernel validator rejects. The reconciler must NOT persist an invalid active row.
  const outbox = new InMemoryOutbox();
  const badTransport = new ScriptedRekorTransport([
    { delivered: true, logIndex: Number.NaN } as never,
  ]);
  const row = pendingRow({ retry_after: NOW, retry_count: 0 });

  const report = await reconcile([row], { now: NOW, rekorTransport: badTransport, outbox });

  assert.equal(report.signed.length, 0);
  assert.deepEqual(report.skipped, [row.id]);
  const passthrough = report.rows.find((r) => r.id === row.id)!;
  // Row is left as the original pending row — NOT flipped to a broken active state.
  assert.equal(passthrough.status, 'pending_production');
  const records = await outbox.all();
  assert.equal(records[0]?.outcome, 'skipped');
  assert.match(records[0]?.detail ?? '', /fail-closed/);
});

test('NoopRekorTransport never fakes delivery', async () => {
  const noop = new NoopRekorTransport();
  const result = await noop.push(pendingRow());
  assert.equal(result.delivered, false);
  if (!result.delivered) {
    assert.match(result.reason, /activates nothing/i);
  }

  // And a full reconcile through the default (Noop) transport signs nothing.
  const outbox = new InMemoryOutbox();
  const row = pendingRow({ retry_after: NOW, retry_count: 0 });
  const report = await reconcile([row], { now: NOW, outbox }); // no transport → default Noop
  assert.equal(report.signed.length, 0);
  assert.deepEqual(report.retried, [row.id]); // Noop failure counts as a retry, never a sign
});

test('non-due pending and staging/terminal rows are skipped and passed through untouched', async () => {
  const outbox = new InMemoryOutbox();
  const transport = new ScriptedRekorTransport([delivered(1)]);
  const notDue = pendingRow({ id: '0192cae6-000b-7000-8000-0000000000aa', retry_after: '2026-07-09T02:00:00Z', retry_count: 0 });
  const staging = stagingRow();

  const report = await reconcile([notDue, staging], { now: NOW, rekorTransport: transport, outbox });

  assert.equal(report.signed.length, 0);
  assert.equal(transport.calls.length, 0); // nothing due → transport untouched
  assert.equal(report.skipped.length, 2);
});

test('fail-closed: an unparseable row is never signed and is recorded as skipped/unparseable', async () => {
  const outbox = new InMemoryOutbox();
  const transport = new ScriptedRekorTransport([delivered(1)]);
  const garbage = { id: 'not-a-uuid', status: 'pending_production', skill_id: 'x' };

  const report = await reconcile([garbage], { now: NOW, rekorTransport: transport, outbox });

  assert.deepEqual(report.unparseable, ['not-a-uuid']);
  assert.equal(report.signed.length, 0);
  assert.equal(transport.calls.length, 0);
  const records = await outbox.all();
  assert.equal(records[0]?.outcome, 'skipped');
  assert.match(records[0]?.detail ?? '', /fail-closed/);
});

test('reconcile does not mutate its input rows in place (returns new objects for changed rows)', async () => {
  const outbox = new InMemoryOutbox();
  const transport = new ScriptedRekorTransport([delivered(99)]);
  const row = pendingRow({ retry_after: NOW, retry_count: 0 });
  const before = structuredClone(row);

  await reconcile([row], { now: NOW, rekorTransport: transport, outbox });

  // The original object is unchanged — the reconciler produced a new row.
  assert.deepEqual(row, before);
});
