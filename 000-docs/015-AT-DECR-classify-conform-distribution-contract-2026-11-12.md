# Classification and conformance distribution contract

Status: maintainer decision, effective with this documentation change.
Refs bead `bd_000-projects-dn6j.20`.

## Decision

Use the canonical npm package or the vendored `install.sh` channel for `classify`
and `conform`. Do not add these verbs or their schema assets to the Rust wrapper
or frozen Python distribution in this change. Preserve every existing wrapper
command; no release, version bump, package retirement, or gate weakening is part
of this decision.

| Channel | `classify` / `conform` | Registry and conformance schemas |
| --- | --- | --- |
| npm | Supported | Included by the package `files` list |
| `install.sh` | Supported by `scripts/audit-harness` | Copied into `.audit-harness/schemas`, recorded in `PROVENANCE` |
| Rust wrapper | Not dispatched | Not embedded |
| Python wrapper | Not dispatched; PyPI remains frozen at `1.4.0` | Not bundled |

The audited project's language does not select the harness distribution. Python
and Rust repositories can use either supported conformance channel. A wrapper
version number alone does not establish feature parity with npm.

## Evidence and rationale

Source inspected at `97b6e0cc9bb84e4f474a928237e19183f71a7147`:

- `bin/audit-harness.js` dispatches both verbs; `package.json` ships `schemas`.
- `install.sh` copies the schema tree, records schema hashes in `PROVENANCE`, and
  dispatches both verbs from its generated wrapper. The existing `tests/install/`
  suite covers offline installation and conformance.
- `rust/src/main.rs` embeds the legacy script set and dispatches eight commands;
  neither requested verb appears in its command map.
- `python/src/intent_audit_harness/cli.py` also dispatches those eight commands.
  The root README records the PyPI freeze; the current release workflow has no
  PyPI publishing job. This is source evidence, not a new registry publication audit.

Adding dispatch entries alone would be incomplete: both verbs resolve their
registry and content-addressed policy files relative to the scripts. Each wrapper
would need asset packaging, extraction/path behavior and packaged-artifact
qualification. The two existing supported channels already provide those assets
without another policy copy or reopening the frozen Python release channel.

## Consumer selection

For a project with the npm dependency installed, select its local binary explicitly:

```bash
pnpm exec audit-harness classify .
pnpm exec audit-harness conform . --tier marketplace --strict
```

For a project using the vendored installer:

```bash
scripts/audit-harness classify .
scripts/audit-harness conform . --tier marketplace --strict
```

Use a reviewed package lock or installer release pin and retain provenance. Do
not use an unqualified `audit-harness` on `PATH` when several wrappers are
installed: it may select the Rust or frozen Python command instead. An unsupported
command is not a successful conformance result; never treat it as a passed gate.

Existing strictness and kernel-schema pinning remain unchanged. Expanding a
wrapper later requires a separate implementation and release with installed
artifact tests proving both verb dispatch and identical schema hashes. Reverting
this documentation does not change the actual command maps or unfreeze PyPI.
