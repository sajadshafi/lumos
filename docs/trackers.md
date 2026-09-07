# Tracker integrations

Lumos supports GitHub Issues, Jira Cloud, GitLab Issues, and Azure DevOps Boards
through one provider-neutral `TrackerAdapter` contract. The workflow engine sees
only a normalized `WorkUnit`; provider APIs and fields stay in adapters.

## Quick start

Configure a provider in `lumos.yaml`, then validate the resolved connection:

```bash
lumos trackers
lumos start 123
```

Use command-line overrides for one run:

```bash
lumos start 123 --tracker github --tracker-transport rest \
  --tracker-option repository=owner/repository
```

CLI values override environment values, which override `lumos.yaml`. `local` is
the default and requires no connection. Tokens, passwords, API keys, and other
secret-looking values are rejected from tracker options.

After a completed run, publish the final summary and optionally link a pull
request and transition the ticket:

```bash
lumos publish GH-123 --pr-url https://github.com/owner/repository/pull/45
lumos publish PROJ-123 --transition Done
```

Writes are capability-gated. Every remote write carries a stable idempotency key
for transports to deduplicate after a retry or resumed run.

## Transports

### MCP bridge

`transport: mcp` keeps authentication in the AI runtime. Set
`LUMOS_MCP_COMMAND` to an executable bridge supplied by that runtime. Lumos sends
one JSON object to stdin:

```json
{"provider":"github","operation":"fetch","params":{"work_id":"123","options":{"repository":"owner/repo"}}}
```

The bridge returns either `{"result": ...}` or `{"error": "safe message"}`.
Supported operations are `fetch`, `comment`, `link_pull_request`, and
`transition`. This subprocess boundary lets Codex, Claude, or another host map
the request to its connected MCP tools without copying MCP credentials into
Lumos. `lumos trackers` reports `connected: false` until the command is set.

### REST

`transport: rest` uses Python's standard-library HTTP client and environment
credentials. HTTP 401, 403, 404, and 429 responses become typed authentication,
permission, not-found, and throttling errors. Error messages never include
authorization headers or raw provider response bodies.

## GitHub Issues

```yaml
tracker:
  provider: github
  transport: rest
  options:
    repository: owner/repository
```

- References: `#123`, `GH#123`, `123`, issue URLs, or `owner/repository#123`.
- REST credentials: `GITHUB_TOKEN` or `GH_TOKEN`.
- Recommended permissions: Issues read/write and repository metadata read.
- Metadata: repository, labels, assignees, and milestone.
- Markdown task-list items are extracted as acceptance criteria.

For GitHub Enterprise, set the non-secret `api_url` option. A 404 may mean the
GitHub App/token cannot access a private repository, not only that the issue is
missing.

## Jira Cloud

```yaml
tracker:
  provider: jira
  transport: rest
  options:
    site: https://example.atlassian.net
    project_key: PROJ
    acceptance_criteria_field: customfield_10042
```

- References: `PROJ-123` or Jira browse URLs.
- REST credentials: `JIRA_EMAIL` with `JIRA_API_TOKEN`, or bearer `JIRA_TOKEN`.
- Recommended permissions: browse projects, read issues, add comments, create
  remote links, and transition issues only when transitions are requested.
- Atlassian Document Format paragraphs, lists, code blocks, links, and line
  breaks are normalized before reaching worker prompts.
- A transition name is resolved against the issue's currently valid transitions.

Custom field identifiers vary by Jira site. Omit
`acceptance_criteria_field` when the project does not use one.

## GitLab Issues

```yaml
tracker:
  provider: gitlab
  transport: rest
  options:
    host: https://gitlab.com
    project: group/project
```

- References: `123`, `group/project#123`, or an issue URL.
- REST credential: `GITLAB_TOKEN`.
- Recommended scope: `api` for writes or the narrowest instance-specific scope
  that permits issue reads and notes.
- Metadata: project, labels, assignees, milestone, weight, and confidentiality.
- Self-managed instances are supported through `host`; issue URLs also resolve
  the host and project, preventing an IID from being used against the wrong project.

Confidential ticket data is placed only in the run's own `WorkUnit` and artifacts.
Apply filesystem and log access controls appropriate to that content.

## Azure DevOps Boards

```yaml
tracker:
  provider: azure-devops
  transport: rest
  options:
    organization: my-organization
    project: MyProject
    prefix: AB
```

- References: numeric IDs, `AB#123`, `AB-123`, or work-item URLs.
- REST credential: `AZURE_DEVOPS_TOKEN`.
- Recommended scope: Work Items read/write; add code/repository scopes only when
  the chosen PR relation type requires them.
- Metadata: area, iteration, tags, assignee, revision, and relations.
- HTML descriptions and acceptance criteria are normalized to stable text.
- External PR URLs are attached as work-item hyperlinks.

Custom Azure DevOps processes may use different fields and state names. Lumos
passes an explicitly requested state to the API; revision conflicts remain
visible as failures and should be retried only after re-fetching the item.

## Troubleshooting

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `connected: false` for MCP | No bridge command | Set `LUMOS_MCP_COMMAND` in the runtime environment. |
| Authentication error | Missing, expired, or wrong credential | Set the provider's documented environment variable. |
| Permission error | Token/App lacks a write scope | Add only the required scope, or run read-only. |
| Not found on a private project | The installation cannot see it | Verify repository/project selection and installation access. |
| Throttled error | Provider rate limit | Retry later; do not create a new Lumos run. |
| Transition unavailable | State is invalid from the current status | Inspect the provider's valid transitions and configuration. |

## Opt-in live smoke test

Normal CI uses fake transports and never contacts a tracker. To verify one
disposable test ticket, set the provider, reference, transport, and JSON-encoded
non-secret options, then run the integration module:

```bash
LUMOS_INTEGRATION_PROVIDER=github \
LUMOS_INTEGRATION_WORK_ID=123 \
LUMOS_INTEGRATION_TRANSPORT=rest \
LUMOS_INTEGRATION_OPTIONS='{"repository":"owner/test-repository"}' \
python -m unittest tests.test_tracker_integration
```

Set `LUMOS_INTEGRATION_WRITE=1` only for a disposable ticket to test comments.
Provider credentials still use the environment variables described above.

## Adding another provider

Subclass `TrackerAdapter` (normally `RemoteTracker`), declare capabilities,
normalize supported references, map `fetch` into `WorkUnit`, and register the
class with `register_adapter`. Inject a fake `TrackerTransport` into the adapter
and run the shared contract expectations: fetch normalization, metadata, comment,
PR linking, transition, typed errors, and stable idempotency keys. Provider SDKs
must not be imported by the deterministic workflow engine.

Published packages can register without modifying Lumos:

```toml
[project.entry-points."lumos.trackers"]
linear = "my_lumos_adapter:LinearTracker"
```

The entry point name becomes the value accepted by `tracker.provider` and
`--tracker`. Its object must be a `TrackerAdapter` subclass.
