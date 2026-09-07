# GitHub Copilot driver

Drives the `Lumos` loop from GitHub Copilot (Chat / agent mode) using the
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

Ensure `lumos` is on PATH (`pip install -e .`) and set the project/worker locations
once for the session:

```bash
export LUMOS_PROJECT_DIR="$PWD"
export LUMOS_SKILLS_DIR="$PWD/examples/skills"   # or your own skills dir
export LUMOS_AGENTS_DIR="$PWD/examples/agents"   # or your own agents dir
```

## Use

In Copilot Chat, ask it to run a work item through a workflow, e.g.:

> Orchestrate TASK-17 through the `default` workflow.

Copilot will `lumos start`, then loop `next → invoke the worker → write the
report → record` until the run reaches a terminal state, then `lumos summary`.

## Notes

- This driver implements [`../DRIVER-SPEC.md`](../DRIVER-SPEC.md). The same loop,
  the same guarantees — a different runtime. Proof that the engine is not tied to
  any one agent.
- Copilot may load a skill in the current context or delegate an agent through
  its available agent mechanism. Both return the same validated report contract.
