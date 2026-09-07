# Configuration

Lumos reads `lumos.yaml` from the project root:

```yaml
version: 1
default_workflow: default
ticket:
  prefix: TC
execution:
  mode: continuous
```

## Ticket references

`ticket.prefix` defaults to `TC`; `C3` and `C3#` are equivalent. It is applied when a
user supplies a number (`123`) or hash-number (`#123`). Explicit values such as
`C3#123`, `AB#44`, and legacy tracker identifiers are preserved.

## Execution mode

- `continuous` tells the runtime driver to execute the complete pipeline in the
  current turn. It stops for a terminal state or `requires_approval` gate.
- `step` executes one worker and returns control. It is useful for debugging or
  runtimes with a strict one-invocation limit.

The engine returns one deterministic directive at a time. The installed runtime
skill owns the continuous loop, keeping the core portable between AI tools.

## Locations

| Resource | CLI | Environment |
|---|---|---|
| Project | `--project-dir` | `LUMOS_PROJECT_DIR` |
| Skills | `--skills-dir` | `LUMOS_SKILLS_DIR` |
| Agents | `--agents-dir` | `LUMOS_AGENTS_DIR` |

Legacy `LUMOS_PROJECT_DIR` and `LUMOS_SKILLS_DIR` remain supported.
