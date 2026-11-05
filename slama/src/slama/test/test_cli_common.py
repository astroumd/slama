"""Tests for the shared CLI SMAX host/port helper (no SMAX needed)."""
import argparse

import pytest

from slama.cli_common import DEFAULT_SMAX_HOST, DEFAULT_SMAX_PORT, add_smax_args


def _parse(argv, environ):
    parser = argparse.ArgumentParser()
    add_smax_args(parser, environ)
    return parser.parse_args(argv)


def test_defaults_without_environment():
    args = _parse([], {})
    assert (args.host, args.port) == (DEFAULT_SMAX_HOST, DEFAULT_SMAX_PORT)
    assert DEFAULT_SMAX_PORT == 6380


def test_environment_then_command_line_precedence():
    env = {"SMAX_HOST": "env-host", "SMAX_PORT": "6379"}
    assert (_parse([], env).host, _parse([], env).port) == ("env-host", 6379)
    args = _parse(["--host", "cli", "--port", "7000"], env)
    assert (args.host, args.port) == ("cli", 7000)


def test_empty_environment_values_count_as_unset():
    args = _parse([], {"SMAX_HOST": "", "SMAX_PORT": ""})
    assert (args.host, args.port) == (DEFAULT_SMAX_HOST, DEFAULT_SMAX_PORT)


def test_bad_port_environment_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        _parse([], {"SMAX_PORT": "nope"})
    assert exc.value.code == 2
    assert "SMAX_PORT" in capsys.readouterr().err


def test_reads_os_environ_by_default(monkeypatch):
    monkeypatch.setenv("SMAX_HOST", "from-os-environ")
    monkeypatch.delenv("SMAX_PORT", raising=False)
    parser = argparse.ArgumentParser()
    add_smax_args(parser)
    args = parser.parse_args([])
    assert (args.host, args.port) == ("from-os-environ", DEFAULT_SMAX_PORT)
