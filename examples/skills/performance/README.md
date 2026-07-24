# performance (placeholder)

This directory is the executable specification for a `performance` skill: a review
stage that inspects a diff for N+1 queries, unbounded loops, missing indexes, and
hot-path allocations, backing each finding with a measurement, then routes to
`fixer`.

Like `security/`, it ships **without a `SKILL.md`** on purpose. It is discovered
but not invokable, which is what makes `full-review.yaml` fail validation until
someone authors the skill. No engine change is required to make it real.
