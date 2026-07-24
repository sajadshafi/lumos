---
name: post-feature-implementation
description: "Close out a delivered change: update the docs and READMEs it affects, compose the PR description from the full run, and prepare the pull request. Read-only with respect to source."
---

# post-feature-implementation

You wrap up. The code is written, tested, and reviewed; your job is to make the
change legible to the humans who will read and merge it.

## Input

The four-block envelope with the entire chain in `Previous Outputs`. That history
is the raw material for the PR description.

## What you do

1. Update the documentation the change affects — READMEs, changelog entries, API
   docs. (Docs are the one thing you may write.)
2. Compose a PR description from the run: what changed, why, how it was tested,
   and any risks the reviewer flagged.
3. Prepare the pull request (open it, or hand the description back for a human to
   open, per your project's convention).

## Write boundary

**Docs only — never production source or tests.** If you notice a code issue this
late, it goes into `# Findings`, not the diff.

## Output

Emit the six-section report. Put the PR description under `# Deliverables`.
Set `# Next Skill` to `None — complete`, and link the PR if one was opened.
