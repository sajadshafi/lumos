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

Before starting a remotely tracked ticket, run `lumos trackers`. If the selected
MCP transport reports `connected: false`, explain that the runtime must expose
its MCP bridge through `LUMOS_MCP_COMMAND`; never request or write an access
token into `lumos.yaml`. The bridge contract is documented in
`docs/trackers.md`.

For `invoke_skill`, invoke the named skill with the full envelope. For
`invoke_agent`, load `agent_path`, delegate the envelope through the runtime's
native agent mechanism, and wait for its report. If native delegation is not
available, follow the agent instructions in the current context and disclose the
fallback. Preserve every worker report verbatim at `report_path`, then record it.

Never fabricate a report, reorder stages, count retries, or approve a gate. At a
terminal directive run `lumos summary <run_id>`. After creating a PR, run
`lumos publish <run_id> --pr-url <url>` once to post the summary and link it to
the source ticket; add `--transition <state>` only when project configuration or
the user explicitly authorizes that state change.
