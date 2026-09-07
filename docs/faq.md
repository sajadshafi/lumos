# FAQ

### How is this different from a prompt runner or an agent framework?

A prompt runner sends prompts and trusts the result. `Lumos` moves the parts
that must be exact — state, attempt counts, retry budgets, loop ceilings, resume,
contract validation — into deterministic code the agent never controls. The agent
supplies judgment; the engine supplies the guarantees. It is the reliability
layer *under* your agent, not a replacement for it.

### Does it call an LLM?

No. The engine is pure standard-library Python and never makes a network or model
call. It hands out a markdown envelope and validates the markdown report that
comes back. A *driver* (see [`adapters/`](../adapters/)) is what actually runs a
model.

### Which agents does it work with?

Anything that can run a CLI and read/write a file: Claude Code and GitHub Copilot
ship as drivers, and [`DRIVER-SPEC.md`](../adapters/DRIVER-SPEC.md) is the ~30-line
contract for adding another (Cursor, a plain script, a human). The engine doesn't
know or care which one is driving.

### Do I have to use Azure DevOps / any issue tracker?

No. The default `local` tracker needs nothing external — the work unit is whatever
you pass on the command line. Trackers are pluggable via `TrackerAdapter`
(`src/ai_loom/adapters/`); an `azure-devops` stub shows the shape. Tracker-specific
fields ride along in a free-form `--metadata key=value` map.

### What happens when a report is malformed?

The engine rejects it, re-queues the same stage, and quotes the specific violation
into the next envelope ("missing required section: # Risks"). The skill tries
again with the reason in hand. You never count attempts — the retry budget in the
workflow does.

### What are `blocked` and `escalated`? Did the run fail?

No — they are legitimate terminal outcomes. `blocked` means a skill needs
information nobody supplied; `escalated` means a review loop didn't converge within
its cycle ceiling, or a skill explicitly asked for a human. Reporting one honestly
is worth more than forcing a green run. `failed` (a stage exhausted its retries) is
the third terminal non-success state.

### Can the orchestrator edit my code?

Never. The engine writes only its own state, logs, and run artifacts. The only
things that touch production source are skills a workflow explicitly authorises —
by convention just `coding` and `fixer`. Every other skill treats the working tree
as read-only.

### A run died halfway. Do I lose it?

No. State is written atomically after every step. `lumos next <run>` reads the
state file and returns the correct next directive — resume is the normal path, not
a special mode.

### How do I add a stage to a pipeline?

Edit the workflow YAML. If the skill it names already exists, that's the whole
change — no engine edit. See [workflow design](workflow-design.md).

### Why `unittest` and not `pytest`? Why no dependencies?

So the engine runs on a bare interpreter anywhere, with nothing to install. YAML
is parsed by PyYAML when present and a bundled fallback parser otherwise; state is
JSON; tests are stdlib. Keeping the dependency budget at zero is a feature, not an
oversight.

### Is `loom` still supported?

Yes. Lumos is the final project name and `lumos` is the primary command. `loom`
remains a compatibility alias for 0.1 installations and scripts.
