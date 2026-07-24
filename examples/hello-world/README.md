# Hello, world — a two-step chain

The smallest run that still shows the whole loop: one skill drafts, one reviews.
No external tracker, no real codebase — just enough to watch the engine advance
through two stages and produce two reports.

This directory is a self-contained mini-project. Point `loom` at it with
`--project-dir`.

## Run it

From the repository root, with `loom` installed (`pip install -e .`):

```bash
HELLO=examples/hello-world

# 1. Start a run of the `hello` workflow
loom --project-dir $HELLO start GREETING-1 --workflow hello \
     --title "Say hello to a new contributor"

# 2. Ask what's next — you get a directive and a fully built input envelope
loom --project-dir $HELLO next GREETING-1
```

`next` prints JSON including `skill`, `envelope_path`, and `report_path`. Read the
envelope, act as the named skill, and write a six-section report to `report_path`.
For a dry run you can copy the drafted report straight from the envelope's
Objective — the point is to see the mechanics.

```bash
# 3. Record the report; the engine validates it and advances the run
loom --project-dir $HELLO record GREETING-1 --stage draft --report <report_path>

# 4. Repeat next/record for the `review` stage, then:
loom --project-dir $HELLO summary GREETING-1
```

## What to notice

- You never told the engine what came after `draft`. `workflows/hello.yaml` did.
- The report you wrote is validated against the six-section contract before the
  run advances — a malformed report re-queues the same stage instead of
  corrupting the next one.
- `state/`, `logs/`, and `runs/` appear under this directory as the run proceeds.
  They are the durable record; delete them to start clean.

When you are ready for the real thing, the top-level `default` workflow chains
`feature-planner → coding → testing → reviewer → post-feature-implementation` over
the skills in `examples/skills/`.
