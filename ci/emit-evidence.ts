#!/usr/bin/env -S node --experimental-strip-types
/**
 * ci/emit-evidence.ts — produce audit-harness's own signed-ready testing
 * evidence for the intent-eval-dashboard reports hub (bead nr75.12).
 *
 * ── Why this lives in `ci/`, NOT `scripts/` ──
 *
 * @intentsolutions/audit-harness is a ZERO-runtime-dependency polyglot CLI, and
 * its `package.json#files` allowlist PUBLISHES `scripts/`. This emitter imports
 * `@intentsolutions/core` (the kernel validators), so it must NOT live in the
 * published surface. `ci/` is excluded from `files`, so nothing here ships to npm
 * consumers and the published package stays zero-dep. CI installs the kernel with
 * `npm i --no-save @intentsolutions/core@<v>` (never written to package.json)
 * just for this emit job — see `.github/workflows/release.yml`.
 *
 * This is the DETERMINISTIC half of the emit. It runs audit-harness's real
 * deterministic self-gate, shapes the outcome into a kernel `gate-result/v1`
 * body, wraps it in a kernel `EvidenceBundle`, and writes:
 *
 *   build/evidence/bundle-<i>.json          — CANONICAL EvidenceBundle bytes
 *   build/evidence/gate-result-<i>.json     — the gate-result/v1 predicate body
 *   build/evidence/manifest-skeleton.json   — for ci/assemble-manifest.ts
 *
 * Signing + Rekor + final report-manifest.json assembly happen in CI. This script
 * does NO crypto and writes only to the gitignored `build/` dir.
 *
 * ── Gate selection (honest, no fake evidence) ──
 *
 * audit-harness is the deterministic-gates tool itself; it has no unit-test
 * coverage suite. Its one clean, deterministic, release-state SELF-gate is
 * HARNESS-HASH (`scripts/harness-hash.sh --verify`) — the integrity check that
 * the hash-pinning tool's own policy manifest (`.harness-hash`) is internally
 * consistent / untampered. That is exactly what iah emits. Deliberately excluded
 * after recon (would be fake/degraded evidence, the nr75 plan's hard rule):
 *   - architecture     — `arch-check.sh` reports not-configured (no rule pack)
 *   - conform          — 0 conformance rows apply to the harness repo itself
 *   - escape-scan self — ci.yml's own note marks the synthetic self-test
 *                        non-deterministic; unfit for SIGNED evidence
 *   - shellcheck/ruff  — real but require extra toolchain installs; deferred
 *
 * ── Contract (matches the dashboard ingest, verified against its source) ──
 *
 *   - Each `bundle` validates against `EvidenceBundleSchema` (kernel pinned to
 *     the EXACT version the dashboard verifies with).
 *   - Canonical bytes use the dashboard's `stableStringify` so cosign's signature
 *     round-trips through the dashboard's re-canonicalisation.
 *   - `signing_mode: 'rekor_production'`, `rekor_log_indices: []` (real index
 *     lives in the sigstore Bundle the dashboard's Rekor check verifies).
 *
 * Usage:
 *   node --experimental-strip-types ci/emit-evidence.ts [--out build/evidence] [--self-check]
 */

import { execFileSync } from 'node:child_process';
import { createHash, randomBytes } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  GateResultV1Schema,
  GATE_RESULT_V1_URI,
} from '@intentsolutions/core/validators/v1/gate-result-v1';
import { EvidenceBundleSchema } from '@intentsolutions/core/validators/v1/evidence-bundle';

const GITHUB_REPO = 'jeremylongshore/intent-audit-harness';
const REPO_KEY = 'iah';

interface GateOutcome {
  readonly gateName: string;
  readonly gateVersion: string;
  readonly decision: 'pass' | 'fail' | 'advisory' | 'error';
  readonly reasons: readonly string[];
  readonly dimensionsEvaluated: readonly string[];
  readonly dimensionsSkipped: readonly string[];
  readonly advisorySeverity?: 'info' | 'warn' | 'error';
  readonly failureMode?: string;
}

interface EmitContext {
  readonly nowIso: string;
  readonly nowMs: number;
  readonly commitSha: string;
  readonly sourceSha: string;
  readonly policyHash: string;
  readonly runnerVersion: string;
  readonly rand16: () => Uint8Array;
}

// ── Canonicalisation (MUST match the dashboard's content-address.ts) ──

function sortDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortDeep);
  if (value !== null && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([k, v]) => [k, sortDeep(v)] as const);
    return Object.fromEntries(entries);
  }
  return value;
}

export function stableStringify(value: unknown): string {
  return JSON.stringify(sortDeep(value));
}

function sha256Hex(s: string): string {
  return createHash('sha256').update(Buffer.from(s, 'utf8')).digest('hex');
}

export function uuidv7(nowMs: number, rand: Uint8Array): string {
  const b = Buffer.from(rand.slice(0, 16));
  const ts = BigInt(nowMs);
  b[0] = Number((ts >> 40n) & 0xffn);
  b[1] = Number((ts >> 32n) & 0xffn);
  b[2] = Number((ts >> 24n) & 0xffn);
  b[3] = Number((ts >> 16n) & 0xffn);
  b[4] = Number((ts >> 8n) & 0xffn);
  b[5] = Number(ts & 0xffn);
  b[6] = (b[6]! & 0x0f) | 0x70; // version 7
  b[8] = (b[8]! & 0x3f) | 0x80; // variant 10
  const h = b.toString('hex');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20, 32)}`;
}

export interface EmitRow {
  readonly bundle: unknown;
  readonly canonicalBundle: string;
  readonly gateResult: unknown;
  readonly sourceSha: string;
}

export function buildGateResult(o: GateOutcome, ctx: EmitContext): Record<string, unknown> {
  const gateId = `${REPO_KEY}:ci:${o.gateName}`;
  const inputHash = `sha256:${sha256Hex(`${ctx.commitSha}:${o.gateName}:${ctx.policyHash}`)}`;
  const body: Record<string, unknown> = {
    gate_id: gateId,
    gate_name: o.gateName,
    gate_version: o.gateVersion,
    gate_decision: o.decision,
    gate_reasons: [...o.reasons],
    coverage: {
      dimensions_evaluated: [...o.dimensionsEvaluated],
      dimensions_skipped: [...o.dimensionsSkipped],
    },
    policy_ref: `${ctx.policyHash}:.harness-hash`,
    policy_hash: ctx.policyHash,
    input_hash: inputHash,
    evaluated_at: ctx.nowIso,
    runner: `iah-emit@${ctx.runnerVersion}`,
    commit_sha: ctx.commitSha,
    ...(o.advisorySeverity !== undefined ? { advisory_severity: o.advisorySeverity } : {}),
    ...(o.failureMode !== undefined ? { failure_mode: o.failureMode } : {}),
  };
  GateResultV1Schema.parse(body); // fail-closed
  return body;
}

export function buildEvidenceBundle(
  gateResult: Record<string, unknown>,
  ctx: EmitContext,
): Record<string, unknown> {
  const grHashHex = sha256Hex(stableStringify(gateResult));
  const inputHash = String(gateResult['input_hash']);
  const subjectDigest = inputHash.startsWith('sha256:')
    ? inputHash.slice('sha256:'.length)
    : inputHash;
  const bundle: Record<string, unknown> = {
    id: uuidv7(ctx.nowMs, ctx.rand16()),
    eval_run_id: uuidv7(ctx.nowMs, ctx.rand16()),
    created_at: ctx.nowIso,
    predicate_uri_set: [GATE_RESULT_V1_URI],
    row_count: 1,
    subject_set: [{ name: String(gateResult['gate_id']), digest: { sha256: subjectDigest } }],
    storage_key: `sha256:${grHashHex}`,
    signing_mode: 'rekor_production',
    rekor_log_indices: [],
    verification_status: 'unverified',
    verification_last_checked_at: ctx.nowIso,
  };
  EvidenceBundleSchema.parse(bundle); // fail-closed
  return bundle;
}

export function buildRows(outcomes: readonly GateOutcome[], ctx: EmitContext): EmitRow[] {
  return outcomes.map((o) => {
    const gateResult = buildGateResult(o, ctx);
    const bundle = buildEvidenceBundle(gateResult, ctx);
    return {
      bundle,
      canonicalBundle: stableStringify(bundle),
      gateResult,
      sourceSha: ctx.sourceSha,
    };
  });
}

export interface ManifestSkeleton {
  readonly repo: string;
  readonly signing: { readonly issuer: string; readonly subject: string; readonly workflowRef: string };
  readonly rows: readonly {
    readonly bundleFile: string;
    readonly gateResults: readonly unknown[];
    readonly sourceSha: string;
  }[];
}

export function signingClaims(ref: string): ManifestSkeleton['signing'] {
  return {
    issuer: 'https://token.actions.githubusercontent.com',
    subject: `repo:${GITHUB_REPO}:ref:${ref}`,
    workflowRef: `${GITHUB_REPO}/.github/workflows/release.yml@${ref}`,
  };
}

export function writeEmit(rows: readonly EmitRow[], ref: string, outDir: string): ManifestSkeleton {
  mkdirSync(outDir, { recursive: true });
  const skeletonRows = rows.map((row, i) => {
    const bundleFile = `bundle-${i}.json`;
    writeFileSync(join(outDir, bundleFile), row.canonicalBundle, 'utf8');
    writeFileSync(join(outDir, `gate-result-${i}.json`), stableStringify(row.gateResult), 'utf8');
    return { bundleFile, gateResults: [row.gateResult], sourceSha: row.sourceSha };
  });
  const skeleton: ManifestSkeleton = { repo: REPO_KEY, signing: signingClaims(ref), rows: skeletonRows };
  writeFileSync(join(outDir, 'manifest-skeleton.json'), JSON.stringify(skeleton, null, 2), 'utf8');
  return skeleton;
}

// ── Gate collection (CI-run; runs the repo's real self-gate) ──

function run(cmd: string, args: readonly string[]): { ok: boolean; out: string } {
  try {
    const out = execFileSync(cmd, args as string[], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    return { ok: true, out };
  } catch (err: unknown) {
    const e = err as { stdout?: string; stderr?: string; message?: string };
    return { ok: false, out: `${e.stdout ?? ''}${e.stderr ?? ''}${e.message ?? ''}` };
  }
}

/**
 * harness-hash --verify: the hash-pinning tool's own policy manifest
 * (.harness-hash) is internally consistent / untampered. Real, deterministic,
 * self-contained (bash only).
 */
function harnessHashOutcome(): GateOutcome {
  const r = run('bash', ['scripts/harness-hash.sh', '--verify']);
  return {
    gateName: 'harness-hash',
    gateVersion: '1.0.0',
    decision: r.ok ? 'pass' : 'fail',
    reasons: r.ok
      ? ['.harness-hash manifest verified consistent']
      : [firstLines(r.out, 6) || 'harness-hash --verify reported drift'],
    dimensionsEvaluated: ['hash-manifest-consistency'],
    dimensionsSkipped: [],
    ...(r.ok ? {} : { failureMode: 'harness-hash-drift' }),
  };
}

function firstLines(s: string, n: number): string {
  return s
    .split('\n')
    .filter((l) => l.trim().length > 0)
    .slice(0, n)
    .join(' ')
    .slice(0, 500);
}

function gitSha(): string {
  const r = run('git', ['rev-parse', 'HEAD']);
  return r.ok ? r.out.trim() : '0'.repeat(40);
}

function harnessPolicyHash(): string {
  try {
    const h = readFileSync(join(process.cwd(), '.harness-hash'), 'utf8').trim();
    if (/^[a-f0-9]{64}$/.test(h)) return `sha256:${h}`;
    // .harness-hash may be a multi-line manifest; hash its full content.
    return `sha256:${sha256Hex(h)}`;
  } catch {
    return `sha256:${sha256Hex('no-policy')}`;
  }
}

// ── Self-check (locally-runnable correctness proof) ──

function selfCheck(): void {
  const ctx = synthCtx();
  const outcomes: GateOutcome[] = [
    {
      gateName: 'harness-hash',
      gateVersion: '1.0.0',
      decision: 'pass',
      reasons: ['.harness-hash manifest verified consistent'],
      dimensionsEvaluated: ['hash-manifest-consistency'],
      dimensionsSkipped: [],
    },
    {
      gateName: 'harness-hash',
      gateVersion: '1.0.0',
      decision: 'fail',
      reasons: ['harness-hash --verify reported drift'],
      dimensionsEvaluated: ['hash-manifest-consistency'],
      dimensionsSkipped: [],
      failureMode: 'harness-hash-drift',
    },
  ];
  const rows = buildRows(outcomes, ctx);
  for (const row of rows) {
    if (stableStringify(JSON.parse(row.canonicalBundle)) !== row.canonicalBundle) {
      throw new Error('canonical bundle is not stable under re-canonicalisation');
    }
  }
  if (rows.length !== 2) throw new Error('expected 2 rows');
  console.log(`✓ self-check: ${rows.length} kernel-valid, canonical-stable rows built`);
}

function synthCtx(): EmitContext {
  let n = 0;
  return {
    nowIso: '2026-06-08T00:00:00.000Z',
    nowMs: 1780617600000,
    commitSha: 'a'.repeat(40),
    sourceSha: 'a'.repeat(40),
    policyHash: `sha256:${'b'.repeat(64)}`,
    runnerVersion: '1.1.6',
    rand16: () => {
      n += 1;
      return Uint8Array.from(Array.from({ length: 16 }, (_v, i) => (n * 31 + i) & 0xff));
    },
  };
}

function packageVersion(): string {
  try {
    const pkg = JSON.parse(readFileSync(join(process.cwd(), 'package.json'), 'utf8')) as {
      version?: string;
    };
    return pkg.version ?? '0.0.0';
  } catch {
    return '0.0.0';
  }
}

function ciCtx(): EmitContext {
  const sha = gitSha();
  return {
    nowIso: new Date().toISOString(),
    nowMs: Date.now(),
    commitSha: sha,
    sourceSha: sha,
    policyHash: harnessPolicyHash(),
    runnerVersion: packageVersion(),
    rand16: () => Uint8Array.from(randomBytes(16)),
  };
}

function parseArgs(argv: readonly string[]): { out: string; selfCheck: boolean; ref: string } {
  let out = 'build/evidence';
  let ref = process.env['GITHUB_REF'] ?? 'refs/tags/v0.0.0';
  let sc = false;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--out') {
      out = argv[i + 1] ?? out;
      i++;
    } else if (argv[i] === '--ref') {
      ref = argv[i + 1] ?? ref;
      i++;
    } else if (argv[i] === '--self-check') {
      sc = true;
    }
  }
  return { out, selfCheck: sc, ref };
}

function main(argv: readonly string[]): number {
  const args = parseArgs(argv);
  if (args.selfCheck) {
    selfCheck();
    return 0;
  }
  const ctx = ciCtx();
  mkdirSync(args.out, { recursive: true });
  const outcomes: GateOutcome[] = [harnessHashOutcome()];
  const rows = buildRows(outcomes, ctx);
  writeEmit(rows, args.ref, args.out);
  console.log(
    `✓ emit-evidence: ${rows.length} kernel-valid gate-result/v1 row(s) written to ${args.out}\n` +
      `  decisions: ${outcomes.map((o) => `${o.gateName}=${o.decision}`).join(', ')}\n` +
      `  next (CI): cosign sign-blob each bundle-<i>.json -> ci/assemble-manifest.ts -> report-manifest.json`,
  );
  return 0;
}

const invokedDirectly = process.argv[1]?.endsWith('emit-evidence.ts') === true;
if (invokedDirectly) {
  try {
    process.exit(main(process.argv.slice(2)));
  } catch (err: unknown) {
    console.error('emit-evidence FAILED (fail-closed):', err instanceof Error ? err.message : String(err));
    process.exit(1);
  }
}
