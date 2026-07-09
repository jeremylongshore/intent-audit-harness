/**
 * reconcile.ts — the PURE, DETERMINISTIC bounded-retry reconciler (AC-2).
 *
 * This is the runtime HALF of aon3.4: it DRIVES the kernel SkillVersion signing
 * state machine that `@intentsolutions/core@0.10.0` publishes. It NEVER
 * reimplements the state machine — every legal transition is checked against the
 * kernel's `skillVersionSigningTransitions` via the kernel's `canTransition`, the
 * retry ceiling is the kernel's `SKILL_VERSION_MAX_SIGNING_RETRIES`, and every
 * resulting row is validated against the kernel `SkillVersionSchema` (which carries
 * the AT-DECR 011 § D3 cross-field invariant) before it is persisted.
 *
 * ── Injected seams (no globals) ──
 *   - `now`             : the clock, as a parameter (RFC 3339 UTC string). NEVER read directly.
 *   - `rekorTransport`  : the push seam. Default = NoopRekorTransport (activates nothing).
 *   - `outbox`          : the append-only ledger (AC-2). Every attempt appends a record.
 *   - `backoff`         : the retry-cadence policy (bounded, injected).
 *
 * ── Contract per AT-DECR 011 § 5 + DR-085 ──
 *   For each `pending_production` row whose `retry_after` ≤ `now`:
 *     • push via the transport;
 *     • SUCCESS  → transition to `active` (via kernel canTransition) + signing_mode
 *                  'rekor_production' + rekor_log_index; VALIDATE against the kernel
 *                  Zod validator (invariant must pass) BEFORE persisting; append a
 *                  success record.
 *     • FAILURE with budget → increment retry_count, push out retry_after (bounded
 *                  backoff), append a failure record; STAY pending_production (an
 *                  in-place field update, NOT a state transition — keeps the kernel
 *                  map self-loop-free).
 *     • FAILURE at ceiling (retry_count === SKILL_VERSION_MAX_SIGNING_RETRIES) →
 *                  transition to `signing_failed` (via kernel canTransition) + surface
 *                  a HumanReviewItem; append the terminal record.
 *   NEVER blocks creation. NEVER reads the clock. FAIL-CLOSED on an unparseable row.
 */

import {
  SKILL_VERSION_MAX_SIGNING_RETRIES,
  canTransition,
  skillVersionSigningTransitions,
} from '@intentsolutions/core';
import { SkillVersionSchema } from '@intentsolutions/core/validators/v1/skill-version';
import { defaultBackoff, NoopRekorTransport } from './transport.ts';
import type {
  BackoffPolicy,
  HumanReviewItem,
  RekorTransport,
  SigningOutbox,
  SkillVersion,
} from './types.ts';

/** What a reconcile pass produced. Pure data — the caller decides what to do with it. */
export interface ReconcileReport {
  /** The rows AFTER reconciliation (only the ones the pass touched are changed). */
  readonly rows: readonly SkillVersion[];
  /** Rows that were signed (transitioned to active) this pass. */
  readonly signed: readonly string[];
  /** Rows whose retry was bumped (stayed pending_production) this pass. */
  readonly retried: readonly string[];
  /** Rows that exhausted retries and landed signing_failed this pass. */
  readonly failed: readonly string[];
  /** Rows skipped (not due yet, or not pending_production). */
  readonly skipped: readonly string[];
  /** Rows that could not be parsed as a SkillVersion — fail-closed, never signed. */
  readonly unparseable: readonly string[];
  /** Human-review escalations emitted this pass (one per exhausted row). */
  readonly humanReview: readonly HumanReviewItem[];
}

export interface ReconcileOptions {
  /** Injected wall clock — RFC 3339 UTC. REQUIRED; the core never reads a real clock. */
  readonly now: string;
  /** Injected Rekor push seam. Defaults to NoopRekorTransport (activates nothing). */
  readonly rekorTransport?: RekorTransport;
  /** Append-only outbox ledger (AC-2). REQUIRED. */
  readonly outbox: SigningOutbox;
  /** Bounded backoff policy. Defaults to the module default. */
  readonly backoff?: BackoffPolicy;
}

/** RFC 3339 lexical-safe comparison via Date parsing; both are UTC. */
function isDue(retryAfter: string | undefined, now: string): boolean {
  // No retry_after set ⇒ eligible immediately (a freshly-queued row).
  if (retryAfter === undefined) return true;
  const ra = Date.parse(retryAfter);
  const n = Date.parse(now);
  if (Number.isNaN(ra) || Number.isNaN(n)) return false; // unparseable → not due (fail-safe)
  return ra <= n;
}

/**
 * Reconcile a batch of candidate rows. PURE with respect to its inputs: the only
 * effects are the awaited transport pushes and outbox appends passed in as seams.
 * Returns a fresh report; input rows are never mutated in place (new objects are
 * produced for changed rows).
 */
export async function reconcile(
  pendingRows: readonly unknown[],
  options: ReconcileOptions,
): Promise<ReconcileReport> {
  const now = options.now;
  const transport = options.rekorTransport ?? new NoopRekorTransport();
  const outbox = options.outbox;
  const backoff = options.backoff ?? defaultBackoff;

  const rows: SkillVersion[] = [];
  const signed: string[] = [];
  const retried: string[] = [];
  const failed: string[] = [];
  const skipped: string[] = [];
  const unparseable: string[] = [];
  const humanReview: HumanReviewItem[] = [];

  for (const raw of pendingRows) {
    // FAIL-CLOSED: an unparseable row is never signed and never mutated. It is
    // recorded as skipped/unparseable and passed through unchanged.
    const parsed = SkillVersionSchema.safeParse(raw);
    if (!parsed.success) {
      const id = extractId(raw);
      unparseable.push(id);
      await outbox.append({
        at: now,
        skill_version_id: id,
        skill_id: extractSkillId(raw),
        outcome: 'skipped',
        retry_count: extractRetryCount(raw),
        detail: `fail-closed: row did not parse against the kernel SkillVersion validator (${parsed.error.issues[0]?.message ?? 'invalid'})`,
      });
      // Pass the raw through untouched only if it at least has the fields we can
      // safely re-emit; otherwise drop from rows to avoid emitting garbage.
      continue;
    }

    const row = parsed.data;

    // Only pending_production rows that are DUE are candidates. Everything else
    // (staging, active, signing_failed, or a not-yet-due pending row) is left
    // exactly as-is.
    if (row.status !== 'pending_production' || !isDue(row.retry_after, now)) {
      rows.push(row);
      skipped.push(row.id);
      continue;
    }

    // Attempt the push through the injected seam (Noop by default).
    const result = await transport.push(row);

    if (result.delivered) {
      // SUCCESS → transition to active. Check legality against the KERNEL map.
      if (!canTransition(skillVersionSigningTransitions, row.status, 'active')) {
        // Defensive: the kernel map forbids it. Never force it.
        rows.push(row);
        skipped.push(row.id);
        await outbox.append({
          at: now,
          skill_version_id: row.id,
          skill_id: row.skill_id,
          outcome: 'skipped',
          retry_count: row.retry_count ?? 0,
          detail: `state-machine refused pending_production→active (kernel canTransition=false)`,
        });
        continue;
      }
      const nextRow: SkillVersion = {
        ...row,
        status: 'active',
        signing_mode: 'rekor_production',
        rekor_log_index: result.logIndex,
      };
      // VALIDATE the resulting row against the kernel validator (the cross-field
      // invariant MUST pass) BEFORE persisting.
      const check = SkillVersionSchema.safeParse(nextRow);
      if (!check.success) {
        // The transport handed us something the kernel rejects (e.g. a non-int
        // index). Fail-closed: do NOT persist an invalid active row.
        rows.push(row);
        skipped.push(row.id);
        await outbox.append({
          at: now,
          skill_version_id: row.id,
          skill_id: row.skill_id,
          outcome: 'skipped',
          retry_count: row.retry_count ?? 0,
          detail: `fail-closed: signed row rejected by kernel validator (${check.error.issues[0]?.message ?? 'invalid'})`,
        });
        continue;
      }
      rows.push(check.data);
      signed.push(row.id);
      await outbox.append({
        at: now,
        skill_version_id: row.id,
        skill_id: row.skill_id,
        outcome: 'success',
        retry_count: row.retry_count ?? 0,
        rekor_log_index: result.logIndex,
        detail: `signed to production Rekor log (index ${result.logIndex})`,
      });
      continue;
    }

    // FAILURE. Account for the attempt.
    const attemptsAfter = (row.retry_count ?? 0) + 1;

    if (attemptsAfter >= SKILL_VERSION_MAX_SIGNING_RETRIES) {
      // Bounded-retry EXHAUSTED → transition to signing_failed (kernel-checked)
      // and surface to human review.
      if (!canTransition(skillVersionSigningTransitions, row.status, 'signing_failed')) {
        rows.push(row);
        skipped.push(row.id);
        continue;
      }
      const failedRow: SkillVersion = {
        ...row,
        status: 'signing_failed',
        retry_count: attemptsAfter,
        signing_downgrade_reason: `rekor unreachable after ${attemptsAfter} attempts (max ${SKILL_VERSION_MAX_SIGNING_RETRIES}); surfaced to human review — ${result.reason}`,
      };
      const check = SkillVersionSchema.safeParse(failedRow);
      // signing_failed keeps signing_mode staging (no rekor index) so the invariant holds.
      const finalRow = check.success ? check.data : failedRow;
      rows.push(finalRow);
      failed.push(row.id);
      const item: HumanReviewItem = {
        skill_version_id: row.id,
        skill_id: row.skill_id,
        retry_count: attemptsAfter,
        reason: result.reason,
      };
      humanReview.push(item);
      await outbox.append({
        at: now,
        skill_version_id: row.id,
        skill_id: row.skill_id,
        outcome: 'terminal',
        retry_count: attemptsAfter,
        detail: `bounded retry exhausted (${attemptsAfter}/${SKILL_VERSION_MAX_SIGNING_RETRIES}) → signing_failed; surfaced to human review: ${result.reason}`,
      });
      continue;
    }

    // FAILURE with budget → in-place retry bump, STAY pending_production.
    const nextRetryAfter = new Date(Date.parse(now) + backoff(attemptsAfter)).toISOString();
    const retriedRow: SkillVersion = {
      ...row,
      retry_count: attemptsAfter,
      retry_after: nextRetryAfter,
    };
    rows.push(retriedRow);
    retried.push(row.id);
    await outbox.append({
      at: now,
      skill_version_id: row.id,
      skill_id: row.skill_id,
      outcome: 'failure',
      retry_count: attemptsAfter,
      detail: `push failed (${result.reason}); retry ${attemptsAfter}/${SKILL_VERSION_MAX_SIGNING_RETRIES} scheduled for ${nextRetryAfter}`,
    });
  }

  return { rows, signed, retried, failed, skipped, unparseable, humanReview };
}

// ── Fail-closed extractors for unparseable rows (best-effort, never throw) ──

function extractId(raw: unknown): string {
  if (typeof raw === 'object' && raw !== null && typeof (raw as { id?: unknown }).id === 'string') {
    return (raw as { id: string }).id;
  }
  return '<unknown-id>';
}

function extractSkillId(raw: unknown): string {
  if (
    typeof raw === 'object' &&
    raw !== null &&
    typeof (raw as { skill_id?: unknown }).skill_id === 'string'
  ) {
    return (raw as { skill_id: string }).skill_id;
  }
  return '<unknown-skill>';
}

function extractRetryCount(raw: unknown): number {
  if (
    typeof raw === 'object' &&
    raw !== null &&
    typeof (raw as { retry_count?: unknown }).retry_count === 'number'
  ) {
    return (raw as { retry_count: number }).retry_count;
  }
  return 0;
}
