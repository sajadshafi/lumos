---
name: Bug report
about: Something in the engine, CLI, or an adapter behaves incorrectly
title: "[bug] "
labels: bug
---

## What happened

A clear description of the incorrect behaviour.

## Expected

What you expected instead.

## Reproduction

Steps and the exact commands. Include the workflow YAML and, if relevant, the run
directory contents.

```bash
loom --project-dir ... start ...
```

## Environment

- ai-loom version (`loom --version`):
- Python version:
- OS:
- Driver / runtime (Claude Code, Copilot, manual, …):
- PyYAML installed? (yes/no)

## Logs

Relevant lines from `logs/<run-id>.jsonl` or the failing command's output.
