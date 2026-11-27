# Skill compliance evidence gate

`skill-gates` is a read-only, offline, zero-dependency verifier for the bounded
IEP skills/hooks pilot. It checks local observations and emits the existing
`gate-result/v1` row. It never runs authored commands, writes state, fetches
schemas, installs hooks or changes rollout policy.

```bash
audit-harness skill-gates --policy gates.json --receipt receipt.json \
  --root /absolute/workspace --session SESSION_HASH \
  --collector /absolute/skill-gates-claude.py --json
```

The J-Rig collector hashes the raw Claude session ID with SHA256; supply that
hash as `SESSION_HASH` when verifying its receipt independently. Its private
`state.json` wraps the receipt in a `receipt` property; extract that value to a
separate JSON file for this command. No source file is modified by verification.
By default, missing or invalid evidence yields ADVISORY/exit 0. `--strict`
yields FAIL/exit 1. Only complete current evidence yields PASS. Configured
observe/enforce mode governs the host adapter; the verifier's own strictness is
explicit, so changing a host setting cannot silently promote a CI gate.

## Operational policy and receipt

The versioned `audit-harness/skill-gates/v1` policy is an experimental harness
configuration, not a canonical kernel artifact or an Agent Skills standard.
Its exact fields are `schema`, `mode` (`observe` or `enforce`), `skill`, `inputs`,
`must_read`, `must_run`, `checklist`, and `deny_tools`. Unknown fields and duplicate
JSON keys are rejected. The executable validation in `scripts/skill-gates.py`
is authority for this operational protocol. The runnable example and collector
are in J-Rig's `examples/skill-gates/` and `scripts/skill-gates-claude.py`.

Inputs and reads are explicit relative regular files, at most 1 MiB each. Paths
cannot be absolute, contain traversal or leave the workspace through a symlink.
Commands declare a unique `id`, shell-free `argv`, `timeout_ms` (1–600000), and
`min_tests` (a positive integer). Their completed stdout must be a JSON object
with integer `tests_passed` and `tests_failed`. No failure or skip count can
substitute for the required minimum successful tests. Declared commands and
their reports are trusted reviewed code, not an adversarial execution oracle.

The `audit-harness/skill-gate-receipt/v1` receipt has exact top-level fields
`schema`, `session`, `identity`, `reads`, `commands`, and `report`.
Identity binds absolute workspace, exact policy bytes, declared input hashes,
file arguments to commands, resolved executable bytes, Python binary/version,
and verifier/collector source bytes. Each command and report binds the whole
identity digest. A source/config/tool change invalidates prior evidence even
when the old process exited zero. Missing executables and unsupported schemas
remain unavailable evidence. Freshness covers only the authored inventory;
environment variables, undeclared inputs and external state remain unbound.

The result row carries policy and receipt digests, findings, reported checklist
and `trusted_local_evidence: true`. `commit_sha` is `unknown`; content hashes are
the freshness identity, and no Git or signed provenance claim is invented.
The row is unsigned until handled by the existing evidence-signing pipeline.
Acceptance of the row format does not automatically enroll this gate in a
rollout policy or make an advisory result blocking.

## Evidence limits and verification

A read receipt proves the collector accessed all file bytes, not that the model
understood them. A run receipt proves the trusted collector observed a declared
process and machine test counts, not that the tests are sufficient. A checklist
receipt records a structured report; it does not inspect final assistant prose.
The same OS user can modify receipts. Independent CI and review remain needed
for higher trust, detector-quality labels and output correctness.

Run `python3 tests/skill-gates/test_skill_gates.py` for verifier falsification
fixtures. It is part of `npm test` and the existing report-lineage CI lane.
J-Rig's replay suite additionally tests host decisions and real subprocess
failure/recovery. The canonical kernel remains the only authority for platform
contracts; its pending adoption decisions are separate from this pilot.
