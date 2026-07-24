# Output Format

The document contract. Every skill emits exactly these six sections, in this
order, with these headings verbatim. Downstream skills parse this; humans skim
it. Both break when the shape drifts.

**Format version:** 1.0.0

---

## Skeleton

```markdown
# Summary

<3–6 sentences. Standalone.>

# Findings

<Evidence-bearing observations. Sourced.>

# Decisions

<Choices made, alternatives rejected, reasons.>

# Deliverables

<Concrete artefacts produced.>

# Risks

<What could go wrong, with mitigation.>

# Next Skill

<Recommended successor + reason, or None + reason.>
```

Sections are never omitted. A section with nothing to report says so explicitly:

```markdown
# Risks

None identified. The change is additive, touches one module, and has no data-model impact.
```

Silence is ambiguous — it reads as "not considered" rather than "considered,
nothing found".

---

## `# Summary`

Three to six sentences of prose. No bullets, no headings.

Must answer: what was this run asked to do, what did it do, what is the single
most important thing the reader needs to know, and is the result usable as-is?

Written for someone who will read nothing else.

> **Good:** "Planned pagination for the `GET /notes` endpoint. The work adds one
> query parameter pair (`limit`, `cursor`), a reusable `paginate()` helper under
> `lib/pagination`, and touches three handlers; it reuses the existing cursor
> encoder, so no shared infrastructure changes. The one material unknown is
> whether existing clients tolerate an envelope response — raised in Open
> Questions. Estimated at 1–2 days including tests."

> **Bad:** "I analyzed the codebase and created a comprehensive plan for the
> pagination feature, covering all the necessary changes." — no facts, no
> numbers, no unknowns, no decision support.

---

## `# Findings`

What is true about the system, with evidence. Observations only — no
recommendations, no plans. Those live in `Decisions` and `Deliverables`.

Every claim carries a source: a repo-relative path (`src/routes/notes.js:34`), a
symbol name, a command and its output, or a citation of an upstream report
section.

Group under `##` subheadings when there are more than about six findings. Order
by decision-relevance, not by discovery order.

```markdown
## Existing list surface

- `GET /notes` (`src/routes/notes.js:18`) returns the full table as a bare JSON
  array, with no limit.
- A cursor encoder already exists (`src/lib/cursor.js`) but is only used by the
  activity feed.
- No pagination tests exist under `tests/`.
```

Unverified claims do not belong here. If it was not checked, it is an assumption —
put it in `Risks` or `Open Questions`, labelled.

---

## `# Decisions`

Choices this run made that constrain what comes next. One entry per decision:

```markdown
- **<Decision>** — chosen over <alternative>. <Reason, tied to a principle,
  constraint, or finding.>
```

Include rejected alternatives. The rejection is the valuable part: it stops the
next skill from re-opening a settled question.

```markdown
- **Cursor pagination rather than offset** — chosen over `?page=` offsets because
  the table is append-heavy and offsets drift under concurrent inserts. Reuses
  the existing `src/lib/cursor.js` encoder.
- **No new dependency** — the standard library covers base64 cursor encoding.
```

Purely mechanical choices ("named the helper `paginate`") are not decisions. If
convention dictated it, it is not a decision.

---

## `# Deliverables`

What now exists that did not before. Each item names the artefact, its location,
and its state.

For document-producing skills, the document is nested here under `##`/`###`
subheadings — the report contains the deliverable rather than pointing at it.

For code-producing skills, list files with their change type:

```markdown
| File | Change | Notes |
|---|---|---|
| `src/lib/pagination.js` | new | 34 lines; wraps the cursor encoder |
| `src/routes/notes.js` | modified | reads `limit`/`cursor`, returns an envelope |
| `tests/pagination.test.js` | new | 6 cases incl. empty + last page |
```

State verification status plainly. "Tests written and passing (`npm test`, 41
passed)" and "tests written, not yet run" are different deliverables, and the
difference matters. Never describe unrun work as complete.

---

## `# Risks`

What could go wrong, and what to do about it. Each risk:

```markdown
- **<Risk>** — Likelihood: <low|medium|high>. Impact: <low|medium|high>.
  Mitigation: <specific action, owned by someone or some skill>.
```

Rules:

- Real risks only. Padding with "the code may contain bugs" trains readers to
  skip the section.
- Mitigations are actionable, not aspirational. "Be careful during review" is not
  a mitigation; "the reviewer must confirm the envelope change is behind a
  version flag" is.
- Include risks introduced by this run's own decisions, not just inherited ones.

```markdown
- **Existing clients may break on the new envelope shape** — Likelihood: medium.
  Impact: high. Mitigation: gate the envelope behind an `Accept-Version` header;
  reviewer must confirm the default path is unchanged.
```

---

## `# Next Skill`

Exactly one recommendation, with reasoning and any conditions.

```markdown
**`coding`** — the plan is complete and no open question blocks the first steps.
Start with the `paginate()` helper, then wire the route; do not change the
response envelope until Open Question #1 (client compatibility) is resolved.
```

Termination is a valid outcome and is stated the same way:

```markdown
**None — blocked.** Open Question #1 determines the response shape, and every
downstream step depends on it. Needs a product decision before any code is written.
```

```markdown
**None — complete.** PR #482 opened and linked to TASK-17. No further skill applies.
```

Never list two candidates without choosing.

---

## Formatting rules

- GitHub-flavoured Markdown.
- `#` for the six sections only. `##`/`###` for structure within them.
- File paths in backticks, always repo-relative. Line numbers as `path.js:42`.
- Tables for uniform enumerations (files, test cases, endpoints). Bullets
  otherwise.
- Fenced code blocks are tagged with a language.
- No emoji. No decorative separators between sections.
- No hedging. If genuinely uncertain, say what would resolve the uncertainty.
- Absolute dates (`2026-07-20`), never relative ones (`last week`).
- Second person for instructions to the next skill; third person for observations.
