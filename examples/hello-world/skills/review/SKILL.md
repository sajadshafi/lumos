---
name: review
description: "Check the draft from the previous step and either accept it or list what to change. The second step of the hello-world chain."
---

# review

Read the `draft` report from `# Previous Outputs`. Judge whether it meets the
Objective.

Emit the six-section report. If the draft is good, set `# Next Skill` to
`None — complete`. If it needs work, list the specific changes under `# Findings`
and set `# Next Skill` to `None — changes requested` (the hello chain has no
`fixer`, so this just ends the run with a clear verdict).
