# Summary

Planned cursor-based pagination for the notes list. The work adds one reusable
`paginate()` helper under `src/lib/`, wires it into the `GET /notes` route behind
an opt-in query parameter, and reuses the existing cursor encoder — so there is no
shared-infrastructure change. The one material unknown is whether the response
should stay a bare array (with pagination via headers) or move to an envelope;
this is raised in Open Questions and does not block the first steps. Estimated at
1–2 days including tests.

# Findings

## Existing list surface

- `GET /notes` (`src/routes/notes.js:18`) returns the full table as a bare JSON
  array, with no limit or ordering guarantee.
- A cursor encoder already exists (`src/lib/cursor.js:4`, `encode`/`decode`) and
  is used only by the activity feed (`src/routes/activity.js:22`).
- No pagination tests exist under `tests/`.

## Conventions that constrain the design

- Routes read query params via `req.query` and validate with the `zod` schemas in
  `src/schemas/` — see `src/schemas/activity.js` for the pagination precedent.
- `npm test` currently passes: 41 tests, 0 failures (run 2026-07-24).

# Decisions

- **Cursor pagination rather than offset** — chosen over `?page=` offsets because
  the notes table is append-heavy and offsets drift under concurrent inserts. The
  cursor encoder already exists, so this reuses rather than adds. (DRY.)
- **Opt-in via `?limit=`** — chosen over changing the default response, to honour
  the "no breaking change for existing clients" constraint.

# Deliverables

## Implementation plan

1. Add `src/lib/pagination.js` exposing `paginate(query, { defaultLimit: 20 })`,
   wrapping `src/lib/cursor.js`. (new)
2. Add a `notesQuery` schema in `src/schemas/notes.js` validating `limit` (1–100)
   and optional `cursor`. (new)
3. Update `src/routes/notes.js:18` to call `paginate()` when `limit` is present,
   returning `{ items, nextCursor }`; unchanged behaviour otherwise. (modified)
4. Add `tests/pagination.test.js`: first page, middle page, last page (null
   cursor), empty table, and invalid `limit`. (new)

Do steps 1–2 first (pure, independently testable), then 3, then 4.

# Risks

- **Bare-array vs envelope response is unresolved** — Likelihood: medium. Impact:
  medium. Mitigation: keep the opt-in envelope only on the `?limit=` path; the
  reviewer must confirm the default array path is byte-identical. Tracked as Open
  Question #1.

## Open Questions

1. Should paginated responses use an envelope (`{ items, nextCursor }`) or return
   an array with `Link` headers? Needs a product/API decision. Does **not** block
   steps 1–2.

# Next Skill

**`coding`** — the plan is complete and no open question blocks the first two
steps. Start with `src/lib/pagination.js` and the schema; do not finalise the
response shape in step 3 until Open Question #1 is resolved.
