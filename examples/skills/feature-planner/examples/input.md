## Objective

Users can page through their notes without the client loading the entire list at
once.

## Context

- Work unit: TASK-1, branch `feat/task-1-paginate-notes`
- Service: the `notes-api` module
- Prior art: the activity feed already paginates and is worth copying
- Product decision: page size defaults to 20, made by the PM

## Constraints

- No new runtime dependencies
- No breaking change to the existing `GET /notes` response for clients that do
  not opt in
- Ship with tests

## Previous Outputs

None (first skill in chain)
