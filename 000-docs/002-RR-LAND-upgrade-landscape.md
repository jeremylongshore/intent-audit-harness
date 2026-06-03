# Upgrade Landscape — audit-harness in the Three-repo Convergence

| Field | Value |
|---|---|
| **Date** | 2026-05-10 |
| **Author** | Jeremy Longshore |
| **Status** | Draft v1.0 — Part 2 research deliverable (research workstream A) |
| **Source plan** | Author's local working source (private to Intent Solutions workspace; not part of this repository). Public-facing companion docs in `intent-eval-lab/000-docs/003-PP-PLAN-phase-b-scope-refinement.md` (synthesis) + `intent-eval-lab/000-docs/004-AT-DECR-isedc-council-record-2026-05-10.md` (Decision Record). |
| **Companion specs** | `000-docs/001-DR-DESIGN-evidence-bundle-envelope-design-notes.md` (AH-4) · `intent-eval-lab/specs/evidence-bundle/v0.1.0-draft/` (IEL-4) |
| **Scope** | Landscape mapping — NOT implementation guidance, NOT a refactor plan |

---

## 1. Mission & scope

`audit-harness` today is a **deterministic test-enforcement toolkit** — a thin Node CLI (`bin/audit-harness.js`) dispatching six battle-tested scripts that cover Layer 1 (hash-pinning + escape-scan against AI test gaming) and parts of Layer 3 (CRAP × coverage scoring, architecture-rule pinning, bias counting, Gherkin lint) of the 7-layer testing taxonomy.

The **three-repo convergence** (`intent-eval-lab` + `audit-harness` + `j-rig-binary-eval`) needs the harness to do more than gate a single repo's pre-commit: it must **emit signed, schema-versioned gate-result rows** that compose into an Evidence Bundle the other two repos consume. This document maps the academic and industry landscape that informs *what the upgraded harness should look like* — primary sources, OSS leaders to study, borrowable patterns, and a concrete Phase-B work-item slate.

This is a **research deliverable**, not a refactor PR. Implementation lives behind `AH-2`, `AH-3`, `AH-5` and the Phase-B issues those spawn.

---

## 2. Empirical anchor — current audit-harness shape

Grounding the rest of this document in what's actually on disk today (verified files: `bin/audit-harness.js`, `scripts/{harness-hash,escape-scan,arch-check,bias-count,gherkin-lint}.sh`, `scripts/crap-score.py`, `000-docs/001-DR-DESIGN-evidence-bundle-envelope-design-notes.md`).

| Capability | Implementation | Layer | Output today |
|---|---|---|---|
| Hash manifest of engineer-owned artifacts | `scripts/harness-hash.sh` (SHA-256 pinning of `.feature`, dep-cruiser, ArchUnit, Stryker config, `.c8rc.json`) | L1 gate | text + exit code (0/2/3) |
| AI-diff escape detection | `scripts/escape-scan.sh` (REFUSE/CHALLENGE/FLAG grammar; reads thresholds from `tests/TESTING.md`) | L1 gate | text + exit code (0/1/2) |
| Architecture rule check | `scripts/arch-check.sh` (dispatches dep-cruiser / import-linter / ArchUnit etc.) | L3 Wall 7 | text + exit |
| Test-bias pattern count | `scripts/bias-count.sh` (smoke-only, tautology, symmetric input regexes) | L3 advisory | stdout text |
| Gherkin lint | `scripts/gherkin-lint.sh` | L7 advisory | stdout text |
| CRAP × coverage scoring | `scripts/crap-score.py` (multi-language: Python/JS/Go/Rust/Java/PHP/Ruby/.NET via radon, c8, gocyclo, rust-code-analysis; `CRAP(m) = C² × (1 - cov)³ + C`) | L3 Walls 5+6 | CSV + JSON |

**What the harness does NOT do today** (gap surface for convergence):

- No machine-readable envelope on most subcommands (`crap-score.py` is the lone JSON emitter; the rest are text + exit codes).
- No `emit-evidence` subcommand → no Evidence Bundle row production.
- No signing or transparency-log integration.
- No L2 SAST / SBOM / secret-scan dispatch.
- No L3 mutation-testing dispatch (Stryker/PIT/mutmut/cargo-mutants config can be hash-pinned, but the harness does not run them or score the kill-rate).
- No MCP/agent-specific conformance gates (the j-rig/intent-eval-lab side cares about agent behavior; the harness has no hooks for it yet).

The Phase-A envelope design (`001-DR-DESIGN-…`) already commits to JSON Schema 2020-12, SemVer `schema_version`, hash-pinnable `policy_hash` + `input_hash`, idempotent emission, no-PII. The convergence question is: **which prior-art envelope do we sit on top of, and which OSS scoring patterns do we borrow for the gates that don't exist yet?**

---

## 3. Academic state-of-the-art

Targeted papers that anchor the design choices below. All retrieved via Semantic Scholar.

| # | Citation | Why it matters |
|---|---|---|
| 1 | Jia, Y. & Harman, M. **"An Analysis and Survey of the Development of Mutation Testing."** *IEEE Trans. Software Engineering* (1,818 citations). [paper](https://www.semanticscholar.org/paper/d7c38286734419b52de4262c9802ebdfcf4b9447) | Foundational survey establishing mutation-score as the gold-standard test-quality metric beyond line coverage. Cited by every modern mutation tool. Justifies why Wall 4 ("kill-rate ≥ 70%") sits above coverage-only gates. |
| 2 | Sánchez, A. B., Parejo, J. A., Segura, S., Durán, A. & Papadakis, M. **"Mutation Testing in Practice: Insights From Open-Source Software Developers."** *IEEE TSE* (2024, CCBY). [paper](https://www.semanticscholar.org/paper/dd96541648125a3eab01f2bdc5e80d24f10de6ec) | Survey of 104 OSS contributors. Key finding: **performance is the dominant barrier**, not adoption willingness. Implication for the harness: any mutation gate we add must run in CI on changed-code-only mode (PIT's incremental analysis pattern), not full-tree. |
| 3 | Suh, H., Tafreshipour, M., Li, J., Bhattiprolu, A. & Ahmed, I. **"An Empirical Study on Automatically Detecting AI-Generated Source Code: How Far are We?"** *ICSE 2025* (20 citations). [paper](https://www.semanticscholar.org/paper/e41ceafe77d394b650430ff144cd87811fcc27f4) | Existing AI-code detectors generalize poorly. Best classifier (AST + static metrics + fine-tuned LLM) reaches F1 82.55. **Implication:** "is this test AI-generated?" cannot be a single deterministic check — the harness's escape-scan grammar (REFUSE/CHALLENGE/FLAG) is a *more honest* posture than a binary detector. |
| 4 | Zeng, Z. et al. **"Benchmarking and Studying the LLM-based Code Review."** *arXiv 2025* (SWRBench, 8 citations). [paper](https://www.semanticscholar.org/paper/ba3c99d34d03c47b99f07f30e65b7b599b20b243) | 1,000-PR benchmark for AI code reviewers. **Multi-reviewer aggregation boosts F1 by up to 43.67%**. Direct argument for the j-rig "binary eval" pattern: aggregate several gate verdicts (CRAP, mutation kill-rate, escape-scan, AI-reviewer score) into one evidence row, not one verdict. |
| 5 | Melara, M. S. **"Software Supply Chain Attribute Integrity (SCAI)."** *arXiv 2022*. [paper](https://www.semanticscholar.org/paper/2415020c4faaa61c9f78607f12299781690a8c25) | Defines a data format for *functional attribute + integrity information* of software artifacts. SCAI is registered as an in-toto predicate type. Direct precedent for "test-gate result" as an in-toto predicate. |
| 6 | Syed, T. A. et al. **"Agentic AI for Autonomous Defense in Software Supply Chain Security: Beyond Provenance to Vulnerability Mitigation."** *Int. Conf. Computing Advancements 2025*. [paper](https://www.semanticscholar.org/paper/7ef12e7f28b538a044f3b2c2af4160446723a200) | Frames SLSA + SBOM + in-toto as **necessary but insufficient** — they prove what was built but not what's safe to merge. The Evidence Bundle plays the same role for *test quality* that SCAI plays for *binary integrity*. |
| 7 | Hemmat, A. et al. **"Advanced Mutation Testing with Zero and Few-Shot Evaluation Using GPT-V4."** *IoT 2025*. [paper](https://www.semanticscholar.org/paper/eaac22fe50ba4fa2dd93224892963890f7f0d649) | LLM-driven mutation generation as a new branch of the field. Forward-looking flag: in 12–24 months the harness's mutation layer will likely dispatch an LLM-mutation step alongside Stryker/PIT. Architect for that. |

**Origin of the CRAP metric.** Note: a direct semantic-scholar query for Savoia/Evans/Crap4j did not surface the original 2007 trade-press article (which lives at [`www.artima.com/weblogs/viewpost.jsp?thread=210575`](https://www.artima.com/weblogs/viewpost.jsp?thread=210575) — Alberto Savoia's column introducing CRAP, complexity-times-coverage). The formula in `crap-score.py` is `C² × (1 - cov)³ + C` where `cov` is the coverage *fraction* (0.0 ≤ cov ≤ 1.0); this matches Savoia & Evans's original definition (Crap4j was the reference Java implementation, expressing the same relation as percentages). The metric has *never* had a peer-reviewed primary citation — it's industry-original, which is worth flagging when defending the gate to academic reviewers.

---

## 4. Industry landscape — competitor scan

Ten-plus tools the harness should be benchmarked against, with explicit license and borrowability notes. Sorted by capability layer.

| Tool | License | Layer / Role | borrowability for audit-harness | Primary URL |
|---|---|---|---|---|
| **SonarQube** Community Edition | LGPL v3 | Multi-layer SAST + quality-gate engine | **Quality Gate concept** (named, versioned threshold bundles, pass/fail at the bundle, not the rule) is the closest industry analog to what `tests/TESTING.md` is becoming. Borrow the quality-gate-as-named-entity pattern. | [sonarsource.com/products/sonarqube](https://www.sonarsource.com/products/sonarqube/) |
| **Semgrep OSS** | LGPL 2.1 | L2 SAST + secrets + SCA | YAML rule format + Semgrep Registry pattern for community rules. Borrow: rule hash-pinning is already in their CI playbook (we pin Stryker/dep-cruiser configs — extend to Semgrep rules). | [Semgrep](https://semgrep.dev/) |
| **OpenSSF Scorecard** | Apache 2.0 | Cross-layer repo health | **Risk-stratified score weighting** (critical=10, high=7.5, medium=5, low=2.5) is directly portable to the Evidence Bundle. JSON output via `--format=json`; REST API at `api.scorecard.dev`. | [github.com/ossf/scorecard](https://github.com/ossf/scorecard) |
| **PIT (PITest)** | Apache 2.0 (tool) | L3 mutation testing (JVM) | **Incremental mutation** (changed-code-only mode) is the answer to Sánchez et al.'s "performance is the #1 barrier" finding. Borrow the incremental-analysis CI pattern even though we won't bundle PIT. | [PITest](https://pitest.org/) |
| **Stryker** (JS/.NET/Scala) | Apache 2.0 | L3 mutation testing | Org-level pattern: **language-specific implementations + shared visualization layer** ("Mutation Testing Elements"). Our equivalent: per-language scorers (radon, c8, gocyclo…) feeding a single CRAP envelope. Stryker config (`stryker.conf.json`) is already in the harness hash-pin list — good. | [Stryker](https://stryker-mutator.io/) |
| **mutmut** | MIT | L3 mutation testing (Python) | Drop-in for Python mutation-kill-rate gate when the harness adds `audit-harness mutation` (future AH-?). Mention as the reference Python implementation. | [github.com/boxed/mutmut](https://github.com/boxed/mutmut) |
| **cargo-mutants** | MIT/Apache-2.0 | L3 mutation testing (Rust) | Reference Rust implementation. Same role as mutmut for the Rust audit-harness binary in `rust/`. | [github.com/sourcefrog/cargo-mutants](https://github.com/sourcefrog/cargo-mutants) |
| **in-toto** | Apache 2.0 (CNCF graduated) | Attestation framework | **Statement format** (`_type` + `subject` + `predicateType` + `predicate`) is the canonical envelope shape. The Evidence Bundle row should BE an in-toto Statement with our own `predicateType`, not a parallel format. **Highest-value borrow on this list.** | [in-toto.io](https://in-toto.io/) · [github.com/in-toto/attestation](https://github.com/in-toto/attestation) |
| **SLSA v1.0** | CC-BY-4.0 (spec) | Build provenance attestation | Direct precedent for what a versioned predicate looks like: `predicateType: https://slsa.dev/provenance/v1` resolves to the latest minor — exact pattern Phase-A envelope design needs for `audit-harness:gate-result/v1`. | [slsa.dev/spec/v1.0/provenance](https://slsa.dev/spec/v1.0/provenance) |
| **Sigstore (Cosign + Fulcio + Rekor)** | Apache 2.0 | Signing + transparency log | keyless OIDC-bound signing of in-toto attestations + Rekor transparency log. **Cosign can sign in-toto attestations directly** via `cosign attest`. Borrow: emit Evidence Bundles as Cosign-attestable artifacts even if v1 doesn't sign them yet. | [Sigstore docs](https://docs.sigstore.dev/) |
| **GUAC** | Apache 2.0 (OpenSSF incubating) | Attestation aggregation graph | Ingests in-toto + SLSA + SBOM + Scorecard into a GraphQL-queryable graph. **If we adopt in-toto envelopes, GUAC ingestion is free.** Architectural argument: don't build a custom aggregator — emit standard envelopes, let GUAC compose. | [github.com/guacsec/guac](https://github.com/guacsec/guac) |
| **SCAI** (Software Supply Chain Attribute Integrity) | Open spec | in-toto predicate type | The closest existing predicate type to what we're emitting. The Evidence Bundle row is *attribute integrity for test artifacts* — same conceptual frame Melara defined for binaries. | [arXiv:2210.05813](https://arxiv.org/abs/2210.05813) |
| **AVID** (AI Vulnerability Database) | Open knowledge base | AI-failure taxonomy | Separation of **what failed (DB)** from **how it's classified (taxonomy)** is the right shape for cataloging escape-scan REFUSE patterns at scale. Borrow the taxonomy-vs-evidence split for the failure-shape catalog the Intentional Mapping work will need. | [avidml.org](https://avidml.org/) |
| **Qodo PR-Agent** (formerly CodiumAI) | AGPL-3.0 | L? AI code review | Open-source AI-reviewer with PR compression strategy. Borrow: the **review/improve/ask** tool decomposition pattern when the harness gets an AI-judge layer. Not core to v1. | [github.com/Qodo-AI/pr-agent](https://github.com/Qodo-AI/pr-agent) |
| **CodeRabbit / Greptile** | Proprietary SaaS | AI code review | Competitive set for *evaluating* AI reviewers, not models to borrow from. Mention only as the SWRBench (paper #4) target population. | [coderabbit.ai](https://coderabbit.ai) · [Greptile](https://greptile.com) |
| **Codacy / CodeClimate** | Proprietary SaaS (free tier) | Multi-layer dashboards | Established quality-dashboard incumbents. Borrow: the **single repo health score** UX pattern. NOT the closed scoring engines. | [Codacy](https://codacy.com) · [codeclimate.com](https://codeclimate.com) |

---

## 5. Primary-source reading list

Categorized URLs. ≥15 unique sources, all directly relevant to upgrade decisions.

### Mutation testing

1. PIT — <https://pitest.org/>
2. Stryker — <https://stryker-mutator.io/>
3. mutmut (Python) — <https://github.com/boxed/mutmut>
4. cargo-mutants (Rust) — <https://github.com/sourcefrog/cargo-mutants>
5. Jia & Harman survey — <https://www.semanticscholar.org/paper/d7c38286734419b52de4262c9802ebdfcf4b9447>
6. Sánchez et al. OSS practitioner survey — <https://www.semanticscholar.org/paper/dd96541648125a3eab01f2bdc5e80d24f10de6ec>

### Attestation, provenance, supply chain

1. in-toto framework — <https://in-toto.io/>
2. in-toto attestation spec — <https://github.com/in-toto/attestation>
3. in-toto Statement v1 spec — <https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md>
4. SLSA v1.0 provenance — <https://slsa.dev/spec/v1.0/provenance>
5. SCAI predicate (Melara, arXiv 2210.05813) — <https://arxiv.org/abs/2210.05813>
6. DSSE (Dead Simple Signing Envelope) — <https://github.com/secure-systems-lab/dsse>

### Transparency log + signing

1. Sigstore docs — <https://docs.sigstore.dev/>
2. Cosign overview — <https://docs.sigstore.dev/cosign/signing/overview/>
3. Rekor transparency log — <https://docs.sigstore.dev/logging/overview/>

### Supply-chain composition

1. GUAC — <https://github.com/guacsec/guac>
2. OpenSSF Scorecard — <https://github.com/ossf/scorecard>
3. Scorecard checks reference — <https://github.com/ossf/scorecard/blob/main/docs/checks.md>

### AI-test review + LLM eval

1. SWRBench (Zeng et al., arXiv 2509.01494) — <https://arxiv.org/abs/2509.01494>
2. CWEval (Peng et al., arXiv 2501.08200) — <https://arxiv.org/abs/2501.08200>
3. AI-code detection (Suh et al., ICSE 2025) — <https://www.semanticscholar.org/paper/e41ceafe77d394b650430ff144cd87811fcc27f4>
4. AVID — <https://avidml.org/>

### Static analysis & quality-gate prior art

1. SonarQube quality gates — <https://www.sonarsource.com/products/sonarqube/>
2. Semgrep — <https://semgrep.dev/>
3. Qodo PR-Agent — <https://github.com/Qodo-AI/pr-agent>

### CRAP metric origin (non-academic, industry-original)

1. Savoia, A. "Will your tests destroy your code?" (Crap4j origin) — <https://www.artima.com/weblogs/viewpost.jsp?thread=210575>

---

## 6. Capability gap matrix — current vs convergence target

The Evidence Bundle is the substrate the three repos share. Each row below asks: *does audit-harness today emit what the Bundle needs, and is the gate it represents implemented?*

| Capability | audit-harness today | Convergence target | Gap |
|---|---|---|---|
| Hash-pinning of engineer-owned artifacts | YES (`harness-hash.sh`) | YES — feeds `policy_hash` field | None |
| AI-diff escape detection | YES (`escape-scan.sh`, REFUSE/CHALLENGE/FLAG) | YES — as one gate among several | None for gate; YES for envelope emission |
| Architecture-rule check | YES (`arch-check.sh`) | YES — emits one row per rule-class | Envelope only |
| Bias-pattern count | YES (`bias-count.sh`) advisory | YES — advisory row in Bundle | Envelope only |
| Gherkin lint | YES (`gherkin-lint.sh`) advisory | YES — advisory row in Bundle | Envelope only |
| CRAP × coverage scoring | YES (`crap-score.py`) — already JSON | YES — direct row emission | Envelope wrap only |
| **Mutation-kill-rate gate** | **NO** — Stryker config is *pinned* but no kill-rate gate runs | YES — Wall 4 needs an actual scorer | **Missing: AH-mutation subcommand** |
| **SAST dispatch** (Semgrep / CodeQL / Bandit) | NO | YES — L2 layer of Bundle | **Missing: AH-sast subcommand** |
| **SBOM / SCA dispatch** | NO | YES — supply-chain row in Bundle | **Missing: AH-sbom subcommand** |
| **Uniform `--json` on all subcommands** | NO — only `crap-score.py` | YES — required for envelope emission | **AH-2** |
| **`emit-evidence` subcommand** | NO | YES — the centerpiece | **AH-3** |
| **in-toto Statement wrapping** | NO | YES — Bundle = in-toto Statement(s) | New capability |
| **DSSE signing** | NO | OPTIONAL v1, REQUIRED v2 | Deferred |
| **Cosign attest integration** | NO | OPTIONAL — pluggable | Deferred |
| **Rekor transparency log** | NO | OPTIONAL — pluggable | Deferred |
| **MCP / agent-conformance gates** | NO | YES — j-rig + intent-eval-lab define these | New, lives mostly in sibling repos but harness must emit slots |
| **Backward-compat regression suite** | Partial (smoke tests) | YES — required for v1.x → v1.y safety | **AH-5** |
| **Multi-language harness packaging** | YES (npm + pip + cargo + curl install.sh) | Unchanged | None |
| **Failure-shape taxonomy / catalog** | NO | YES — AVID-style separation of evidence + taxonomy | Future (Intentional Mapping adjacent) |

---

## 7. Patterns worth borrowing — concrete adoption candidates

Patterns with named source and direct mapping to a convergence bead.

- **in-toto v1 Statement as the Evidence Bundle row shape.** Replace the Phase-A envelope's bespoke top-level with `{_type: "https://in-toto.io/Statement/v1", subject: [...], predicateType: "https://evals.intentsolutions.io/gate-result/v1", predicate: {<current envelope contents>}}`. Cost: ~20 lines of wrapping in `emit-evidence`. Payoff: GUAC ingestion + Cosign signing + SLSA toolchain interoperability **for free**. **Maps to: IEL-CONV-2, AH-4.**

- **Predicate-type URI versioning (SLSA pattern).** `https://evals.intentsolutions.io/gate-result/v1` resolves to latest 1.x; bump to `/v2` on a breaking change. Mirrors the `schema_version` field rather than replacing it — URI is the human-readable contract, `schema_version` is the machine-precise one. **Maps to: AH-4.**

- **Quality-gate-as-named-entity (SonarQube pattern).** `tests/TESTING.md` becomes a named gate bundle ("AH-Default-2026", "AH-Strict-2026") with `policy_hash` baking in the version. Consumers can compare bundles across repos. **Maps to: future audit-harness work (TBD — file as new AH-N when scoped), tests/TESTING.md spec evolution.**

- **Risk-stratified score weighting (Scorecard pattern).** When the Bundle aggregates rows into one health number (Phase B+), use Scorecard's `critical=10, high=7.5, medium=5, low=2.5` rubric. Avoid inventing a new weighting system. **Maps to: j-rig binary-eval scoring.**

- **Incremental / changed-code-only mode (PIT pattern).** When the harness adds a mutation subcommand, default to changed-files-only against `origin/main`. Sánchez et al. is the citation that justifies the choice. **Maps to: future AH-mutation.**

- **Multi-reviewer aggregation (SWRBench pattern, Zeng et al.).** A single row should carry **multiple sub-verdicts** (CRAP gate, mutation gate, escape-scan, AI-judge) — not one row per sub-verdict. The Bundle's `metadata.sub_results[]` array is the right place; the top-level `result` is a roll-up. **Maps to: 001-DR-DESIGN open question #3 (failure annotations).**

- **Taxonomy ÷ evidence split (AVID pattern).** Escape-scan REFUSE patterns are evidence; the "AI-test-gaming failure shapes" catalog is taxonomy. Keep them in separate files so the taxonomy can evolve without invalidating historical evidence. **Maps to: failure-shape catalog (sibling spec work).**

- **DSSE signing primitive (in-toto / Sigstore alignment).** Reserve a `signature` slot in the envelope even when v1 emits unsigned rows. Cosign and standalone `dsse-sign` can populate it later without a schema bump. **Maps to: 001-DR-DESIGN open question #1.**

- **Org-level shared visualization (Stryker org pattern).** When the Bundle ships a renderer, it lives in a *separate* repo from the harness — the same pattern Stryker uses with "Mutation Testing Elements." Harness emits rows; renderer is decoupled. **Maps to: future renderer repo, not Phase B.**

---

## 8. Phase B scope recommendation

Six work items, prioritized for sequential execution. Each is small enough to land as a single beads-tracked PR.

### PB-1. Wrap the gate-result envelope in an in-toto Statement (highest ROI)

- **What:** Modify the Phase-A `001-DR-DESIGN-…` schema to nest the current envelope fields under an in-toto Statement (`_type`, `subject`, `predicateType`, `predicate`).
- **Rationale:** Single biggest payoff in the landscape — opens GUAC, Cosign, SLSA-tool interop for the price of ~20 lines.
- **Effort:** S (schema edit + validator update; no new code).
- **Primary sources:** [§3 paper #5](https://arxiv.org/abs/2210.05813) (SCAI as precedent) · [in-toto Statement spec](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md) · [SLSA v1.0 provenance](https://slsa.dev/spec/v1.0/provenance).
- **Cross-ref:** `AH-4`, `IEL-4`.

### PB-2. Add uniform `--json` to all subcommands (AH-2)

- **What:** Every script in `scripts/` gets a `--json` flag emitting the canonical envelope (post PB-1 = in-toto-wrapped). Text output stays as default for human use.
- **Rationale:** Prerequisite for `emit-evidence`. CRAP already does this; the pattern is proven.
- **Effort:** M (6 scripts × ~30 LOC each, plus a shared JSON-emitter helper).
- **Primary sources:** `scripts/crap-score.py` as the reference implementation.
- **Cross-ref:** `AH-2`.

### PB-3. Implement `emit-evidence` subcommand (AH-3)

- **What:** New `scripts/emit-evidence.{sh,py}`. Reads `tests/TESTING.md` policy + most-recent gate outputs + commit/CI metadata → emits one canonical Statement-shaped row (or N rows if requested).
- **Rationale:** The centerpiece of the convergence. Without this, the other two repos have nothing to consume.
- **Effort:** M.
- **Primary sources:** [in-toto Statement spec](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md) · `001-DR-DESIGN-…` field design.
- **Cross-ref:** `AH-3`.

### PB-4. Backward-compat regression suite (AH-5)

- **What:** Test suite that runs the v0.x CLI surface (verify/init/list/escape-scan/arch/bias/gherkin-lint/crap) against fixture repos and asserts identical exit codes + text output. Runs on every PR.
- **Rationale:** PB-1/PB-2/PB-3 add new shapes — they MUST NOT break adopters pinned to v0.x. Without this gate, the convergence work risks shipping a stealth-breaking minor.
- **Effort:** M.
- **Primary sources:** general SemVer hygiene; no specific borrow.
- **Cross-ref:** `AH-5`.

### PB-5. Mutation-kill-rate dispatcher (new bead)

- **What:** `audit-harness mutation` subcommand that detects language, dispatches to Stryker / PIT / mutmut / cargo-mutants, parses the tool-specific output, and emits a kill-rate row in the canonical envelope. Defaults to changed-code-only against `origin/main`.
- **Rationale:** Closes the biggest capability gap (§6). Wall 4 currently has no scorer behind it — only a config hash-pin. Sánchez et al. is the citation that justifies *incremental-only by default*.
- **Effort:** L (per-language adapter complexity; performance tuning).
- **Primary sources:** [PIT incremental analysis](https://pitest.org/) · [Stryker config reference](https://stryker-mutator.io/) · [Sánchez 2024](https://www.semanticscholar.org/paper/dd96541648125a3eab01f2bdc5e80d24f10de6ec).
- **Cross-ref:** new bead, file at Phase-B kickoff.

### PB-6. Reserve a signature slot in the envelope (no implementation yet)

- **What:** Add an optional `signatures: []` array slot to the schema with a comment "reserved for DSSE signing in v2." No code emits or validates it in v1.
- **Rationale:** Avoids a schema-breaking minor when Cosign integration is added later. Zero-cost insurance.
- **Effort:** XS.
- **Primary sources:** [DSSE spec](https://github.com/secure-systems-lab/dsse) · [Cosign attest workflow](https://docs.sigstore.dev/).
- **Cross-ref:** updates `001-DR-DESIGN-…` open question #1.

---

## 9. What's NOT in scope here

To prevent scope creep:

- **Not implementation guidance.** None of the work items above are PR-ready specs. Each needs a follow-up design pass before code is written.
- **Not a refactor proposal.** The existing six scripts stay where they are. PB-2 / PB-3 add capability; they do not rewrite battle-tested code.
- **Not vendor selection.** This document lists candidates; it does not pick "use Stryker over PIT" or "adopt SonarQube as the dashboard." Those are Phase-B follow-ons per language.
- **Not an Evidence Bundle spec.** The Bundle's canonical schema lives at `intent-eval-lab/specs/evidence-bundle/v0.1.0-draft/` (IEL-4). This document informs that spec; it does not replace it.
- **Not a signing rollout plan.** Cosign / Fulcio / Rekor are correctly recommended for v2. A signing-rollout plan needs its own design doc with key-management and CI-OIDC concerns.
- **Not a marketing piece.** The borrowability matrix is for engineering decisions, not competitive positioning.
- **Not a security review.** Threat modeling against the harness (supply-chain attacks on the harness itself, `harness-hash.sh` race conditions, etc.) is a separate workstream.

---

## 10. Cross-references

- **Companion design (Phase A):** `000-docs/001-DR-DESIGN-evidence-bundle-envelope-design-notes.md`
- **Spec home (canonical Evidence Bundle schema):** `intent-eval-lab/specs/evidence-bundle/v0.1.0-draft/`
- **Master plan:** author's local working source (not part of this repository); public companion synthesis at `intent-eval-lab/000-docs/003-PP-PLAN-phase-b-scope-refinement.md`
- **Taxonomy (7-layer):** ships as part of the `@intentsolutions/audit-harness` documentation; reference summary in `audit-tests` skill installed via the Intent Solutions Testing SOP
- **Beads:** `AH-2`, `AH-3`, `AH-4`, `AH-5`; sibling `IEL-CONV-1`, `IEL-CONV-2`, `IEL-4`
