# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-07-24

First open-source release. Extracted from a private, working internal tool and
made runtime- and tracker-neutral.

### Added

- Deterministic workflow engine: state persistence, attempt counting, retry
  budgets, remediation loops with a cycle ceiling, and runaway protection
  (`max_total_stages`).
- Six-section report contract (`Summary`, `Findings`, `Decisions`,
  `Deliverables`, `Risks`, `Next Skill`) with strict validation and verdict
  derivation.
- Four-block input envelope (`Objective`, `Context`, `Constraints`, `Previous
  Outputs`), assembled automatically from the work unit and every upstream report.
- Workflow model as data (YAML): linear pipelines, remediation loops, manual
  approval gates, optional stages, per-stage retry budgets.
- `TrackerAdapter` seam with a dependency-free `local` default and a documented
  `azure-devops` stub; a small adapter registry.
- Runtime drivers: a neutral `DRIVER-SPEC.md`, a Claude Code skill, and a GitHub
  Copilot instructions file.
- `pip`-installable package (`pyproject.toml`) exposing the `loom` command; runs
  on the standard library alone, with optional PyYAML.
- A full worked skill set, the contract docs, and a runnable `hello-world` chain
  under `examples/`.
- 129 tests (stdlib `unittest`) and a GitHub Actions CI matrix.

### Changed

- Flattened to a standalone repository (`src/` layout) with a flat project
  directory (`workflows/`, `skills/`, `state/`, `logs/`, `runs/`) instead of the
  previous `.claude/orchestrator/` nesting.
- Generalized run-id normalization: no synthetic tracker prefix is imposed.
- Renamed `WorkItem` to the tracker-neutral `WorkUnit` (with a compatibility
  alias) and moved tracker-specific fields into a free-form `metadata` map.
- Moved the project-specific default constraints out of the engine and into an
  editable `constraints/default.md`.

[Unreleased]: https://github.com/your-org/ai-loom/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/your-org/ai-loom/releases/tag/v0.1.0
