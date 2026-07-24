# Skill authoring

A skill is a directory with a `SKILL.md`. It does one job in the pipeline. This
guide is how to write one the engine will accept and other skills can chain with.
The worked set under [`examples/skills/`](../examples/skills/) is the reference —
copy the nearest one and adapt.

## Anatomy

```
skills/
└── my-skill/
    ├── SKILL.md              # required: frontmatter + instructions
    └── examples/
        ├── input.md          # a sample four-block envelope
        └── output.md         # the conformant six-section report it produces
```

The engine discovers any directory under your skills dir. A directory **with** a
`SKILL.md` is invokable; one **without** is reported as inert (so a workflow that
names it fails with an explanation, not a crash).

## The frontmatter

```markdown
---
name: my-skill
description: "One or two sentences: what it does and when to use it. This is what an agent reads to decide whether to invoke it."
---
```

`name` must be kebab-case (`[a-z][a-z0-9-]*`) and match the directory. Frontmatter
is read with a simple line scan — keep it a flat key/value map.

## The two halves of the contract

Every skill sits between the same two shapes (full spec:
[`examples/shared/workflow-contract.md`](../examples/shared/workflow-contract.md)).

**It receives** the four-block input envelope — `Objective`, `Context`,
`Constraints`, `Previous Outputs`. The engine builds this for you from the work
unit and every upstream report; your `SKILL.md` just says which blocks the skill
requires and what to do if one is missing.

**It emits** the six-section report — `# Summary`, `# Findings`, `# Decisions`,
`# Deliverables`, `# Risks`, `# Next Skill`, in that order, with those exact
headings. See [`examples/shared/output-format.md`](../examples/shared/output-format.md)
for what belongs in each. The engine validates this shape before advancing; get
it wrong and the same stage re-queues with the violation quoted back.

## What a good SKILL.md says

Keep it short and imperative. Cover:

1. **Role** — the one job, in a sentence.
2. **Input** — which envelope blocks it needs; what to do if they're absent
   (block, don't guess).
3. **Procedure** — the steps to perform.
4. **Write boundary** — state it explicitly. Only `coding` and `fixer` write
   source; everything else treats the tree as read-only, *including* obvious fixes
   noticed in passing. This is the rule that keeps the audit trail honest.
5. **Output** — where skill-specific detail nests (e.g. a planner nests its plan
   under `# Deliverables`) and what to recommend in `# Next Skill`.

## Conformance checklist

A skill is conformant when it:

- [ ] names any input block it requires, rather than inventing missing content;
- [ ] emits all six sections, in order, with the exact headings;
- [ ] keeps every factual claim in `# Findings` sourced (path, symbol, command,
      or upstream report section);
- [ ] respects its declared write boundary without exception;
- [ ] terminates with an explicit `# Next Skill`, including the `None` cases
      (`None — complete` / `None — blocked` / `None — escalate`);
- [ ] ships an `examples/input.md` + `examples/output.md` pair demonstrating all
      of the above.

## Try it

```bash
loom --skills-dir ./skills skills            # confirm it's discovered + invokable
loom --skills-dir ./skills validate default  # confirm a workflow can use it
```

Non-conformant output is a defect in the skill, not the run. Fix the `SKILL.md`
and re-run — never hand-patch a report.
