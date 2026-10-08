"""Tests for the compute engine CLI's SMAX host/port resolution (no SMAX needed)."""
import pytest

from slama.monitor.compute.__main__ import (
    DEFAULT_SMAX_HOST,
    DEFAULT_SMAX_PORT,
    _build_parser,
)


def _parse(argv, environ):
    return _build_parser(environ).parse_args(["conf/computations.json", *argv])


class TestSmaxHostPort:
    def test_defaults_without_environment(self):
        args = _parse([], {})
        assert (args.host, args.port) == (DEFAULT_SMAX_HOST, DEFAULT_SMAX_PORT)

    def test_environment_used_when_not_on_command_line(self):
        args = _parse([], {"SMAX_HOST": "smax.sma.hawaii.edu", "SMAX_PORT": "6379"})
        assert (args.host, args.port) == ("smax.sma.hawaii.edu", 6379)

    def test_command_line_overrides_environment(self):
        args = _parse(["--host", "cli-host", "--port", "7000"],
                      {"SMAX_HOST": "env-host", "SMAX_PORT": "6379"})
        assert (args.host, args.port) == ("cli-host", 7000)

    def test_empty_environment_values_fall_back_to_defaults(self):
        args = _parse([], {"SMAX_HOST": "", "SMAX_PORT": ""})
        assert (args.host, args.port) == (DEFAULT_SMAX_HOST, DEFAULT_SMAX_PORT)

    def test_bad_port_environment_is_a_usage_error(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _build_parser({"SMAX_PORT": "not-a-port"})
        assert exc.value.code == 2
        assert "SMAX_PORT" in capsys.readouterr().err

    def test_reads_os_environ_by_default(self, monkeypatch):
        monkeypatch.setenv("SMAX_HOST", "from-os-environ")
        monkeypatch.delenv("SMAX_PORT", raising=False)
        args = _build_parser().parse_args(["conf/computations.json"])
        assert (args.host, args.port) == ("from-os-environ", DEFAULT_SMAX_PORT)
