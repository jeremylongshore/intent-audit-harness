# AISlop — Vale rules that catch AI-generated prose patterns

Detects the AI-slop patterns catalogued by [petergyang/no-ai-slop](https://github.com/petergyang/no-ai-slop),
expressed as Vale rules so they run in CI and locally instead of only inside an editing skill.

| Rule | Catches | Level |
|---|---|---|
| `AISlop.BinaryContrast` | "It's not X. It's Y." / "isn't X, it's Y" | warning |
| `AISlop.NegativeListing` | "Not a X. Not a Y." triads | warning |
| `AISlop.DramaticFragment` | "That's it. That's the whole thing." / "Full stop." | warning |
| `AISlop.Phrases` | throat-clearing, faux-insight, puffery, weasel attribution, hub-speak | warning |
| `AISlop.Words` | delve, tapestry, testament, utilize, myriad, boasts, firstly, moreover, ... | warning |
| `AISlop.Dashes` | em / en dash (the #1 AI tell; beyond no-ai-slop's explicit list, matches house style) | warning |

**Tuning:** every rule is `warning`. Promote a rule to `error` (or demote to `suggestion`)
by editing its `level:`. The Vale job in `doc-quality.yml` is advisory (`fail_on_error: false`,
reviewdog `github-pr-check`), so findings annotate changed lines and never block the build.

**Note on `AISlop.Dashes`:** em-dash is not in no-ai-slop's explicit pattern list, but it is the
most common giveaway of AI-drafted text and is banned by the Intent Solutions house style, so it
is included here. Remove `Dashes.yml` if you want strict no-ai-slop parity only.
