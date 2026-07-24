# Logging Strategy

One append-only JSONL file per run:
`logs/<run-id>.jsonl`.

---

## 1. Why JSONL

The timeline is queried far more often than it is read top-to-bottom. `jq` over
one event per line beats regex over prose, every time:

```bash
# every retry in the run
jq 'select(.event == "stage_retry")' logs/TASK-17.jsonl

# slowest stages first
jq -s 'map(select(.duration_seconds)) | sort_by(-.duration_seconds) | .[:5]' …

# did any review loop fail to converge?
jq 'select(.event == "escalated")' …
```

Append-only, opened `O_APPEND` per write so concurrent writers cannot interleave
partial lines.

---

## 2. Event schema

```json
{
  "ts": 1770000185.421,
  "iso": "2026-07-20T18:15:37",
  "run_id": "TASK-17",
  "event": "stage_completed",
  "stage": "coding",
  "skill": "coding",
  "status": "completed",
  "attempt": 2,
  "duration_seconds": 180.5,
  "error": null,
  "detail": { "remaining": 1 }
}
```

`ts` and `iso` are both present deliberately: one sorts and subtracts correctly,
the other is readable without a converter. Optional fields are omitted rather
than written as `null`, keeping lines compact.

---

## 3. Event catalogue

| Event | Emitted when | Key fields |
| --- | --- | --- |
| `workflow_started` | A new run is created | `detail.workflow`, `detail.stages` |
| `workflow_resumed` | An existing run is picked up | `status` |
| `stage_started` | A stage is dispatched | `stage`, `skill`, `attempt` |
| `stage_completed` | A stage produced a conformant report | `duration_seconds` |
| `stage_retry` | A stage failed with budget remaining | `error`, `detail.remaining` |
| `stage_failed` | A stage exhausted its budget | `error`, `attempt` |
| `stage_blocked` | A skill reported a blocker | `detail.summary` |
| `stage_skipped` | An operator skipped a stage | `detail.reason` |
| `optional_stage_skipped` | An optional stage failed, run continues | `error` |
| `remediation_queued` | A review requested changes | `detail.cycle`, `detail.max_cycles` |
| `remediation_returned` | A fixer finished, control returns to the origin | `detail.returns_to` |
| `escalated` | Loop ceiling hit, or a skill asked for a human | `detail.cycles` |
| `approval_granted` | A manual gate was cleared | `stage` |
| `workflow_cancelled` | An operator cancelled | `detail.reason` |
| `workflow_finished` | The run reached a terminal state | `status`, `detail.reason` |

---

## 4. Rendered timeline

```bash
loom timeline TASK-17
```

```
  ELAPSED  EVENT                  SKILL                        STATUS             DETAIL
  -------  ---------------------- ---------------------------- ------------------ ------------------
    00:00  workflow_started                                    running
    00:00  stage_started          feature-planner              running            attempt 1
    02:14  stage_completed        feature-planner              completed          attempt 1, 134.2s
    02:14  stage_started          coding                       running            attempt 1
    06:41  stage_retry            coding                       failed             attempt 1, 267.1s, missing # Risks
    06:41  stage_started          coding                       running            attempt 2
    11:22  stage_completed        coding                       completed          attempt 2, 281.0s
    11:22  stage_started          testing                      running            attempt 1
    14:03  stage_completed        testing                      completed          attempt 1, 161.4s
    14:03  stage_started          reviewer                     running            attempt 1
    15:30  remediation_queued     reviewer                     changes_requested  attempt 1
    15:30  stage_started          fixer@reviewer               running            attempt 1
    18:12  stage_completed        fixer@reviewer               completed          attempt 1, 162.3s
    18:12  remediation_returned   fixer                                           
    18:12  stage_started          reviewer                     running            attempt 2
    19:40  stage_completed        reviewer                     completed          attempt 2, 88.0s
    19:40  stage_started          post-feature-implementation  running            attempt 1
    21:15  stage_completed        post-feature-implementation  completed          attempt 1, 95.2s
    21:15  workflow_finished                                   completed
```

Elapsed time is relative to the first event, because absolute timestamps make it
hard to see where a run actually spent its time.

The same timeline is embedded in `loom summary` output, so the artifact
posted to the work item is self-contained.

---

## 5. Robustness

`iter_events` skips any line that fails to parse rather than raising. A truncated
final line from an interrupted write must not make the whole timeline unreadable
— an incident is the worst possible moment for the diagnostic tool to be strict.

---

## 6. What is deliberately not logged

- **Report and envelope contents.** They are large, and already persisted under
  `runs/<run-id>/`. The log records paths, not payloads.
- **Anything the orchestrator did not do.** No speculative entries, no "would
  have" events.
- **Secrets.** Work item fields are logged only as ids and titles; descriptions
  and acceptance criteria go into envelopes on disk, not into the event stream.

Log files are gitignored: they are large, machine-generated, and meaningful only
to the session that produced them. The orchestrator's *code* and *workflow
definitions* are project knowledge and are committed.

---

## 7. Retention

No automatic rotation. A run's log is typically tens of kilobytes, and the value
of keeping it is high while a work item is open. To clear finished runs:

```bash
# remove artifacts for runs that reached a terminal state
loom runs \
  | jq -r '.runs[] | select(.status | IN("completed","cancelled")) | .run_id' \
  | while read -r id; do
      rm -f "state/$id.state.json" \
            "logs/$id.jsonl"
      rm -rf "runs/$id"
    done
```

Review the list before deleting — the reports under `runs/` are the audit trail
for what shipped.
