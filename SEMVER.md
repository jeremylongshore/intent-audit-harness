# SemVer commitment — @intentsolutions/audit-harness

> Source of truth for what counts as a breaking change in this package. Engineers and AI
> contributors **MUST** read this before modifying the CLI surface, exit codes, or output streams.

## TL;DR

The audit-harness CLI surface is consumed by pre-commit hooks, CI pipelines, and the
[`audit-tests`](https://www.npmjs.com/package/@intentsolutions/audit-harness) + `implement-tests`
Claude Code skills across multiple Intent Solutions repositories. Breaking that surface breaks
adopter CI. **We do not break it lightly.**

| Change | Semver impact |
|---|---|
| Add a new subcommand (e.g. `emit-evidence`) | **minor** — additive |
| Add a new flag to an existing subcommand (e.g. `--json`) | **minor** — additive |
| Add a new optional field to a JSON output envelope | **minor** — additive |
| Add a new exit code (numerically new value) for a new failure class | **minor** — additive |
| Change existing default text output | **major** |
| Change existing exit code for the same input | **major** |
| Remove or rename a subcommand or flag | **major** |
| Tighten an input regex or enum that previously accepted a value | **major** |
| Move output between stdout/stderr for the same flag combination | **major** |
| Change the `predicateType` URI referenced by `emit-evidence` | **major** |

Anything ambiguous → cut a major version. The cost of a major-version bump is far smaller than
the cost of a silent CI breakage across N adopter repositories.

## Stable contracts

### Exit codes (per command)

| Command | Exit | Meaning | Stable since |
|---|---|---|---|
| `escape-scan` | 0 | clean | v0.1.0 |
| `escape-scan` | 1 | CHALLENGE (engineer-approved comment required) | v0.1.0 |
| `escape-scan` | 2 | REFUSE (pipeline halted) | v0.1.0 |
| `verify` (harness-hash) | 0 | OK | v0.1.0 |
| `verify` | 2 | HARNESS_TAMPERED | v0.1.0 |
| `verify` | 3 | no manifest | v0.1.0 |
| `crap` | 0 | within thresholds | v0.1.0 |
| `crap` | 1 | thresholds exceeded | v0.1.0 |
| `crap` | 2 | unsupported language | v0.1.0 |
| `arch` | 0 | rules pass | v0.1.0 |
| `arch` | 1 | rule violations | v0.1.0 |
| `arch` | 2 | no tool / no config / unsupported | v0.1.0 |
| `gherkin-lint` | 0 | clean / warnings (non-strict) | v0.1.0 |
| `gherkin-lint` | 1 | errors or warnings (strict) | v0.1.0 |
| `gherkin-lint` | 2 | path not found | v0.1.0 |
| `bias` | 0 | always (advisory gate) | v0.1.0 |
| `bias` | 1 | test directory not found | v0.1.0 |
| `emit-evidence` | 0 | Statement emitted | v0.3.0 |
| `emit-evidence` | 1 | input malformed | v0.3.0 |
| `emit-evidence` | 2 | cosign not installed (when --sign) | v0.3.0 |
| `emit-evidence` | 3 | Rekor push failed | v0.3.0 |
| `emit-evidence` | 4 | production DNSSEC/CAA pre-flight failed — REFUSE to sign (fail-closed; nothing anchored) | v1.2.0 |
| `report-lineage` | 0 | report is clean, or findings remain advisory | unreleased |
| `report-lineage` | 1 | `--strict` found unverifiable or mismatched lineage, including duplicate sample slots | unreleased |
| `report-lineage` | 2 | command-line usage error | unreleased |

### Stream contracts

| Mode | stdout | stderr |
|---|---|---|
| Text (no `--json`) — pre-v0.3.0 behavior | human-readable summary | severity notes (`[REFUSE]`, `[CHALLENGE]`, `[FLAG]`) |
| `--json` (v0.3.0+) | exactly one JSON object validating against [`evidence-bundle/v0.1.0-draft/schema/gate-result.schema.json`](https://github.com/jeremylongshore/intent-eval-lab/blob/main/specs/evidence-bundle/v0.1.0-draft/schema/gate-result.schema.json) | unchanged human-readable output (same content as text mode) |

The `--json` flag was deliberately designed so adopters can run gates in BOTH modes simultaneously
without parsing-script churn: stderr still produces the human-readable text it always did; stdout
either produces the existing text summary OR pure JSON. There is no third mode.

### `emit-evidence` predicate URI

`emit-evidence` emits in-toto Statement v1 with `predicateType = https://evals.intentsolutions.io/gate-result/v1`.

This URI is **frozen** once any signed Statement referencing it is pushed to a public transparency
log (Rekor). The path is also reserved exclusively for this predicate per the
[ISEDC v1 Q1 binding constraint (2026-05-10)](https://github.com/jeremylongshore/intent-eval-lab/blob/main/000-docs/004-AT-DECR-isedc-council-record-2026-05-10.md).

Breaking changes to the predicate body would mint a new URI (`gate-result/v2`); both URIs may
coexist. We will never silently change the body shape under the same URI.

### `emit-evidence` production DNSSEC + CAA pre-flight (v1.2.0)

Per the CISO binding (DR-010 Q5), pushing a signed Statement to a **public** transparency log
(Rekor) against `evals.intentsolutions.io` requires the namespace to be DNSSEC-signed AND
CAA-pinned first. When a production Rekor push is requested (`--rekor-url` / non-empty
`REKOR_URL`), `emit-evidence` runs `scripts/dnssec-check.sh` then `scripts/caa-check.sh` and
**refuses to sign (exit 4)** if either fails. The gate is read-only — it anchors nothing and can
only make signing *more* conservative (fail-closed). `EVIDENCE_SKIP_DNS_PREFLIGHT=1` skips it for
**non-production** flows only (no Rekor push); a production Rekor push can never be silently
skipped. This is an additive minor surface — non-Rekor and unsigned flows are unaffected.

## Adopter-facing guarantees

If you are an adopter pinning `@intentsolutions/audit-harness@^0.x.y`:

1. Your existing pre-commit hooks and CI calls will not break across minor versions in 0.x.
2. New gates / new flags are opt-in. The `--json` flag did not change any pre-existing default.
3. If you parse stdout of a gate, you will not see JSON in stdout unless you pass `--json`.
4. If you parse stderr, you will not see anything new there from minor versions.
5. The `emit-evidence` subcommand is opt-in. Pre-v0.3.0 callers do not see it; calling it
   without args prints help; calling with malformed input exits non-zero with a clear message.

## What we will never do

- Silently change an exit code for the same input.
- Move human-readable text from stdout to stderr (or vice-versa) under the same flag set.
- Re-use a removed subcommand name for a different gate.
- Change the predicate URI without bumping the URI path component (`v1` → `v2`).
- Skip a CHANGELOG entry for a CLI-surface change.

## Version history at a glance

| Version | Released | CLI surface delta |
|---|---|---|
| 0.1.0 | initial | 6 gates + `verify` / `init` / `list` |
| 0.2.0 | 2026-04 | Intentional Mapping terminology rename (internal docs only — zero CLI delta) |
| 0.3.0 | 2026-05 (Milestone 2) | `--json` on all 6 gates; new `emit-evidence` subcommand; SemVer doc; backward-compat regression suite. Additive minor. |
| 1.1.8+ | 2026-06 | new `cred-gate` subcommand (provider credential PASS/FAIL gate, iah-E08); `emit-evidence` now also fires the `gate.decision.emitted` OTel event (iah-E07b, per NORMATIVE intent-eval-lab `067-AT-SPEC` § 2.2: `gate.decision` enum `{pass, fail, advisory, error}` + `gate.name` + `gate.policy_ref`). Both additive. |
| (unreleased) | 2026-06 | new `migration-notes` subcommand (adopter-facing migration-notes generator, iah-E05d) — read-only, stdlib, emits Markdown or a `migration-notes/v1` envelope from this file + `CHANGELOG.md`. Additive. |
| (unreleased) | 2026-08 | new `report-lineage` subcommand — read-only, stdlib, emits a `gate-result/v1` row while verifying J-Rig Run/Grade/report projections, per-cell sample-slot uniqueness, and optional suite audit manifests. Additive. |

Future minor bumps add new gates, new flags, new optional fields in JSON metadata. Future major
bumps will be rare; we will hold a major-bump as a last resort.
