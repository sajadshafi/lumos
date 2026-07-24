<!--
Default constraints injected into every skill's input envelope.

This is your project's house rules — the non-negotiables every skill must honour.
Replace the generic items below with yours (a UI kit to reuse, an SDK to prefer,
an architecture to follow, test requirements). Override per run with
`--constraints-file`, or delete this file to fall back to the built-in defaults.
-->

- Obey the write boundary declared in your SKILL.md without exception: only the
  skills a workflow authorises may modify source, tests, or documentation.
- Emit the six-section report contract, in order: Summary, Findings, Decisions,
  Deliverables, Risks, Next Skill.
- Keep every factual claim in Findings sourced to a path, symbol, command output,
  or an upstream report section. An unsourced claim is an assumption — put it in
  Risks or Open Questions.
- Ship tests with any behavioural change. A bug fix needs a test that fails
  before and passes after.
- Do not expand scope silently. Work discovered mid-run that is outside the
  objective goes into Findings, not into the diff.
- Match the surrounding naming, formatting, and idioms of the code you touch.
- Update the docs and READMEs the change affects.
