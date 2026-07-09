/**
 * cli.test.ts — arg parsing for the reconciler CLI (finding #7).
 *
 * The manual arg loop must consume `--flag value` correctly: the value slot is
 * skipped, never re-processed as an option on the next pass.
 */

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { parseArgs } from '../src/cli.ts';

test('parseArgs: --flag value pairs are consumed, values are not re-processed as options (finding #7)', () => {
  const args = parseArgs([
    '--rows',
    'rows.json',
    '--now',
    '2026-07-09T01:00:00Z',
    '--outbox',
    'build/out.jsonl',
    '--json',
  ]);
  assert.equal(args.rows, 'rows.json');
  assert.equal(args.now, '2026-07-09T01:00:00Z');
  assert.equal(args.outbox, 'build/out.jsonl');
  assert.equal(args.json, true);
});

test('parseArgs: a value that itself looks like a flag name is taken as the value, not re-parsed', () => {
  // `--outbox` as the VALUE of `--rows` must be consumed as the rows value, and must
  // NOT then be interpreted as the --outbox option. Before the i-increment fix, the
  // value slot leaked into the next iteration.
  const args = parseArgs(['--rows', '--outbox']);
  assert.equal(args.rows, '--outbox');
  // --outbox never fired as an option → stays default.
  assert.equal(args.outbox, 'build/signing-outbox.jsonl');
});

test('parseArgs: defaults hold when no args are given (now defaults to a parseable clock)', () => {
  const args = parseArgs([]);
  assert.equal(args.rows, null);
  assert.equal(args.outbox, 'build/signing-outbox.jsonl');
  assert.equal(args.json, false);
  assert.ok(Number.isFinite(Date.parse(args.now)));
});

test('parseArgs: --json is order-independent and does not consume a following token', () => {
  const args = parseArgs(['--json', '--rows', 'r.json']);
  assert.equal(args.json, true);
  assert.equal(args.rows, 'r.json');
});
