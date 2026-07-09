# signing-reconciler — CI-only, NON-PUBLISHED

The append-only Rekor **OUTBOX** + bounded-retry **reconciler** runtime for the
kernel SkillVersion signing state machine (**AC-2**, CISO **P0-RATIFY-2** — the
runtime half of bead `aon3.4`).

## Why it lives in `audit-harness/ci/`

`@intentsolutions/audit-harness` is a **zero-runtime-dependency** polyglot CLI.
This reconciler imports `@intentsolutions/core` (the kernel validators + state
machine), so it must NOT ship in the published package. `ci/` is **outside** the
`package.json#files` allowlist, exactly like `ci/emit-evidence.ts` — nothing here
reaches npm consumers and the published tarball stays zero-dep. This dir carries
its own `package.json` that pins `@intentsolutions/core@0.10.0` **exactly** so the
reconcile-time contract equals the published kernel.

Proof it never ships: `npm pack --dry-run | grep -c signing-reconciler` ⇒ `0`.

## What it does

It **consumes** — never reimplements — the state machine that
`@intentsolutions/core@0.10.0` publishes:

- legal transitions via the kernel `skillVersionSigningTransitions` +
  `canTransition`;
- the retry ceiling via the kernel `SKILL_VERSION_MAX_SIGNING_RETRIES` (never
  hardcodes `5`);
- every resulting row validated against the kernel `SkillVersionSchema` (the
  AT-DECR 011 § D3 cross-field invariant) before it is persisted.

`reconcile(pendingRows, { now, rekorTransport, outbox, backoff })` is a **pure,
deterministic** function over **injected seams** — the clock is a `now` param, the
Rekor push is a `RekorTransport`, persistence is an append-only `SigningOutbox`,
and the backoff is an injected policy. It never reads the wall clock or the
network directly, never blocks creation, and fails **closed** on an unparseable
row.

Per due `pending_production` row:

| transport result | outcome |
|---|---|
| success | → `active` + `signing_mode='rekor_production'` + `rekor_log_index`; kernel-validated; outbox **success** record |
| failure, budget left | `retry_count++`, new bounded `retry_after`; **stays** `pending_production`; outbox **failure** record |
| failure at ceiling | → `signing_failed` + human-review escalation; outbox **terminal** record |

## STAGING-FIRST — this activates nothing

The default `NoopRekorTransport` always returns `delivered: false` and never fakes
a push. The **real** production-Rekor push is **STAGING-FIRST / DR-082-Q3-gated**
(dispatch-only, dry-run-default, human-gated VPS wiring) — a documented seam, NOT
wired live here. A bare `npm run reconcile` is a dry-run reporter.

## Run

```bash
npm install                                   # installs @intentsolutions/core@0.10.0 (CI-only, this dir)
npm test                                       # node --test, deterministic
node --experimental-strip-types src/cli.ts \
  --rows rows.json --now 2026-07-09T01:00:00Z \
  --outbox build/signing-outbox.jsonl [--json] # what a VPS cron invokes
```
