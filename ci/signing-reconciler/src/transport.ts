/**
 * transport.ts — the RekorTransport seam + the default NoopRekorTransport.
 *
 * ── STAGING-FIRST / DR-082-Q3-gated — this runtime ACTIVATES NOTHING ──
 *
 * The default {@link NoopRekorTransport} ALWAYS returns `{ delivered: false }`.
 * It NEVER fakes a push and NEVER fabricates a Rekor log index. This mirrors the
 * platform's other Noop transports (j-rig, intent-rollout-gate): the seam is
 * present and honest, but the live production-Rekor push is a SEPARATE, HUMAN-
 * GATED wiring that does NOT run from here.
 *
 * The REAL production-Rekor push is AND-gated on the four DR-082 Q3 triggers
 * (SPEC.md normative section landed; DNSSEC + CAA pre-flight on
 * `evals.intentsolutions.io`; dispatch-only workflow; dry-run-default) — exactly
 * the same gate that blocks `scripts/emit-evidence.sh`'s `--sign` path. Wiring a
 * concrete Rekor transport in place of the Noop is a deliberate operator action
 * behind that gate, NOT something this reconciler turns on by existing.
 */

import type { BackoffPolicy, RekorPushResult, RekorTransport, SkillVersion } from './types.ts';

/**
 * The default, safe transport. Returns `delivered: false` for every row —
 * production signing is off until an operator injects a real transport behind the
 * DR-082 Q3 gate. NEVER fakes delivery; NEVER supplies a log index.
 */
export class NoopRekorTransport implements RekorTransport {
  push(_version: SkillVersion): Promise<RekorPushResult> {
    return Promise.resolve({
      delivered: false,
      reason:
        'NoopRekorTransport: production-Rekor push is STAGING-FIRST / DR-082-Q3-gated (dispatch-only, dry-run-default, human-gated VPS wiring). This runtime activates nothing.',
    });
  }
}

/**
 * Default bounded exponential backoff: 2^attempts minutes, capped at 60 minutes.
 * `attempts` is the retry_count AFTER the just-recorded attempt (1-based), so the
 * first failure schedules ~2 min, the second ~4 min, and so on, never exceeding
 * an hour. Pure + injected so the retry cadence is policy, not a magic literal.
 */
export const defaultBackoff: BackoffPolicy = (retryCountAfterThisAttempt: number): number => {
  const minutes = Math.min(60, 2 ** Math.max(1, retryCountAfterThisAttempt));
  return minutes * 60_000;
};
