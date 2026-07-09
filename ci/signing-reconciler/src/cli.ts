#!/usr/bin/env -S node --experimental-strip-types
/**
 * cli.ts — thin CLI entry for the SkillVersion signing reconciler (AC-2).
 *
 * A VPS cron would invoke this: load the candidate `pending_production` rows,
 * run the PURE `reconcile()` with the DEFAULT NoopRekorTransport, and REPORT what
 * it WOULD do. Because the default transport is the Noop (STAGING-FIRST /
 * DR-082-Q3-gated), a bare run ACTIVATES NOTHING — it is a dry-run reporter until
 * an operator injects a real Rekor transport behind the four DR-082 Q3 triggers.
 *
 * This entry lives in audit-harness/ci/ — OUTSIDE the published package `files`
 * allowlist — so the published @intentsolutions/audit-harness stays zero-runtime-
 * deps. The kernel is installed CI-only (`npm i --no-save @intentsolutions/core`,
 * or via this dir's own package.json), never into the harness's dependencies.
 *
 * Usage:
 *   node --experimental-strip-types src/cli.ts --rows rows.json [--now <rfc3339>] [--outbox outbox.jsonl] [--json]
 *
 *   --rows    path to a JSON array of candidate SkillVersion rows (default: read stdin)
 *   --now     RFC 3339 UTC clock to reconcile against (default: process wall clock,
 *             read ONCE here at the edge — the core never reads it)
 *   --outbox  path to the append-only JSONL outbox ledger (default: build/signing-outbox.jsonl)
 *   --json    emit the machine-readable report to stdout
 */

import { readFile } from 'node:fs/promises';
import { JsonFileOutbox } from './outbox.ts';
import { reconcile } from './reconcile.ts';
import { NoopRekorTransport } from './transport.ts';

interface CliArgs {
  readonly rows: string | null;
  readonly now: string;
  readonly outbox: string;
  readonly json: boolean;
}

function parseArgs(argv: readonly string[]): CliArgs {
  let rows: string | null = null;
  // The clock is read ONCE, HERE, at the process edge — never inside reconcile().
  let now = new Date().toISOString();
  let outbox = 'build/signing-outbox.jsonl';
  let json = false;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--rows') rows = argv[i + 1] ?? rows;
    else if (a === '--now') now = argv[i + 1] ?? now;
    else if (a === '--outbox') outbox = argv[i + 1] ?? outbox;
    else if (a === '--json') json = true;
  }
  return { rows, now, outbox, json };
}

async function loadRows(path: string | null): Promise<readonly unknown[]> {
  const raw = path === null ? await readStdin() : await readFile(path, 'utf8');
  const parsed: unknown = JSON.parse(raw);
  if (!Array.isArray(parsed)) {
    throw new Error('reconciler: --rows input must be a JSON array of SkillVersion rows');
  }
  return parsed;
}

function readStdin(): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => (data += chunk));
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

async function main(argv: readonly string[]): Promise<number> {
  const args = parseArgs(argv);
  const rows = await loadRows(args.rows);

  const report = await reconcile(rows, {
    now: args.now,
    // DEFAULT: the Noop transport. This CLI activates NOTHING — production Rekor
    // is STAGING-FIRST / DR-082-Q3-gated and requires a human-injected transport.
    rekorTransport: new NoopRekorTransport(),
    outbox: new JsonFileOutbox(args.outbox),
  });

  if (args.json) {
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  } else {
    process.stdout.write(
      [
        `signing-reconciler dry-run @ ${args.now} (NoopRekorTransport — activates nothing)`,
        `  candidates : ${rows.length}`,
        `  would-sign : ${report.signed.length}`,
        `  retried    : ${report.retried.length}`,
        `  failed     : ${report.failed.length} (surfaced to human review)`,
        `  skipped    : ${report.skipped.length}`,
        `  unparseable: ${report.unparseable.length} (fail-closed)`,
        `  outbox     : ${args.outbox} (append-only)`,
      ].join('\n') + '\n',
    );
    if (report.humanReview.length > 0) {
      process.stdout.write('  human-review queue:\n');
      for (const item of report.humanReview) {
        process.stdout.write(
          `    - ${item.skill_id} (${item.skill_version_id}) after ${item.retry_count} attempts: ${item.reason}\n`,
        );
      }
    }
  }
  return 0;
}

const invokedDirectly = process.argv[1]?.endsWith('cli.ts') === true;
if (invokedDirectly) {
  main(process.argv.slice(2))
    .then((code) => process.exit(code))
    .catch((err: unknown) => {
      process.stderr.write(`signing-reconciler: ${(err as Error).message}\n`);
      process.exit(1);
    });
}

export { main };
