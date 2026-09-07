# Authoring skills and agents

Lumos calls both resource types **workers** because they share an input and
output contract. Their runtime behavior differs:

| Type | Location | Invocation |
|---|---|---|
| Skill | `skills/<name>/SKILL.md` | Loaded in the current AI context |
| Agent | `agents/<name>/AGENT.md` or `agents/<name>.md` | Delegated through the host's native agent mechanism |

Start with [`templates/skill/SKILL.md`](../templates/skill/SKILL.md) or
[`templates/agent/AGENT.md`](../templates/agent/AGENT.md).

## Shared input

Every worker receives a markdown envelope with `Objective`, `Context`,
`Constraints`, and all `Previous Outputs`. A worker must not infer missing
requirements that materially affect the result; return a blocker instead.

## Shared report

Every worker returns these exact top-level headings in order:

```markdown
# Summary
# Findings
# Decisions
# Deliverables
# Risks
# Next Skill
```

Keep findings evidence-backed and state the write boundary in the worker file.
`Next Skill` is advisory; the workflow remains authoritative. Use
`None — complete`, `None — blocked: ...`, or `None — escalate: ...` for terminal
recommendations.

Validate with `lumos workers` and `lumos validate <workflow>`. Validation checks
skills, agents, and remediation targets before a run begins.

