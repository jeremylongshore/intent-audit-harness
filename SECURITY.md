# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest (v0.1.x) | Yes |
| < latest | Best effort |

## Reporting a Vulnerability

**Please do NOT open public issues for security concerns.**

Email **security@intentsolutions.io** with:

- Type of issue (e.g., escape-scan bypass, manifest forgery, code execution via crafted policy file, dependency vulnerability)
- Full paths of related source files
- Location of the affected code (tag/branch/commit or direct URL)
- Any special configuration required to reproduce
- Step-by-step instructions to reproduce
- Proof-of-concept or exploit code (if possible)
- Impact assessment — particularly important for the supply-chain dimension since `audit-harness` ships in CI gates for downstream repos

### Response Timeline

| Stage | Timeframe |
|-------|-----------|
| Acknowledgment | 24 hours |
| Initial assessment | 48 hours |
| Status update | 5 business days |
| Resolution | Depends on severity |

### Severity Levels

| Severity | CVSS | Examples | Target Resolution |
|----------|------|---------|-------------------|
| Critical | 9.0–10.0 | Remote code execution via manifest, harness bypass that hides AI-tampered thresholds | 24 hours |
| High | 7.0–8.9 | Privilege escalation in install.sh, credential exposure in emitted JSON | 7 days |
| Medium | 4.0–6.9 | Denial of service via crafted policy file, partial hash-pinning bypass | 30 days |
| Low | 0.1–3.9 | Information disclosure in error messages, minor parser issues | 90 days |

## Threat Model

audit-harness sits in CI as a quality gate. Its security posture must consider:

- **Adversary inside the repo** — AI agent or contributor attempting to lower test thresholds, delete tests, or silently weaken the harness. Mitigation: `.harness-hash` manifest pins policy files; `escape-scan` detects common tampering patterns; modifying these requires committer to also re-run `init` and explicitly commit the new manifest.
- **Adversary upstream** — supply-chain attack on the npm/PyPI/crates package. Mitigation: minimal dependencies in the dispatcher; signed releases (planned); cosign keyless OIDC signing on releases (planned).
- **Adversary in consumer repo's CI** — attempt to forge `verify` output to claim manifest passed. Mitigation: the harness emits structured output that downstream collectors can re-verify against the on-disk manifest.

## Disclosure Process

1. **Report** — You email the details to security@intentsolutions.io
2. **Triage** — We assess severity and impact
3. **Fix** — We develop and test a patch
4. **Notify** — We inform affected users (consumer repos via the npm/PyPI/crates advisory feeds + a CHANGELOG entry tagged `SECURITY`)
5. **Release** — We publish the fix
6. **Post-Mortem** — We document lessons learned

## Security Best Practices

When contributing to this project:

- Never hardcode credentials or secrets
- Validate all input at system boundaries (the `init`/`verify` subcommands read files at paths the user supplies — symlink traversal + path-escape are real concerns)
- Keep dependencies up to date (dependabot opens weekly PRs)
- Use HTTPS for all external communication
- Follow the principle of least privilege
- Do not log sensitive information
- Write tests for security-critical paths

## Recognition

We appreciate responsible disclosure. Reporters who follow this policy will receive:

- Credit in security advisories (unless anonymity is preferred)
- Mention in CONTRIBUTORS.md
- Our sincere gratitude

## Contact

- **Security reports**: security@intentsolutions.io
- **General inquiries**: jeremy@intentsolutions.io
- **Response time**: 24 hours for initial acknowledgment
