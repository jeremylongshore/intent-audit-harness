---
name: Feature request
about: Propose a new subcommand, flag, or behavior for @intentsolutions/audit-harness
title: "[feature] "
labels: enhancement
assignees: ''
---

## Summary

<!-- One-sentence description of the proposed feature. -->

## Motivation

<!-- What problem does this solve? Cite a concrete situation where the current CLI surface is insufficient — a repo that needs the missing capability, a hook that can't be wired without it, an enforcement gate that's currently impossible. -->

## Proposed CLI surface

```text
audit-harness <new-subcommand-or-flag> [args...]
```

**Output shape:**

<!-- Plain text, JSON (`--json`), or both? If JSON, sketch the schema. -->

**Exit code semantics:**

<!-- 0 = pass, 1 = fail, 2 = REFUSE? Match existing subcommand conventions. -->

## Backward compatibility

<!-- Does this break any existing CLI surface? Per CLAUDE.md rule 3 ("Backward compatibility on CLI surface"), once shipped commands don't get renamed or repurposed. New subcommands and additive flags are fine. -->

## Alternatives considered

<!-- What other approaches did you consider? Why is this the right shape? -->

## Cross-references

<!-- Link to upstream Anthropic docs, audit-tests / implement-tests skill SKILL.md sections, or downstream repo issues that depend on this feature. -->
