# agent-workflow-common

Shared tooling for agent-driven repositories. The tools are standalone Python scripts that use only the standard library. Each project keeps a pinned copy of a tool and its own configuration.

## Tools

- [tools/check_docs.py](tools/check_docs.py) checks the Markdown documentation of a repository.

A Git candidate snapshot and a reviewer dispatcher are planned.

## check_docs.py

Run `./check_docs.py` from a repository. It needs Python 3.11 or later and Git.

- It checks that each relative link and each heading anchor resolves inside the repository.
- It checks the task files under `tasks/open/` and `tasks/closed/` against the index in `tasks/TODO.md`.
- It checks the style rules that need no judgment: sentence length, paragraph length, semicolons, alternatives joined by a slash, and one source line for each paragraph.
- It prints each problem as `path:line: rule: message`.
- The exit status is 0 without problems, 1 with problems, and 2 if the check cannot run.

`./check_docs.py --references TARGET` runs no check. It lists each line that links to a file, a directory or a `FILE#heading`.

An optional `check_docs.toml` at the root of the repository configures the check. Every key is optional.

```toml
# Path prefixes of the files whose style is checked on changed lines only. Default: none.
changed_lines_only = ["DESIGN.md", "tasks/closed/"]

[tasks]
# A regular expression that matches a whole task ID. Default: 'T\d+'.
id = '(?:T|NB)\d+'
# The text that may follow the ID in the title of a task file. Default: [":"].
title_separators = [":", " —"]
# Task files that the task rules skip. Default: none.
exempt = ["tasks/closed/an-old-record.md"]
```

## Use a tool in a project

1. Copy the tool's file from `tools/` into the project.
2. Record the commit of this repository that the copy comes from.
3. Add the project's configuration file.
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
- Each test owns its Git repository under a temporary directory, and reads no Git configuration of the host.
