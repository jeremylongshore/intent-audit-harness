/**
 * types.ts — the injected-seam contracts for the SkillVersion signing reconciler
 * (AC-2, CISO P0-RATIFY-2). Pure interfaces; NO side effects.
 *
 * ── Why these are SEAMS, not concrete calls ──
 *
 * The platform's runtime discipline (mirrored from j-rig / intent-rollout-gate)
 * is that a reconciler NEVER reaches for the wall clock, the network, or a
 * concrete store directly. Every impure edge is an INJECTED interface so the
 * `reconcile()` core stays a PURE, DETERMINISTIC function:
 *
 *   - the clock is a `now` PARAMETER, never `new Date()`;
 *   - the Rekor push is a `RekorTransport`, never a direct fetch;
 *   - persistence is an append-only `SigningOutbox`, never a bare `fs.writeFile`.
 *
 * This makes the whole retry/backoff/exhaustion logic unit-testable with zero
 * mocking of globals — you hand it a fixed `now`, a scripted transport, and an
 * in-memory outbox, and assert the outcome.
 */

/**
 * The canonical SkillVersion row shape the reconciler drives, imported from the
 * kernel Zod validator. We NEVER redefine the entity here — the type flows from
 * `@intentsolutions/core` so the reconciler and the kernel agree by construction.
 */
export type { SkillVersion } from '@intentsolutions/core/validators/v1/skill-version';

/**
 * Result of a single Rekor push attempt via the injected transport. On success
 * the transport reports the production transparency-log index the row will carry.
 * A `delivered: false` result NEVER carries a `logIndex` (the reconciler refuses
 * to fabricate an `active` row without a real index — the kernel cross-field
 * invariant would reject it anyway).
 */
export type RekorPushResult =
  | { readonly delivered: true; readonly logIndex: number }
  | { readonly delivered: false; readonly reason: string };

/**
 * Injected Rekor push seam. The reconciler calls this for each due
 * `pending_production` row. The DEFAULT impl ({@link NoopRekorTransport}) always
 * returns `{ delivered: false }` — the REAL production-Rekor push is STAGING-FIRST
 * / DR-082-Q3-gated (dispatch-only, dry-run-default, human-gated VPS wiring) and
 * is NOT wired live from this runtime. This reconciler ACTIVATES NOTHING.
 */
export interface RekorTransport {
  /**
   * Attempt to push a SkillVersion's signature to the production Rekor log.
   * @param version the row being signed (read-only; the transport MUST NOT mutate it)
   * @returns delivery outcome; a real transport supplies the production log index
   */
  push(version: import('@intentsolutions/core/validators/v1/skill-version').SkillVersion): Promise<RekorPushResult>;
}

/**
 * One append-only record in the signing OUTBOX (AC-2). DISTINCT from Rekor's own
 * append-only log: this is audit-harness's local, ordered, never-mutated ledger of
 * every signing ATTEMPT the reconciler made, whatever the outcome. Records are
 * only ever appended — never updated or deleted — so the ledger is a complete,
 * replayable history.
 */
export interface OutboxRecord {
  /** RFC 3339 UTC timestamp of the attempt — the injected `now`, never the wall clock. */
  readonly at: string;
  /** The SkillVersion id the attempt was for. */
  readonly skill_version_id: string;
  /** The skill this version belongs to (for human-review triage). */
  readonly skill_id: string;
  /** Outcome of this attempt. `terminal` = the row exhausted retries → signing_failed. */
  readonly outcome: 'success' | 'failure' | 'terminal' | 'skipped';
  /** retry_count AFTER this attempt was accounted for. */
  readonly retry_count: number;
  /** Production Rekor log index, present ONLY on `outcome: 'success'`. */
  readonly rekor_log_index?: number;
  /** Human-readable reason (failure detail, skip cause, or terminal escalation note). */
  readonly detail: string;
}

/**
 * Append-only signing OUTBOX seam (AC-2). Records are appended in order; the
 * interface deliberately exposes NO update/delete — an append-only store cannot
 * rewrite history. The reconciler depends on this interface, not a concrete file,
 * so tests inject an in-memory implementation.
 */
export interface SigningOutbox {
  /** Append one record. MUST NOT mutate or remove any prior record. */
  append(record: OutboxRecord): Promise<void>;
  /** Read the full ordered history (oldest first). For audit / replay / assertions. */
  all(): Promise<readonly OutboxRecord[]>;
}

/**
 * A structured human-review escalation, emitted (as an outbox `terminal` record
 * AND surfaced in the reconcile report) when a row exhausts its bounded retries
 * and lands `signing_failed`. This is the CISO bounded-retry escape hatch: a stuck
 * row escalates to a human, it never spins forever.
 */
export interface HumanReviewItem {
  readonly skill_version_id: string;
  readonly skill_id: string;
  readonly retry_count: number;
  readonly reason: string;
}

/**
 * Backoff policy: given the attempt count SO FAR, return how many milliseconds
 * from `now` the next `retry_after` floor should be. Injected so tests are
 * deterministic and the bound is policy, not a magic number in the loop body.
 */
export type BackoffPolicy = (retryCountAfterThisAttempt: number) => number;
