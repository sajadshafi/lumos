# Example skills

A full, worked skill set for the shipped workflows. Copy any of these as the
starting point for your own — they are the reference implementation of the
[skill contract](../shared/workflow-contract.md).

| Skill | Role | Writes source? |
|---|---|---|
| [`feature-planner`](feature-planner/) | Turn a requirement into a file-level plan | no |
| [`coding`](coding/) | Execute the plan; write code and tests | **yes** |
| [`testing`](testing/) | Close coverage gaps, especially failure modes | tests only |
| [`reviewer`](reviewer/) | Verify the change; route defects to `fixer` | no |
| [`fixer`](fixer/) | Apply targeted remediation for review findings | **yes** |
| [`post-feature-implementation`](post-feature-implementation/) | Update docs, compose the PR | no |
| [`security`](security/), [`performance`](performance/) | Placeholders — a README, no `SKILL.md` | — |

## Conventions

- A skill is a directory whose name is kebab-case (`[a-z][a-z0-9-]*`) and matches
  the `name` in its `SKILL.md` frontmatter.
- A directory **with** a `SKILL.md` is invokable; **without** one it is inert
  (discovered and reported, so a workflow that names it fails with an
  explanation). `security/` and `performance/` are deliberately inert.
- `shared/` (one level up) holds the contract docs, not a skill, and is excluded
  from discovery.
- Each real skill should ship an `examples/input.md` + `examples/output.md` pair;
  `feature-planner/` has the reference pair.

See [skill authoring](../../docs/skill-authoring.md) for the full guide.
