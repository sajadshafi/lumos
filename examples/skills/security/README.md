# Security review skill

This directory is the executable specification for a `security` skill: a review
stage that checks a diff for injection, authz gaps, secret handling, and
data-exposure issues, then routes findings to `fixer`.

The adjacent `SKILL.md` is a runnable, read-only implementation used by the
`full-review` workflow.
