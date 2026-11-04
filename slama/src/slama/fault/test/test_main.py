"""Tests for the fault CLI's logging setup (no SMAX needed)."""
import logging

import pytest

import slama.fault.__main__ as fault_main
from slama.smax_logging import SMAX_CLIENT_LOGGER, SMAX_LOGGER, RepeatedMissingKeyFilter


class _StopAfterLogging(Exception):
    """Raised in place of config loading, right after logging is set up."""


@pytest.fixture
def run_until_config(monkeypatch):
    """Run ``main`` only as far as config loading, restoring logging afterwards."""
    root, smax_parent = logging.getLogger(), logging.getLogger(SMAX_LOGGER)
    saved = (root.level, list(root.handlers), smax_parent.level,
             list(logging.getLogger(SMAX_CLIENT_LOGGER).filters))

    def stop(_path):
        raise _StopAfterLogging

    monkeypatch.setattr(fault_main.FaultConfig, "from_file", staticmethod(stop))

    def run(*argv):
        with pytest.raises(_StopAfterLogging):
            fault_main.main(["conf/faults.json", *argv])

    yield run
    root.setLevel(saved[0])
    root.handlers[:] = saved[1]
    smax_parent.setLevel(saved[2])
    logging.getLogger(SMAX_CLIENT_LOGGER).filters[:] = saved[3]


def test_log_level_takes_effect_despite_smax_import_basicconfig(run_until_config):
    import smax  # noqa: F401  (its import-time basicConfig is what made ours a no-op)
    run_until_config("--log-level", "INFO")
    assert logging.getLogger().level == logging.INFO


def test_smax_logging_configured(run_until_config):
    run_until_config()
    assert logging.getLogger(SMAX_CLIENT_LOGGER).getEffectiveLevel() == logging.WARNING
    assert any(isinstance(f, RepeatedMissingKeyFilter)
               for f in logging.getLogger(SMAX_CLIENT_LOGGER).filters)


# ---------------------------------------------------------------------------
# SMAX host/port, --as-of and --once (phase 2 CLI parity)
# ---------------------------------------------------------------------------

from slama.cli_common import DEFAULT_SMAX_HOST, DEFAULT_SMAX_PORT  # noqa: E402


def _parse(argv, environ):
    return fault_main._build_parser(environ).parse_args(["conf/faults.json", *argv])


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

    def test_bad_port_environment_is_a_usage_error(self, capsys):
        with pytest.raises(SystemExit) as exc:
            fault_main._build_parser({"SMAX_PORT": "not-a-port"})
        assert exc.value.code == 2
        assert "SMAX_PORT" in capsys.readouterr().err


def test_no_site_root_option():
    # The fault system reads no site files; the flag is deliberately absent.
    with pytest.raises(SystemExit):
        _parse(["--site-root", "/tmp"], {})


class _FakeFaultSystem:
    """Records construction kwargs and tick/run calls instead of running."""

    instances = []

    def __init__(self, config, monitor_system, client=None, **kwargs):
        self.client = client
        self.kwargs = kwargs
        self.ticks = 0
        self.ran_forever = False
        _FakeFaultSystem.instances.append(self)

    def tick(self):
        self.ticks += 1
        return []

    @property
    def last_snapshot(self):
        return {"nodes": {"a": {"state": "root"}, "b": {"state": "ok"},
                          "c": {"state": "ok"}}}

    def run_forever(self):
        self.ran_forever = True

    def set_interval(self, seconds):
        self.interval = seconds


@pytest.fixture
def fake_main(monkeypatch):
    """Patch out config, tree, client and FaultSystem so main() runs offline."""
    _FakeFaultSystem.instances = []
    root = logging.getLogger()
    saved = (root.level, list(root.handlers))
    monkeypatch.setattr(fault_main.FaultConfig, "from_file",
                        staticmethod(lambda path: object()))
    monkeypatch.setattr(fault_main, "MonitorSystem", lambda path: object())
    monkeypatch.setattr(fault_main, "SmaxRedisClient",
                        lambda host, redis_port: ("client", host, redis_port))
    monkeypatch.setattr(fault_main, "FaultSystem", _FakeFaultSystem)

    def run(*argv):
        rc = fault_main.main(["conf/faults.json", *argv])
        return rc, _FakeFaultSystem.instances[-1]

    yield run
    root.setLevel(saved[0])
    root.handlers[:] = saved[1]


def test_once_runs_exactly_one_tick(fake_main):
    rc, system = fake_main("--once")
    assert rc == 0
    assert system.ticks == 1
    assert not system.ran_forever


def test_without_once_runs_forever(fake_main):
    _, system = fake_main()
    assert system.ticks == 0
    assert system.ran_forever


def test_as_of_sets_only_the_wall_clock(fake_main):
    _, system = fake_main("--once", "--as-of", "1790094623")
    assert set(system.kwargs) == {"wall_clock"}
    assert system.kwargs["wall_clock"]() == 1790094623.0


def test_no_as_of_leaves_clocks_default(fake_main):
    _, system = fake_main("--once")
    assert system.kwargs == {}


def test_client_uses_resolved_host_and_port(fake_main, monkeypatch):
    monkeypatch.setenv("SMAX_HOST", "env-host")
    monkeypatch.setenv("SMAX_PORT", "6379")
    _, system = fake_main("--once")
    assert system.client == ("client", "env-host", 6379)


def test_once_logs_state_counts(fake_main, monkeypatch):
    # main() reconfigures logging with force=True, which drops caplog's
    # handler, so record the logger's calls directly.
    lines = []
    monkeypatch.setattr(fault_main.logger, "info",
                        lambda msg, *args: lines.append(msg % args))
    fake_main("--once")
    assert "--once: states ok 2, consequence 0, debouncing 0, ignored 0, root 1" in lines
