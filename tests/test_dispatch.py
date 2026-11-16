"""Exercise the reviewer dispatch with owned Git repositories and a stub of the Codex CLI."""

import importlib.util
import json
import runpy
import shlex
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# The tool is a standalone script, so the tests load it by file path.
SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'dispatch.py'
SPEC = importlib.util.spec_from_file_location('dispatch', SCRIPT)
assert SPEC is not None and SPEC.loader is not None
dispatch = importlib.util.module_from_spec(SPEC)
sys.modules['dispatch'] = dispatch  # dataclasses resolve annotations through the module table
SPEC.loader.exec_module(dispatch)


def git(root, *args):
    """Run git in an owned repository with a fixed identity and return its output."""
    return subprocess.run(
        ['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', *args], cwd=root, check=True,
        capture_output=True, text=True,
    ).stdout


@pytest.fixture
def repo(tmp_path):
    """Provide an owned repository with one commit."""
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'README.md').write_text('# Project\n', encoding='utf-8')
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'add', 'README.md')
    git(root, 'commit', '-q', '-m', 'start')
    return root


@pytest.fixture(autouse=True)
def no_real_codex(tmp_path, monkeypatch):
    """Keep the real Codex CLI off PATH, so that no test can reach it or the user's login."""
    tools = tmp_path / 'tools-only'
    tools.mkdir()
    for name in ('git', 'bash'):
        found = subprocess.run(['which', name], check=True, capture_output=True, text=True).stdout.strip()
        (tools / name).symlink_to(found)
    monkeypatch.setenv('PATH', str(tools))


def stub_codex(tmp_path, monkeypatch, *events, status=0, login=0):
    """Put a ``codex`` stub first on PATH that answers the login check and records its other arguments."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    record = tmp_path / 'codex-args'
    output = '\n'.join(json.dumps(event) for event in events) + '\nnot json\n'
    stub = bin_dir / 'codex'
    stub.write_text(
        '#!/bin/bash\n'
        f'if [ "$1" = login ]; then echo "login state {login}"; exit {login}; fi\n'
        f'printf "%s\\n" "$@" > {shlex.quote(str(record))}\n'
        f'printf "%s" {shlex.quote(output)}\n'
        f'exit {status}\n',
        encoding='utf-8',
    )
    stub.chmod(0o755)
    monkeypatch.setenv('PATH', str(bin_dir), prepend=':')
    return record


STARTED = {'type': 'thread.started', 'thread_id': 'abc'}
REPORT = {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'No blocking findings.'}}
FIRST = ['--record', 'rec.md', '--boundary', 'tasks/open/T1.md', '--purpose', 'Do a thing.']


def test_dispatch_reads_the_base_revision_from_the_target(tmp_path, repo, monkeypatch, capsys):
    """The prompt names the target's actual HEAD, the dispatch arguments and closed stdin."""
    record = stub_codex(tmp_path, monkeypatch, STARTED, REPORT)
    log = tmp_path / 'log.jsonl'
    with patch.object(dispatch.subprocess, 'run', wraps=subprocess.run) as run:
        status = dispatch.main([*FIRST, '--target', str(repo), '--log', str(log), '--ignore', 'junk.sh'])
    # An open non-terminal stdin makes the CLI wait for more prompt text instead of starting.
    assert run.call_args_list[-1].kwargs['stdin'] is subprocess.DEVNULL
    arguments = record.read_text(encoding='utf-8')
    assert status == 0
    assert git(repo, 'rev-parse', 'HEAD').strip() in arguments
    assert 'gpt-6.1-sol' in arguments
    assert 'model_reasoning_effort="medium"' in arguments
    assert f'Read {repo}/.agents/skills/adversarial-review/SKILL.md and perform step 3' in arguments
    assert "under the skill's rules.\n" in arguments
    assert 'Unrelated paths to ignore: junk.sh.' in arguments
    assert 'tasks/open/T1.md' in arguments
    assert capsys.readouterr().out == 'SESSION abc\nNo blocking findings.\n'
    assert 'thread.started' in log.read_text(encoding='utf-8')


def test_dispatch_uses_the_settings_of_the_target(tmp_path, repo, monkeypatch):
    """The model, the effort, the skill and the safety rule come from the target's configuration."""
    record = stub_codex(tmp_path, monkeypatch, STARTED, REPORT)
    (repo / 'agent-workflow.json').write_text(
        json.dumps({
            'check_docs': {'another': 'tool reads this object'},
            'dispatch': {
                'model': 'model-x', 'effort': 'high', 'skill': 'docs/REVIEW.md', 'safety': 'Never call the bank.',
            },
        }),
        encoding='utf-8',
    )
    assert dispatch.main([*FIRST, '--target', str(repo), '--log', str(tmp_path / 'log')]) == 0
    arguments = record.read_text(encoding='utf-8')
    assert '--model\nmodel-x\n' in arguments
    assert 'model_reasoning_effort="high"' in arguments
    assert f'Read {repo}/docs/REVIEW.md and perform step 3' in arguments
    assert "under the skill's rules. Never call the bank.\n" in arguments
    assert 'the dispatch arguments are model-x and high' in arguments
    assert 'gpt-6.1-sol' not in arguments


def test_dispatch_resumes_the_recorded_reviewer(tmp_path, repo, monkeypatch):
    """A follow-up continues the named session with the configured model rather than starting another."""
    record = stub_codex(tmp_path, monkeypatch, REPORT)
    (repo / 'agent-workflow.json').write_text('{"dispatch": {"model": "model-x"}}', encoding='utf-8')
    status = dispatch.main([
        '--record', 'rec.md', '--target', str(repo), '--log', str(tmp_path / 'log'),
        '--resume', 'abc', '--delta', 'A fix.',
    ])
    lines = record.read_text(encoding='utf-8').splitlines()
    assert status == 0
    assert lines[:2] == ['exec', 'resume']
    assert 'abc' in lines
    assert 'model-x' in lines
    assert any('A fix.' in line for line in lines)


@pytest.mark.parametrize(('text', 'message'), [
    ('{"dispatch"', 'agent-workflow.json: '),
    ('{"dispatch": 1}', 'agent-workflow.json: the file or dispatch is not an object'),
    ('[]', 'agent-workflow.json: the file or dispatch is not an object'),
    ('{"dispatch": {"modle": "x"}}', 'agent-workflow.json: unknown key dispatch.modle'),
    ('{"dispatch": {"effort": 3}}', 'agent-workflow.json: dispatch.effort is not a string'),
])
def test_dispatch_stops_on_an_invalid_configuration(tmp_path, repo, monkeypatch, capsys, text, message):
    """A file that is not JSON, an unknown key and a value that is no string stop the dispatch unsent."""
    record = stub_codex(tmp_path, monkeypatch, STARTED, REPORT)
    (repo / 'agent-workflow.json').write_text(text, encoding='utf-8')
    assert dispatch.main([*FIRST, '--target', str(repo), '--log', str(tmp_path / 'log')]) == 2
    assert f'dispatch: {message}' in capsys.readouterr().err
    assert not record.exists()


def test_dispatch_stops_on_a_configuration_that_is_not_text(tmp_path, repo, monkeypatch, capsys):
    """A configuration file that is not UTF-8 is reported instead of raising."""
    stub_codex(tmp_path, monkeypatch, STARTED, REPORT)
    (repo / 'agent-workflow.json').write_bytes(b'\xff\xfe')
    assert dispatch.main([*FIRST, '--target', str(repo), '--log', str(tmp_path / 'log')]) == 2
    assert 'dispatch: agent-workflow.json: ' in capsys.readouterr().err


def test_dispatch_propagates_the_cli_status(tmp_path, repo, monkeypatch):
    """A failed CLI run is a failed dispatch, even with a partial report."""
    stub_codex(tmp_path, monkeypatch, REPORT, status=3)
    assert dispatch.main([*FIRST, '--target', str(repo), '--log', str(tmp_path / 'log')]) == 3


def test_dispatch_fails_without_a_report(tmp_path, repo, monkeypatch, capsys):
    """A successful exit with no report is not a review."""
    stub_codex(tmp_path, monkeypatch, STARTED)
    assert dispatch.main([*FIRST, '--target', str(repo), '--log', str(tmp_path / 'log')]) == 1
    assert 'no report' in capsys.readouterr().err


def test_dispatch_stops_when_the_cli_is_not_logged_in(tmp_path, repo, monkeypatch, capsys):
    """A failed login check is a blocker: nothing is sent, and the message forbids a substitute."""
    record = stub_codex(tmp_path, monkeypatch, STARTED, REPORT, login=1)
    assert dispatch.main([*FIRST, '--target', str(repo), '--log', str(tmp_path / 'log')]) == 2
    error = capsys.readouterr().err
    assert 'codex login status exited with 1: login state 1' in error
    assert 'This blocks the review' in error
    assert 'do not use another reviewer or model' in error
    assert not record.exists()
    assert not (tmp_path / 'log').exists()


def test_dispatch_stops_when_the_cli_is_missing(tmp_path, repo, capsys):
    """Without a codex command the dispatch reports the blocker instead of raising."""
    assert dispatch.main([*FIRST, '--target', str(repo), '--log', str(tmp_path / 'log')]) == 2
    error = capsys.readouterr().err
    assert 'the codex command cannot run' in error
    assert 'This blocks the review' in error


@pytest.mark.parametrize('arguments', [
    ['--record', 'r', '--log', 'l'], ['--record', 'r', '--log', 'l', '--resume', 'abc'],
    ['--record', 'r', '--log', 'l', '--boundary', 'b'], ['--record', 'r', '--log', 'l', '--purpose', 'p'],
])
def test_dispatch_requires_the_right_arguments_for_its_mode(tmp_path, monkeypatch, arguments, capsys):
    """A first assessment needs its boundary and purpose, and a follow-up its delta, before the CLI is asked."""
    record = stub_codex(tmp_path, monkeypatch, STARTED, REPORT, login=1)
    with pytest.raises(SystemExit) as raised:
        dispatch.main(arguments)
    assert raised.value.code == 2
    error = capsys.readouterr().err
    assert 'needs' in error
    assert 'login state' not in error
    assert not record.exists()


def test_the_script_runs_as_a_program(monkeypatch, capsys):
    """The entry point runs the command line; --help exits cleanly."""
    monkeypatch.setattr(sys, 'argv', ['dispatch', '--help'])
    with pytest.raises(SystemExit) as raised:
        runpy.run_path(str(SCRIPT), run_name='__main__')
    assert raised.value.code == 0
    assert 'usage' in capsys.readouterr().out
