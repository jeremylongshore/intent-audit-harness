# `cred-gate` — provider credential PASS/FAIL gate (iah-E08)

CISO non-negotiable per DR-010 S1Q5. Before any provider abstraction is allowed
to flow data into an Evidence Bundle / OTel signal / gate-result envelope, the
`cred-gate` gate proves — deterministically and offline — that:

1. **Credential redaction** — no provider secret VALUE appears verbatim in the
   candidate artifact (the JSON the runner is about to sign, the OTel line it is
   about to emit, any log it captures). A leaked API key in a signed,
   Rekor-anchored in-toto Statement is irreversible.
2. **No env-var spillover** — the candidate artifact does not blindly serialize
   the process environment. A provider key need not be named to leak: a wholesale
   `env` dump spills every secret at once.

## Usage

```bash
# Candidate on stdin (the artifact about to be emitted/signed):
producer | audit-harness cred-gate

# Candidate from a file:
audit-harness cred-gate --input candidate.json

# Declare secrets by env-var NAME (the VALUE is read from the environment and
# never appears on the command line / in `ps`):
audit-harness cred-gate --secret-env ANTHROPIC_API_KEY --secret-env OPENAI_API_KEY < cand.json

# Emit a gate-result/v1 envelope, pipe-ready for emit-evidence:
audit-harness cred-gate --json < candidate.json | audit-harness emit-evidence
```

## Exit codes

| Code | Meaning |
| ---- | ------- |
| `0`  | **PASS** — no secret value present, no provider-key shape, no env-var spillover |
| `1`  | **FAIL** — a secret value leaked OR a provider-key shape matched OR env-var spillover detected |
| `2`  | usage / input error (no candidate, unreadable `--input`) |

## What it detects

### Detected provider-key shapes (value-agnostic catalog)

These match the on-the-wire SHAPE of a known provider key, so a raw key is caught
even when it was not declared via `--secret-env`. Patterns are intentionally
specific to keep the false-positive rate low.

| Name | Shape (regex fragment) |
| ---- | ---------------------- |
| `anthropic-key` | `sk-ant-…` |
| `openai-key` | `sk-…` / `sk-proj-…` (excludes `sk-ant-`) |
| `groq-key` | `gsk_…` |
| `nvidia-key` | `nvapi-…` |
| `aws-access-key-id` | `AKIA…` |
| `google-api-key` | `AIza…` |
| `github-token` | `ghp_` / `gho_` / `ghs_` / `ghr_` / `ghu_…` |
| `slack-token` | `xoxb-` / `xoxa-` / `xoxp-` / `xoxr-` / `xoxs-…` |
| `private-key-block` | `-----BEGIN … PRIVATE KEY-----` |

### Env-var spillover heuristics

| Name | What it catches |
| ---- | --------------- |
| `process-env-spread` | `...process.env` (JS object spread of the whole environment) |
| `os-environ-dump` | `dict(os.environ)` / a bare `os.environ` serialized into JSON |
| `env-block-key` | an `"env"` / `"environ"` / `"environment"` object key whose value is a `{…}` block |
| `printenv-capture` | a `printenv` / `/usr/bin/env` invocation captured into the artifact |

A spillover match is a hard **FAIL**: an environment dump inside a to-be-signed
artifact is exactly the irreversible leak this gate exists to stop.

## False-positive posture

- **Declared secrets shorter than 8 chars are ignored** — a 1-char "secret"
  would false-positive on virtually any artifact and is not a real credential.
- **The word "environment" in prose is NOT a spillover** — only the structural
  `"env"/"environment": { … }` block shape, the `...process.env` spread, the
  `os.environ` dump, or a `printenv` capture flag. (See the `tests/cred-gate`
  FP-guard assertion.)
- The shape catalog is conservative by design; promotion from advisory to
  blocking elsewhere in the harness follows `docs/gate-promotion.md`.

## No re-leak guarantee

When a declared secret leaks, the FAIL finding **never echoes the secret value
back**. It reports only the value's length and a non-reversible SHA-256
fingerprint prefix, so the finding is actionable without re-leaking. The
`tests/cred-gate` suite asserts this explicitly.

## Remediation when the gate FAILs

| Finding kind | Fix |
| ------------ | --- |
| `secret-value-leak` | Remove the literal secret from the artifact. Pass an opaque reference (key NAME, a hash, or a vault path) instead of the value. |
| `secret-shape-match` | A raw provider key is embedded. Strip it; if it is a real credential, treat it as compromised and rotate. |
| `env-spillover` | Stop serializing the whole environment. Allowlist the specific non-secret fields you actually need (`os.getenv("X")` per key), never `dict(os.environ)` / `{...process.env}`. |

## Safety + scope

- **Offline + read-only**: never contacts a provider, never reads a real key
  from disk, never writes.
- **Secret values via env-var NAME only**: `--secret-env NAME` reads `$NAME`
  through indirect expansion; the value never appears on `argv` (so it is not
  visible to `ps`), and the candidate + secret blob are passed to the python
  analyzer through the environment, not the command line.
- **Kill-switch aware**: `cred-gate` is in `KILLABLE_GATES`, so
  `AUDIT_HARNESS_DISABLE=1` no-ops it (exit 0, banner) like the other gates.
- **Timeout aware**: `AUDIT_HARNESS_TIMEOUT=N` supervises it like every gate.

## CI (iah-E08c)

The `cred-gate` CI lane in `.github/workflows/ci.yml` runs
`tests/cred-gate/run-cred-gate-tests.sh`, which proves the credential-redaction
fixture (E08a), the env-var spillover fixture (E08b), the `--json` envelope
round-trip, and — because the same suite also exercises `emit-evidence.sh` — the
`agent.rollout.gate.decision` OTel event (iah-E07b). Both must pass for the lane
to be green.
