# Claude Code driver

Drives the `ai-loom` loop from [Claude Code](https://claude.com/claude-code) using
the Skill tool. The engine handles state and sequencing; this skill supplies the
judgment — reading the task, invoking each skill, and deciding whether output is
genuine.

## Install

Copy the skill into your Claude Code skills directory:

```bash
mkdir -p ~/.claude/skills/orchestrator
cp SKILL.md ~/.claude/skills/orchestrator/SKILL.md
```

(Or into a project's `.claude/skills/orchestrator/` to scope it to one repo.)

Make sure `loom` is on PATH (`pip install -e .` from the repo root) and that your
project has a `workflows/` directory and a skills directory. Point the engine at
them with `LOOM_PROJECT_DIR` / `LOOM_SKILLS_DIR`, or pass `--project-dir` /
`--skills-dir` on each call.

## Use

In Claude Code:

```
/orchestrator TASK-17
/orchestrator TASK-17 --workflow hotfix
/orchestrator status TASK-17
```

## Notes

- This is the reference driver — it follows [`../DRIVER-SPEC.md`](../DRIVER-SPEC.md)
  exactly. Read that to understand the contract it upholds.
- To wire a real issue tracker (Azure DevOps, GitHub), add a `TrackerAdapter`
  under `src/ai_loom/adapters/` and fetch the work item in step 1; pass
  tracker-specific fields with `--metadata key=value`. With the default `local`
  tracker, no external system is touched.
