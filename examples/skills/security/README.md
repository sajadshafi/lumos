# security (placeholder)

This directory is the executable specification for a `security` skill: a review
stage that checks a diff for injection, authz gaps, secret handling, and
data-exposure issues, then routes findings to `fixer`.

It deliberately ships **without a `SKILL.md`**, so it is discovered but not
invokable. That is why `full-review.yaml` fails `loom workflows --validate` — and
it is the proof that turning this into a real stage is a matter of authoring one
`SKILL.md`, with no change to the engine. Copy any skill under
`examples/skills/` as a starting point.
