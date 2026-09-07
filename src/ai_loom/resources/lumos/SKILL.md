---
name: lumos
description: "Run a ticket continuously through a configured spec-driven workflow of AI skills and delegated agents. Use for /lumos or $lumos requests, end-to-end ticket delivery, run resumption, and Lumos status checks."
---

# Lumos

Drive the deterministic Lumos engine; do not replace its sequencing decisions.

Accept `/lumos TC#123`, `$lumos TC#123`, or a bare number. Bare numbers and
`#123` use `ticket.prefix` from `lumos.yaml`; pass through explicit prefixes.

Start or resume with `lumos start <ticket>`. Keep the same turn active and repeat
`lumos next` → invoke worker → `lumos record` until `complete`, `abort`, or
`await_approval`. Never stop between ordinary stages to ask the user to continue.
Only `execution.mode: step` or a real human gate permits an early return.

For `invoke_skill`, invoke the named skill with the full envelope. For
`invoke_agent`, load `agent_path`, delegate the envelope through the runtime's
native agent mechanism, and wait for its report. If native delegation is not
available, follow the agent instructions in the current context and disclose the
fallback. Preserve every worker report verbatim at `report_path`, then record it.

Never fabricate a report, reorder stages, count retries, or approve a gate. At a
terminal directive run `lumos summary <run_id>` and report status, deliverables,
risks, and the PR link when present.

