# Shared deterministic validators

`audit-harness conform . --shared-validators` adds the pinned marketplace-authored
agent body/tool-list check to discovered agent conformance rows. It works with
both schema tiers; the option is off by default and does not change discovery or
add gates excluded by a supplied profile. Currently only agents have a shared
check. This is one extracted deterministic check, not the complete `/validate-*`
workflow, rubric or behavioral evaluation.

The checker compares lexical MCP references in Markdown against declared tools.
Its original errors and warnings remain distinct. Errors are advisory unless
`--strict` or the selected gate's blocking policy makes them failures. Warnings
remain advisory, including under `--strict`. Schema violations continue to fail
when appropriate even if the shared implementation cannot be measured.

These findings do not prove tool invocation or denial. In particular, the legacy
checker treats omitted and explicitly empty `tools` alike, although a host may
inherit tools when the field is omitted. Prose can describe another agent's calls;
short-name matches are heuristic. Result metadata labels the findings as static
and records these limits. Selecting the option selects this lexical policy;
existing schema-only defaults retain their previous behavior.

Frontmatter, body and input hash come from one bounded original-byte snapshot.
The reader refuses unsafe paths and ambiguous mappings and leaves unsupported
YAML aliases or resource limits unmeasured. The policy hash combines the selected
schema policy with a shared-validator manifest hash. That manifest identifies the
source repository, full Git commit, module bytes and MIT notice. Hashes identify
content; they do not replace repository and release trust.

Before loading the checker, the harness verifies both the module and license
bytes. It executes the exact verified module snapshot rather than importing a
second read through the working directory or import cache. Missing files, changed
hashes or unsupported findings produce explicit indeterminate advisories. The
module uses only Python's standard library; parsing frontmatter still requires
PyYAML. No network request or provider call is part of the check.

The authoring home remains the marketplace repository identified by
[the provenance pin](../schemas/conform/shared-validators/agent-body-tools.json).
The vendored implementation is unchanged; source updates must be qualified there,
then copied with the corresponding full commit and hashes, corpus/CLI checks and
ordinary protected-file repinning. The complete third-party license is retained
[in the bundled MIT notice](../schemas/conform/shared-validators/marketplace-LICENSE).
Other harness code remains under its existing license.
