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
