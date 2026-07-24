# State Model

The complete, durable record of one workflow run. If the process dies, this file
is sufficient to resume — nothing that matters lives only in the agent's context.

---

## 1. Storage

| | |
| --- | --- |
| Location | `state/<run-id>.state.json` |
| Format | JSON (durable), rendered as YAML by `loom state <run>` |
| Written by | `StateManager` only |
| Write mode | Atomic — temp file, `fsync`, `os.replace` |
| Schema version | `1` |

**Why JSON and not YAML.** The design sketch specifies a YAML state model, and
the `state` command renders exactly that shape. But the durable record is JSON:
it round-trips exactly through the standard library, requires no dependency, and
cannot be corrupted by the limits of the fallback YAML parser. Human readability
is a presentation concern and is served by a renderer, not by the storage format.

**Why atomic writes.** A run is interrupted by Ctrl-C, a closed terminal, or a
crashed session more often than by anything else. An in-place write risks a
truncated file, which loses the entire run. Write-temp-then-rename is atomic on
POSIX: the file on disk is always either the previous state or the next one.

---

## 2. Run identity

A run is keyed by a normalised work item reference, so resuming never depends on
retyping the reference identically:

```
TASK-17       →  TASK-17
task-17       →  TASK-17   (case-insensitive)
task#17       →  TASK-17
feature/login →  FEATURE-LOGIN
```

No synthetic tracker prefix is imposed — a bare id is preserved. Non-alphanumeric
characters collapse to hyphens, which also means a reference can never escape the
state directory (`TASK-17/../etc` → `TASK-17----ETC`). A tracker that needs its own
scheme normalises the reference in its adapter (see `normalise_id` in
`src/ai_loom/adapters/base.py`).

---

## 3. The YAML projection

`loom state TASK-17` renders the model in the shape the design specifies:

```yaml
feature:
  id: TASK-17
  title: Paginate the notes list
  type: Feature
  branch: feat/task-17-paginate-notes
workflow: default
status:
  feature-planner: completed
  coding: completed
  testing: completed
  reviewer: running
  fixer@reviewer: completed
  post-feature-implementation: pending
current_step: reviewer
next_step: reviewer
attempts:
  feature-planner: 1
  coding: 2
  testing: 1
  reviewer: 2
  fixer@reviewer: 1
summary:
  feature-planner: "Plan covers 4 files; reuses the existing cursor encoder…"
  coding: "Added paginate() helper, wired the notes route, 6 tests…"
artifacts:
  feature-planner:
    - implementation plan (4 files)
  coding:
    - src/lib/pagination.js
errors:
  - stage: coding
    message: "report does not conform to the output contract: missing # Risks"
    recoverable: true
workflow_status: running
```

---

## 4. Field reference

### Run level

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Refused if greater than the orchestrator supports |
| `contract_version` | str | Skill report contract in force (`1.0.0`) |
| `run_id` | str | Normalised identity, e.g. `TASK-17` |
| `workflow_name` | str | Which definition governs this run |
| `status` | enum | See §5 |
| `branch`, `repository` | str | Repository context passed to every skill |
| `created_at`, `updated_at` | float | Unix timestamps |
| `work_item` | object | Work-unit snapshot (§6) |
| `current_step` | str? | Stage most recently dispatched |
| `next_step` | str? | Head of the queue |
| `order` | list | Display order; remediation stages sit next to their origin |
| `pending_queue` | list | **Authoritative** — stages still to run, in order |
| `stages` | map | Stage key → stage record (§7) |
| `errors` | list | Append-only; each entry flagged recoverable or not |

`order` and `pending_queue` are distinct on purpose. `order` is for rendering and
never shrinks; `pending_queue` is the live plan and is consumed as the run
progresses.

### 5. Workflow status

| Status | Terminal | Meaning |
| --- | --- | --- |
| `not_started` | no | Created, nothing dispatched |
| `running` | no | Normal execution |
| `awaiting_approval` | no | Paused at a manual gate |
| `completed` | yes | Queue drained successfully |
| `failed` | yes | A required stage exhausted its retries |
| `blocked` | yes | A skill needs information nobody supplied |
| `escalated` | yes | Loop ceiling hit, or a skill asked for a human |
| `cancelled` | yes | Operator terminated the run |

`blocked` and `escalated` are **legitimate outcomes**, not defects. Per the
workflow contract, guessing past a blocker is the most expensive available
failure.

### 6. Work item

```json
{
  "id": "TASK-17",
  "title": "Paginate the notes list",
  "type": "Feature",
  "state": "Active",
  "description": "…",
  "acceptance_criteria": "…",
  "url": "https://tracker.example.com/issues/TASK-17",
  "metadata": {
    "area_path": "notes-api",
    "labels": "backend,api"
  }
}
```

A snapshot, taken at `start`. Core fields are tracker-neutral; anything specific
to a tracker lives in `metadata`, populated by a `TrackerAdapter`. With the default
`local` tracker these fields come straight from the `start` flags. The
orchestrator reads work items and (via an adapter) may comment on them; it never
writes their state field.

### 7. Stage record

```json
{
  "key": "fixer@reviewer",
  "skill": "fixer",
  "status": "completed",
  "attempts": [
    {
      "number": 1,
      "started_at": 1770000000.0,
      "ended_at": 1770000185.4,
      "duration_seconds": 185.4,
      "verdict": "success",
      "report_path": "runs/TASK-17/fixer@reviewer/attempt-1.report.md",
      "error": null,
      "summary": "Addressed both findings; added a regression test."
    }
  ],
  "summary": "Addressed both findings; added a regression test.",
  "deliverables": ["src/lib/pagination.js"],
  "decisions": ["Guarded the null rather than changing the signature"],
  "risks": ["Low: the guard hides a caller bug — noted for the reviewer"],
  "next_skill": "reviewer",
  "remediation_cycles": 0,
  "returns_to": "reviewer"
}
```

| Field | Meaning |
| --- | --- |
| `key` | Stage identity. Differs from `skill` for remediation stages. |
| `attempts` | **Append-only.** A retry never overwrites the record of what failed. |
| `deliverables` / `decisions` / `risks` | Bullets extracted from the report's corresponding sections |
| `next_skill` | What the skill recommended — advisory, not dispatch |
| `remediation_cycles` | How many times *this* stage has requested changes |
| `returns_to` | For a remediation stage, the origin that verifies its work |

### 8. Stage status

| Status | Meaning |
| --- | --- |
| `pending` | Queued, not yet dispatched |
| `running` | Dispatched, awaiting a report |
| `completed` | Produced a conformant report and advanced |
| `failed` | Exhausted its attempt budget |
| `blocked` | Reported a blocker |
| `skipped` | Operator skipped it |
| `escalated` | Requested a human, or hit the loop ceiling |

---

## 9. Stage keys

A stage key is normally the skill name. Remediation stages are namespaced by
origin:

```
reviewer                 the reviewer stage
fixer@reviewer           the fixer, running on the reviewer's findings
fixer@security           the fixer, running on the security findings
```

Without this, two independent fixer runs in the same workflow would share one
state record, and the second would silently overwrite the first's attempt history.

---

## 10. Recovery

Resume is not a special mode — it is the normal path:

```bash
loom next TASK-17     # reads state, returns the correct directive
```

Because state is written after every transition and `next` is idempotent
(repeated calls inspect the run rather than opening new attempts), a run can be
interrupted at any point and picked up in a different session, by a different
agent, days later.

The only unrecoverable cases are refused loudly rather than papered over:

| Case | Behaviour |
| --- | --- |
| State file missing | `StateError` naming the `start` command to run |
| State file corrupt | `StateError` quoting the JSON error |
| Schema newer than supported | `StateError` — upgrade the orchestrator or start fresh |

An in-flight attempt interrupted before `record` leaves the stage `running` with
an open attempt. The next `next` reuses that open attempt rather than inflating
the count, so the stage is simply re-dispatched.
