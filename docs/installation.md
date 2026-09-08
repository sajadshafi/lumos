# Installation and runtime management

Lumos has two installation layers. `pipx` installs the isolated Python CLI;
`lumos install` installs the small integration that teaches each AI runtime how
to drive that CLI.

## Recommended setup

```bash
pipx install lumos
lumos install
lumos doctor
```

Before the PyPI release, install from GitHub instead:

```bash
pipx install git+https://github.com/sajadshafi/lumos.git
lumos install
```

Running `lumos install` without an argument detects Codex and Claude Code. It
installs only integrations whose runtime home or executable can be found. An
undetected runtime is reported as skipped and no directory is created for it.

## Installation commands

```bash
lumos install                 # all detected runtimes
lumos install --dry-run       # preview without writing
lumos install --dry-run --json
lumos install --all           # every supported runtime, detected or not
lumos install --force         # replace modified managed files
lumos install codex           # one runtime, preserving existing syntax
lumos install claude
```

`--destination PATH` remains available with one explicit runtime. It cannot be
combined with automatic multi-runtime installation because one path cannot
safely represent multiple runtime homes.

Installation is idempotent. Every integration gets a `.lumos-install.json`
manifest containing its runtime, Lumos version, managed relative paths, and
content hashes. A repeated install whose files match reports `unchanged`.

Lumos can adopt a pre-manifest installation when all known files exactly match
the packaged integration. It writes the manifest without disturbing the files.
If a destination is user-authored or a managed file has been modified, Lumos
reports a conflict. Review the destination before choosing `--force`.

Each file is written to a temporary sibling and atomically replaced. A failure
in one runtime is reported independently and does not hide results for others.

## Detection and destinations

| Runtime | Detection | Default integration destination |
| --- | --- | --- |
| Codex | `CODEX_HOME`, an existing `~/.codex`, or the `codex` executable | `$CODEX_HOME/skills/lumos` or `~/.codex/skills/lumos` |
| Claude Code | `CLAUDE_HOME`, an existing `~/.claude`, or the `claude` executable | `$CLAUDE_HOME/skills/lumos` or `~/.claude/skills/lumos` |

Explicit `lumos install <runtime>` is authorization to create that runtime's
default destination even when automatic detection cannot find it. `--all` does
the same for every supported runtime.

Restart or reload a runtime after an installed or updated result. Skipped,
unchanged, and dry-run results require no restart.

## Doctor

```bash
lumos doctor
lumos doctor --json
```

Doctor checks:

- Lumos CLI and Python versions.
- Project discovery and `lumos.yaml` parsing.
- Resolved skill and agent directories.
- Detected runtime homes and integration manifests.
- Missing, modified, or version-mismatched managed files.
- Selected tracker provider, transport, and connection availability.
- MCP bridge presence when an MCP tracker transport is selected.

Human output includes remediation commands. JSON output has `schema_version: 1`
and stable check objects for support automation. Neither format prints credential
values or the MCP command itself.

## Safe uninstall

```bash
lumos uninstall codex
lumos uninstall claude --dry-run
lumos uninstall --all
lumos uninstall --all --dry-run --json
```

Uninstall requires one runtime or `--all`; there is no implicit automatic
uninstall. Lumos removes only relative files recorded in a valid, matching
manifest. It validates every resolved target before deleting the first file,
removes empty managed subdirectories, and preserves unrelated files. A legacy or
unmanaged destination is left untouched.

## Troubleshooting

| Result | Meaning | Action |
| --- | --- | --- |
| `skipped` | Runtime was not detected | Install it explicitly or use `--all`. |
| `unchanged` | Managed files match this CLI version | No action. |
| `repair-manifest` | Legacy files match exactly | Run without dry-run to adopt them. |
| `conflict` | Unmanaged or modified files would be replaced | Review the files; use `--force` only if replacement is intended. |
| `outdated-or-modified` | Doctor found a hash or version mismatch | Run the displayed install command after reviewing local changes. |
| `not-managed` | Uninstall found no valid manifest | Remove user-owned files manually if desired. |

## Extending runtime support

New AI tools subclass `RuntimeInstaller` and register through
`register_runtime_installer`. The CLI works from the registry and contains no
runtime-specific installation branches. Implementations provide detection and
destination metadata while reusing manifest, planning, verification, atomic
write, and safe-uninstall behavior.
