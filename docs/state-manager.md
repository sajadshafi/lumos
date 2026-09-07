# State Manager Specification

`orchestrator/state_manager.py` — sole owner of reading, mutating, and persisting
workflow state.

The engine never opens the state file. The CLI never opens the state file. That
exclusivity is what makes "recover an interrupted workflow" a property of the
system rather than a hopeful comment.

---

## 1. Interface

### Identity

```python
StateManager.run_id_for("task#17") -> "TASK-17"
```

Static and total. Normalises case and separator style — `TASK-17`, `task-17`,
`task#17` all map to one run id — so resuming never depends on retyping a
reference identically. Collapses non-alphanumerics to hyphens, which also prevents a work item reference escaping
the state directory. Raises `StateError` on input with no usable characters.

### Lifecycle

```python
exists(run_id)                            -> bool
create(work_item, workflow, branch, repo) -> WorkflowState
load(run_id)                              -> WorkflowState
load_or_create(...)                       -> (WorkflowState, resumed: bool)
save(state)                               -> Path
delete(run_id)                            -> bool
list_runs()                               -> list[str]
```

`create` seeds one `pending` stage per definition and fills `pending_queue` with
the full order.

`load_or_create` is the resume path. On an existing run it refreshes volatile
context that legitimately changes between sessions (the branch) while preserving
everything earned by prior stages.

### Mutation

Every state change goes through one of these — nothing mutates a `Stage`
directly:

```python
begin_attempt(state, stage_key)     -> Attempt   # opens attempt, marks running
complete_attempt(state, stage_key, verdict, status, summary, report_path, error)
add_stage(state, key, skill, returns_to)         # dynamic remediation stages
reset_stage(state, key)                          # return a stage to pending
set_status(state, status, save=True)
```

---

## 2. Atomic persistence

```python
temp = path.with_suffix(f".{os.getpid()}.tmp")
write(temp)
flush()
fsync()
os.replace(temp, path)
```

A run is interrupted by Ctrl-C, a closed terminal, or a crashed session more
often than by anything else. An in-place write risks a truncated state file,
which loses the entire run. `os.replace` is atomic on POSIX, so the file on disk
is always either the previous state or the next one — never a fragment.

The temp file carries the PID and is removed in a `finally`, so a crashed process
cannot leave a name that collides with the next one.

---

## 3. Attempts are append-only

```python
stage.attempts = [
    Attempt(number=1, verdict="failed", error="missing # Risks", duration_seconds=41.2),
    Attempt(number=2, verdict="success", duration_seconds=180.5),
]
```

A retry never overwrites the record of what failed. That history is the point:
it is what the timeline reconstructs, what the retry note quotes back to the
skill, and what tells a human whether a stage is flaky or genuinely stuck.

### Tolerating a missing `begin_attempt`

`complete_attempt` synthesises an attempt if none is open. A session resumed
after a crash may have lost the in-memory attempt while the work actually
happened — losing that record entirely would be worse than tolerating the
inconsistency.

---

## 4. Stage ordering

`add_stage` inserts a remediation stage immediately after the stage that spawned
it, rather than appending:

```
before:  [planner, coding, testing, reviewer, post-feature-implementation]
after:   [planner, coding, testing, reviewer, fixer@reviewer, post-feature-implementation]
```

`order` drives every rendered view. Appending would show the fixer running after
the PR stage, which is not what happened — a bug found by the first end-to-end
smoke run and covered by
`test_remediation_stage_is_ordered_next_to_its_origin`.

`order` and `pending_queue` are separate: `order` is for display and never
shrinks; `pending_queue` is the live plan and is consumed as the run progresses.

---

## 5. Refusal cases

The manager refuses loudly rather than papering over corruption:

| Case | Behaviour |
| --- | --- |
| State file missing | `StateError` naming the `start` command to run |
| Invalid JSON | `StateError` quoting the decode error and the path |
| `schema_version` newer than supported | `StateError` — upgrade the orchestrator or start a fresh run |
| Unknown stage key | `KeyError` naming the run |

A silently reset run would repeat expensive work; an explicit error costs one
message.

---

## 6. Schema evolution

`SUPPORTED_SCHEMA_VERSION = 1`. Every state file records the version it was
written with.

- **Additive change** (new optional field): `from_dict` defaults it; no bump. All
  readers use `data.get(...)` with a default, so old files load unchanged.
- **Breaking change** (field removed, or semantics changed): bump the constant
  and add a migration in `load`.

Reading a *newer* file is always refused. Silently ignoring fields written by a
future version would corrupt the run in ways that surface much later.

---

## 7. Concurrency

The state manager assumes **one writer per run**. This is not a limitation in
practice: a run is a sequential pipeline driven by one agent.

Two orchestrators driving the same run id would interleave writes. Atomic
replacement guarantees each individual write is whole, so the file is never
corrupt, but a lost update is possible. If concurrent drivers are ever needed,
add an `O_EXCL` lock file next to the state file — the interface does not change.

Note that the *log* is safe under concurrency regardless: it is opened `O_APPEND`
per write, so lines cannot interleave.
