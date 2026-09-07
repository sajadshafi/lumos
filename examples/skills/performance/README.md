# Performance review skill

This directory is the executable specification for a `performance` skill: a review
stage that inspects a diff for N+1 queries, unbounded loops, missing indexes, and
hot-path allocations, backing each finding with a measurement, then routes to
`fixer`.

The adjacent `SKILL.md` is a runnable, read-only implementation used by the
`full-review` workflow.
