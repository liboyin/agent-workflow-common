# agent-workflow-common

Shared tooling for agent-driven repositories. The tools are standalone Python scripts that use only the standard library. Each project keeps a pinned copy of a tool and its own configuration.

## Tools

- [tools/check_docs.py](tools/check_docs.py) checks the Markdown documentation of a repository.
- [tools/snapshot.py](tools/snapshot.py) records the state of a frozen Git candidate, so that two snapshots show an accidental change.
- [tools/dispatch.py](tools/dispatch.py) starts or continues an independent reviewer through the Codex CLI.

Each tool needs Python 3.11 or later and Git. Each tool's `--help` text describes its arguments.

## Configuration

A project configures the tools in one optional file, `agent-workflow.toml`, at the root of its repository. Each tool reads only its own table, and every key is optional.

```toml
[check_docs]
# Path prefixes of the files whose style is checked on changed lines only. Default: none.
changed_lines_only = ["DESIGN.md", "tasks/closed/"]

[check_docs.tasks]
# A regular expression that matches a whole task ID. Default: 'T\d+'.
id = '(?:T|NB)\d+'
# The text that may follow the ID in the title of a task file. Default: [":"].
title_separators = [":", " —"]
# Task files that the task rules skip. Default: none.
exempt = ["tasks/closed/an-old-record.md"]

[dispatch]
# The reviewer's model and reasoning effort. These are the defaults.
model = "gpt-6.1-sol"
effort = "medium"
# The review skill that the reviewer reads, relative to the root. This is the default.
skill = ".agents/skills/adversarial-review/SKILL.md"
# A project rule that the first prompt states. Default: none.
safety = "Never contact the live service, and never read .env."
```

`snapshot.py` has no configuration.

## check_docs.py

Run `./check_docs.py` from a repository.

- It checks that each relative link and each heading anchor resolves inside the repository.
- It checks the task files under `tasks/open/` and `tasks/closed/` against the index in `tasks/TODO.md`.
- It checks the style rules that need no judgment: sentence length, paragraph length, semicolons, alternatives joined by a slash, and one source line for each paragraph.
- It prints each problem as `path:line: rule: message`.
- The exit status is 0 without problems, 1 with problems, and 2 if the check cannot run.

`./check_docs.py --references TARGET` runs no check. It lists each line that links to a file, a directory or a `FILE#heading`.

## snapshot.py

Run `./snapshot.py [UNTRACKED...] > before.json` from a repository, and name each in-scope untracked file. Write the snapshot outside the repository.

- The snapshot holds `HEAD`, the status, the complete index, and the hash and mode of each changed or named file.
- It records the target of a symlink and never follows it. It never reads ignored content.
- It fails with status 2 for a submodule, or for a tracked path below a working-tree symlink.
- Take a second snapshot later and compare the two files, for example with `diff`. Compare only successful runs.
- The snapshot detects accidents. It does not protect against a concurrent change of the files.

## dispatch.py

`dispatch.py` writes the reviewer's prompt, runs the Codex CLI with closed standard input, and prints the session ID and the report.

- A first assessment needs `--record`, `--log`, `--boundary` and `--purpose`.
- A follow-up needs `--record`, `--log`, `--resume SESSION` and `--delta`.
- `--target` names the repository or the frozen worktree. The default is the working directory.
- The exit status is the CLI's status. It is 1 for a run without a report, and 2 for a missing CLI, a missing login or an invalid configuration.
- The tool runs the CLI with `--dangerously-bypass-approvals-and-sandbox`. Use it only where the user accepts that.

## Use a tool in a project

1. Copy the tool's file from `tools/` into the project.
2. Record the commit of this repository that the copy comes from.
3. Add the tool's table to the project's `agent-workflow.toml`, if the project needs one.
4. Do not edit the copy. Change the tool here, and copy the new version.

## Development

The project uses [uv](https://docs.astral.sh/uv/). Run the three checks before a commit:

```sh
uv run pytest
uv run ruff check .
uv run mypy tools
```

- pytest requires 100% statement coverage and branch coverage of `tools/`.
- Tests run in random order. Reproduce an ordering failure with the printed `--randomly-seed=<seed>`.
- Each test owns its Git repository under a temporary directory.
- No test reaches the real Codex CLI. The dispatch tests keep it off `PATH` and use a stub.
