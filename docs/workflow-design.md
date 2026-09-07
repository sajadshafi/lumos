# Workflow design

A workflow is an ordered YAML pipeline. It decides which worker runs; the Python
engine does not hardcode planning, coding, or review stages.

```yaml
version: 1
name: delivery
description: Plan, implement, review, and ship a ticket.
max_total_stages: 30
stages:
  - agent: planner
    retry:
      max_attempts: 2
  - skill: coding
    retry:
      max_attempts: 3
  - agent: reviewer
    remediation:
      skill: fixer
      max_cycles: 2
  - skill: post-feature-implementation
    requires_approval: true
```

## Stage fields

| Field | Meaning |
|---|---|
| `skill` | Invoke a reusable skill in the current runtime context |
| `agent` | Delegate to the named agent definition |
| `worker` + `type` | Neutral alternative, e.g. `worker: planner`, `type: agent` |
| `id` | Optional unique stage key, needed when reusing one worker |
| `description` | Reason included in the directive |
| `retry.max_attempts` | Maximum invocation attempts |
| `optional` | Continue when retries are exhausted |
| `requires_approval` | Pause before invocation until a human approves |
| `remediation` | Worker to run when this stage requests changes |

Each stage must specify exactly one of `skill`, `agent`, or `worker`. The string
shorthand (`- coding`) remains equivalent to `- skill: coding`.

## Remediation

Remediation accepts the same worker syntax:

```yaml
- skill: reviewer
  remediation:
    agent: fixer
    max_cycles: 3
```

If `reviewer` requests `fixer`, Lumos queues `fixer`, then queues `reviewer`
again so the worker that raised the objection verifies the result. The cycle and
global stage ceilings prevent runaway token use.

## Reusing a worker

Stage ids are normally the worker name. Give repeated uses explicit ids:

```yaml
- id: architecture-review
  agent: reviewer
- id: final-review
  agent: reviewer
```

## Validation

`lumos validate <name>` checks the schema and every referenced skill, agent, and
remediation target. `lumos workflows --validate` checks all workflow files.
