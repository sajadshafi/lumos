# Extension Guide

The orchestrator is designed so that growing to dozens of specialised skills
requires **no architectural change**. This guide covers the four things you are
likely to add, in increasing order of rarity.

The invariant that makes this work: **no skill name and no stage ordering appears
anywhere in `orchestrator/*.py`.** Grep for `"coding"` in the package and you
find it only in docstrings and default constraint text. Everything else is data.

---

## 1. Adding a skill to an existing workflow

The common case. Two steps, no code.

**Step 1 — create the skill.** Follow `examples/skills/README.md`:

```
examples/skills/security/
├── SKILL.md              ← required; frontmatter with name + description
├── examples/input.md
└── examples/output.md
```

The skill must emit the six-section report from
`examples/shared/output-format.md`. That is the entire integration
contract — the orchestrator needs nothing else.

**Step 2 — add it to a workflow:**

```yaml
  - skill: security
    description: Authorization, tenant isolation, injection surfaces, secrets.
    retry:
      max_attempts: 2
    remediation:
      skill: fixer
      max_cycles: 2
```

**Verify:**

```bash
lumos validate default
```

The already-shipped `full-review.yaml` is the worked example: it references
`security` and `performance`, which do not yet exist, and fails validation
cleanly rather than crashing. Write those two `SKILL.md` files and it starts
working with no other change.

---

## 2. Creating a new workflow

Drop a YAML file in `workflows/`. The filename is the workflow name.

```yaml
# workflows/docs-only.yaml
version: 1
name: docs-only
description: Documentation changes that touch no production source.
max_total_stages: 12

stages:
  - skill: coding
    description: Update the affected docs pages and READMEs.
    retry:
      max_attempts: 2

  - skill: reviewer
    description: Verify accuracy against the code being documented.
    retry:
      max_attempts: 2
    remediation:
      skill: fixer
      max_cycles: 2

  - skill: post-feature-implementation
    retry:
      max_attempts: 2
```

```bash
lumos validate docs-only
lumos start TASK-42 --workflow docs-only
```

Branching lives in separate workflow files, never in conditional YAML. An `if`
expression in a config file is an untestable programming language in disguise;
four small explicit workflows beat one clever one.

---

## 3. Changing retry or loop behaviour

Config only. See [`retry-and-errors.md`](retry-and-errors.md).

```yaml
    retry:
      max_attempts: 5                     # more attempts
      retry_on_contract_violation: false  # do not retry a drifting skill
      retry_on_blocked: true              # retry blockers (rarely right)
    remediation:
      max_cycles: 1                       # one loop, then escalate
```

Before raising a budget, ask whether another attempt actually has new information
to work with. If not, the honest fix is escalation, not more attempts.

---

## 4. Adding a stage capability

This is the only case that touches code, and it is rare. Say you want
`timeout_minutes` on a stage.

1. **`config.py`** — add the field to `StageDefinition` and parse it in
   `from_dict`. Default it, so existing workflows keep working.
2. **`engine.py`** — act on it in `next_directive`, likely by adding a field to
   the `Directive` the agent receives.
3. **`models.py`** — if it must survive a restart, add it to `Stage` and to both
   `to_dict`/`from_dict`. Reading uses `data.get(...)` with a default, so old
   state files still load.
4. **`SKILL.md`** — document what the agent should do with the new directive
   field. The engine can only instruct; the agent acts.
5. **Tests** — add to `test_config_and_runner.py` (parsing) and `test_engine.py`
   (behaviour).

If a change requires editing `report.py` or `state_manager.py`, stop and
reconsider — those implement versioned contracts, and changing them affects every
run and every skill.

---

## 5. Changing the report contract

The expensive one. `shared/output-format.md` is an API: every skill produces it
and every stage consumes it.

1. Update `shared/output-format.md` and `shared/workflow-contract.md`; bump the
   contract version.
2. Update `REQUIRED_SECTIONS` in `report.py`.
3. Update **every** `SKILL.md` in the same commit — a mixed fleet means some
   stages fail validation for reasons unrelated to their work.
4. Update `examples/output.md` for each skill; they are the regression baselines.
5. Bump `CONTRACT_VERSION` in `orchestrator/__init__.py`.

In-flight runs record the contract version they started under, so a mid-run bump
is visible in state rather than silently changing the rules.

---

## 6. What to keep out of the orchestrator

Cases that look like orchestrator features but are not:

| Temptation | Where it belongs |
| --- | --- |
| "Skip testing when the diff is docs-only" | A separate workflow. Conditional logic in config becomes unmaintainable fast. |
| "Have the orchestrator fix trivial review findings" | `fixer`. The moment the orchestrator writes code, no reviewer has seen that code. |
| "Summarise reports to save tokens in the next envelope" | Nowhere. Contract §1 is explicit: a skill given a paraphrase re-derives the repository and drifts. |
| "Auto-approve gates when the change is small" | Nowhere. A gate the machine can clear is not a gate. |
| "Transition the work item to Resolved on completion" | A human. Board state is a human signal. |
| "Run testing and reviewer in parallel" | Nowhere. You cannot review code that is not tested; the sequence is semantic, not incidental. |

---

## 7. Testing your extension

```bash
python3 -m unittest discover -s tests -t tests
```

`tests/support.py` builds a complete throwaway project — skills, workflows,
state, logs — so tests exercise real discovery and real persistence rather than
mocks:

```python
class MyExtensionTests(OrchestratorTestCase):
    workflow_text = """
version: 1
name: default
stages:
  - skill: coding
    retry:
      max_attempts: 2
"""

    def test_my_behaviour(self):
        engine = self.make_engine()
        directive = self.run_stage(engine, "coding", report(next_skill="None"))
        self.assertEqual(directive.action, "complete")
```

`self.run_stage(engine, key, report_text)` simulates a full invocation — begin
attempt, write report, validate, record — and returns the next directive.

A new stage capability needs at least: the happy path, the failure path, and what
happens when it interacts with a retry.
