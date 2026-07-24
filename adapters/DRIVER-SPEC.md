# Driver specification

A **driver** binds `ai-loom`'s loop to a specific agent runtime. The engine never
calls a model; a driver is whatever *does* — a Claude Code skill, a Copilot
instructions file, a shell script, or a human at a terminal. This document is the
whole contract. Implement it and your runtime can drive any workflow.

The engine speaks a neutral CLI: **markdown envelope in, six-section report out,
JSON directives over stdout.** A driver needs exactly three capabilities:

1. run a command-line program and read its stdout,
2. read and write a text file,
3. invoke a skill (a prompt) and capture its output.

That is the entire coupling surface. Anything with those three can be a driver.

---

## The commands

Machine commands emit **JSON on stdout**. Exit codes: `0` success, `1` usage/config
error, `2` the run reached a terminal non-success state.

| Command | Purpose |
|---|---|
| `loom start <id> --workflow <name> [--title … --type … --branch … --metadata k=v]` | Create (or resume) a run |
| `loom next <run>` | Get the next directive **and** the built input envelope |
| `loom record <run> --stage <key> --report <path>` | Validate a report, advance the run |
| `loom record <run> --stage <key> --failed --error "…"` | Record an invocation that produced no report |
| `loom status <run>` · `loom summary <run>` | Progress board · final markdown summary |
| `loom approve <run> --stage <key>` | Clear a manual approval gate |
| `loom cancel <run> --reason "…"` | Terminate a run |

Add `--project-dir <dir>` (and, if your skills live elsewhere, `--skills-dir
<dir>`) to every call, or set `LOOM_PROJECT_DIR` / `LOOM_SKILLS_DIR`.

---

## The loop a driver must run

```
start
  │
  ▼
next ─────────────────────────────► read directive JSON
  ▲                                    │
  │                                    ├─ action == "invoke_skill":
  │                                    │     read `envelope` (or `envelope_path`)
  │                                    │     invoke `skill` with the envelope as input
  │                                    │     write the skill's report VERBATIM to `report_path`
  │                                    │     record ──► loop
  │                                    │
  │                                    ├─ action == "await_approval":
  │                                    │     stop; tell the human the `approve` command
  │                                    │
  │                                    └─ action in ("complete", "abort"):
  │                                          run `summary`; stop
  └────────────────────────────────────────┘
```

The `next` response contains: `action`, `skill`, `stage_key`, `attempt`,
`envelope_path`, `report_path`, and `envelope` (the full four-block input text,
already assembled from the work unit and every upstream report).

`record` returns the verdict and the next directive. If the skill could not run at
all, use `--failed --error "<what happened>"` instead of `--report`.

---

## The five rules a driver must not break

These are what make the engine's determinism real. A driver that breaks them
silently defeats the point.

1. **Invoke the skill the directive names** — not the one you would have picked,
   and not the one the last report recommended. The workflow dispatches; `Next
   Skill` only advises.
2. **Write the report verbatim.** Do not summarise, reformat, or "improve" it. The
   next stage consumes the full text; a paraphrase makes it re-derive the
   repository from scratch.
3. **Never fabricate a report.** If a skill fails to produce one, `record
   --failed`. A synthesised report corrupts every downstream stage.
4. **Never count attempts or decide retries yourself.** If a report is malformed,
   the engine re-queues the same stage with the violation quoted into the
   envelope — you just invoke it again. Loop ceilings are the engine's.
5. **Never approve a gate on the human's behalf.** `await_approval` means stop and
   ask.

`blocked`, `escalated`, and `failed` are legitimate terminal outcomes. Report them
honestly; do not restart a run to force a greener result unless the human asks.

---

## Minimal reference driver (shell)

A complete, runtime-free driver is about 30 lines. This is enough to drive a run
end to end where a human (or a piped agent) fills in each report:

```bash
run=$1; proj=${2:-.}
while :; do
  d=$(loom --project-dir "$proj" next "$run")
  action=$(printf '%s' "$d" | python3 -c 'import sys,json;print(json.load(sys.stdin)["action"])')
  case "$action" in
    invoke_skill)
      skill=$(printf '%s'  "$d" | python3 -c 'import sys,json;print(json.load(sys.stdin)["skill"])')
      stage=$(printf '%s'  "$d" | python3 -c 'import sys,json;print(json.load(sys.stdin)["stage_key"])')
      report=$(printf '%s' "$d" | python3 -c 'import sys,json;print(json.load(sys.stdin)["report_path"])')
      env=$(printf '%s'    "$d" | python3 -c 'import sys,json;print(json.load(sys.stdin)["envelope_path"])')
      # >>> invoke `$skill` with the contents of `$env`, write its report to `$report` <<<
      loom --project-dir "$proj" record "$run" --stage "$stage" --report "$report" ;;
    await_approval) echo "Approval needed. Run: loom approve $run --stage <key>"; break ;;
    complete|abort) loom --project-dir "$proj" summary "$run"; break ;;
  esac
done
```

The two shipped drivers ([`claude-code/`](claude-code/), [`copilot/`](copilot/))
are this same loop expressed in each runtime's idiom.
