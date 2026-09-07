# Lumos runtime driver specification

A driver binds the deterministic Lumos CLI to an AI runtime. The engine never
calls a model; the driver invokes the skill or agent named by each directive.

## Required capabilities

1. Run `lumos` and parse JSON stdout.
2. Read an input envelope and write a worker report verbatim.
3. Invoke a skill in the current context.
4. Delegate an agent through the runtime's native agent mechanism, when present.

## Continuous loop

After `lumos start <ticket>`, repeat without returning control to the user:

1. Call `lumos next <run_id>`.
2. For `invoke_skill`, invoke `worker`/`skill_command` with `envelope`.
3. For `invoke_agent`, load `agent_path`, delegate `envelope`, and wait for it.
4. Write the result verbatim to `report_path`.
5. Call `lumos record <run_id> --stage <stage_key> --report <report_path>`.
6. Loop on the returned directive.

Stop only when:

- `complete` or `abort` is returned;
- `await_approval` requires a human decision;
- project configuration explicitly sets `execution.mode: step`.

Commentary/progress messages are not a reason to end the run.

## Directive fields

| Field | Meaning |
|---|---|
| `action` | `invoke_skill`, `invoke_agent`, `await_approval`, `complete`, or `abort` |
| `worker_type` | `skill` or `agent` |
| `worker` | Runtime-facing worker name |
| `skill_command` | Slash command for skills; null for agents |
| `agent_path` | Agent instruction file for agent directives; null for skills |
| `stage_key` | Stable workflow stage identity |
| `envelope` | Full four-block worker input |
| `report_path` | Required destination for the verbatim report |

Legacy `skill` remains populated for compatibility with 0.1 drivers.

## Invariants

- Follow the workflow's worker and order; `Next Skill` in a report is advisory.
- Never fabricate, summarize, or repair a worker report.
- Record an invocation failure with `--failed --error <reason>`.
- Never decide retries or remediation loops; follow the next directive.
- Never approve a human gate on the user's behalf.
- Preserve all host authorization and repository instruction boundaries.

These invariants make runs resumable and auditable across runtimes.
