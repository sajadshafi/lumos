---
name: lumos
description: "Run a ticket continuously through a configured spec-driven workflow of AI skills and delegated agents. Use for /lumos requests, end-to-end delivery, resume, and status."
---

# Lumos

Start or resume the requested ticket with the `lumos` CLI. In continuous mode,
keep the same turn active and loop over `lumos next`, worker invocation, and
`lumos record` until the engine returns `complete`, `abort`, or
`await_approval`. Never stop after an ordinary stage to ask for “continue”.

For `invoke_skill`, use the named Skill with the full envelope. For
`invoke_agent`, read `agent_path`, delegate the full envelope with Claude Code's
agent/Task capability, wait for its report, and write that report verbatim to
`report_path`. If delegation is unavailable, follow the agent instructions in
the current context and disclose that fallback.

Do not fabricate reports, reorder work, count retries, or approve a human gate.
At termination, run `lumos summary` and report the outcome.
