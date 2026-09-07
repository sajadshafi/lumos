# Lumos Copilot driver

When asked to run Lumos, start or resume the ticket with `lumos start`. Continue
the full `next` → invoke → `record` loop in the same response until a terminal
directive or approval gate. Do not pause between normal stages.

For `invoke_skill`, load the named `SKILL.md` and perform it with the full input
envelope. For `invoke_agent`, load `agent_path` and use Copilot's delegated agent
facility when available; otherwise follow the agent definition in the current
context and disclose the fallback. Save the exact six-section report at
`report_path` before recording it.

Never invent reports, reorder stages, decide retries, or approve a human gate.
Run `lumos summary` at termination.
