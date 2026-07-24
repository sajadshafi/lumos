# GitHub Copilot driver

Drives the `ai-loom` loop from GitHub Copilot (Chat / agent mode) using the
terminal and the filesystem — no Skill tool required. Copilot reads each skill's
`SKILL.md`, performs the work, and writes a six-section report the engine
validates.

## Install

Copilot reads repository custom instructions from
`.github/copilot-instructions.md`. Install the driver there:

```bash
mkdir -p .github
cp copilot-instructions.md .github/copilot-instructions.md
```

Ensure `loom` is on PATH (`pip install -e .`) and set the project/skills location
once for the session:

```bash
export LOOM_PROJECT_DIR="$PWD"
export LOOM_SKILLS_DIR="$PWD/examples/skills"   # or your own skills dir
```

## Use

In Copilot Chat, ask it to run a work item through a workflow, e.g.:

> Orchestrate TASK-17 through the `default` workflow.

Copilot will `loom start`, then loop `next → (do the skill's work) → write the
report → record` until the run reaches a terminal state, then `loom summary`.

## Notes

- This driver implements [`../DRIVER-SPEC.md`](../DRIVER-SPEC.md). The same loop,
  the same guarantees — a different runtime. Proof that the engine is not tied to
  any one agent.
- Because Copilot has no dedicated "skill" primitive, it treats each skill's
  `SKILL.md` as instructions and does the work directly, then writes the report.
  The engine's contract validation is what keeps that honest.
