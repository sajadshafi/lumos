---
name: lumos
description: "Initialize projects or run tickets continuously through configured workflows of AI skills and delegated agents. Use for /lumos or $lumos init, ticket delivery, resumption, and status checks."
---

# Lumos

Drive the deterministic Lumos engine; do not replace its sequencing decisions.

If the request is `/lumos init`, `$lumos init`, or asks to initialize Lumos,
run `lumos init` in the requested project directory and report the generated
files. Pass through requested `--name`, `--ticket-prefix`, or `--tracker`
options. Never add `--force` unless the user explicitly asks to overwrite
existing scaffold files. After a successful initialization, run
`lumos validate default` and invite the user to customize the generated workers
and workflow. Do not interpret `init` as a ticket identifier.

Accept `/lumos TC#123`, `$lumos TC#123`, or a bare number. Bare numbers use
`ticket.prefix` from `lumos.yaml`; pass through explicit prefixes.

Start or resume with `lumos start <ticket>`. Keep the same turn active and repeat
`lumos next` → invoke worker → `lumos record` until `complete`, `abort`, or
`await_approval`. Never stop between ordinary stages to ask the user to continue.
Only `execution.mode: step` or a real human gate permits an early return.

Before starting a remotely tracked ticket, run `lumos trackers`. If the selected
MCP transport reports `connected: false`, explain that the runtime must expose
its MCP bridge through `LUMOS_MCP_COMMAND`; never request or write an access
token into `lumos.yaml`.

For `invoke_skill`, invoke the named skill with the full envelope. For
`invoke_agent`, load `agent_path`, delegate through the runtime's native agent
mechanism, wait for the report, and preserve it verbatim at `report_path`. If
native delegation is unavailable, follow the agent file in the current context
and disclose the fallback.

Never fabricate a report, reorder stages, count retries, or approve a human gate.
At a terminal directive run `lumos summary`. After creating a PR, run
`lumos publish <run_id> --pr-url <url>` once; transition the ticket only when the
project configuration or user explicitly authorizes the target state.
