"""Tests for :mod:`slama.smax_logging`."""
import logging

import pytest

from slama.smax_logging import (
    SMAX_CLIENT_LOGGER,
    SMAX_LOGGER,
    RepeatedMissingKeyFilter,
    configure_smax_logging,
)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def record(msg, level=logging.ERROR):
    return logging.LogRecord(SMAX_CLIENT_LOGGER, level, __file__, 1, msg, (), None)


MISSING_A = "Could not find antenna:1:receiver:a:cartridge in Redis"
MISSING_B = "Could not find antenna:1:receiver:b:cartridge in Redis"


class TestRepeatedMissingKeyFilter:
    def test_first_occurrence_passes_repeats_dropped(self):
        f = RepeatedMissingKeyFilter(clock=Clock())
        assert f.filter(record(MISSING_A))
        assert not f.filter(record(MISSING_A))
        assert not f.filter(record(MISSING_A))

    def test_each_key_tracked_separately(self):
        f = RepeatedMissingKeyFilter(clock=Clock())
        assert f.filter(record(MISSING_A))
        assert f.filter(record(MISSING_B))
        assert not f.filter(record(MISSING_B))

    def test_reminder_after_interval_reports_suppressed_count(self):
        clock = Clock()
        f = RepeatedMissingKeyFilter(reminder_s=3600, clock=clock)
        f.filter(record(MISSING_A))
        for _ in range(5):
            clock.t += 2
            assert not f.filter(record(MISSING_A))
        clock.t = 3600.0
        rec = record(MISSING_A)
        assert f.filter(rec)
        assert rec.getMessage() == MISSING_A + " (still missing; 5 repeats suppressed since last logged)"
        clock.t += 2
        assert not f.filter(record(MISSING_A))   # interval restarts

    @pytest.mark.parametrize("msg", [
        "Reading antenna:1:x from Redis <client> failed",
        "Successfully pulled antenna:1:x",
        "Could not find",                        # no key: not the pattern
    ])
    def test_other_messages_always_pass(self, msg):
        f = RepeatedMissingKeyFilter(clock=Clock())
        assert f.filter(record(msg)) and f.filter(record(msg))


class TestConfigureSmaxLogging:
    @pytest.fixture(autouse=True)
    def restore(self):
        parent, client = logging.getLogger(SMAX_LOGGER), logging.getLogger(SMAX_CLIENT_LOGGER)
        level, filters = parent.level, list(client.filters)
        yield
        parent.setLevel(level)
        client.filters[:] = filters

    def test_sets_level_and_installs_one_filter(self):
        configure_smax_logging("warning")
        configure_smax_logging("WARNING")
        client = logging.getLogger(SMAX_CLIENT_LOGGER)
        assert client.getEffectiveLevel() == logging.WARNING
        assert sum(isinstance(f, RepeatedMissingKeyFilter) for f in client.filters) == 1

    def test_real_smax_logger_hides_info_and_dedupes(self, caplog):
        import smax.smax_redis_client as src  # the logger the library actually uses
        configure_smax_logging("WARNING")
        with caplog.at_level(logging.DEBUG):
            logging.getLogger().setLevel(logging.DEBUG)
            src.logger.info("Successfully pulled antenna:1:x")
            src.logger.error(MISSING_A)
            src.logger.error(MISSING_A)
        msgs = [r.getMessage() for r in caplog.records if r.name == SMAX_CLIENT_LOGGER]
        assert msgs == [MISSING_A]
