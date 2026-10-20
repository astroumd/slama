"""Tame the smax-python library's logging for long-running SLAMA processes.

``smax.smax_redis_client`` logs an INFO line for every successful
``smax_pull`` and ``smax_share``, and an ERROR line *before* raising
``SmaxKeyError`` for a key that isn't in Redis. A compute-engine tick
reads and writes several hundred points, so at INFO the library alone
logs ~900 lines per tick, and a key that is legitimately absent (e.g. an
optional input) logs the same ERROR every tick.

:func:`configure_smax_logging` sets the library's level (default
WARNING) and installs :class:`RepeatedMissingKeyFilter`, which lets the
first "Could not find" for each key through and then only an occasional
reminder.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Callable


SMAX_LOGGER: str = "smax"
"""Parent logger of every smax-python module logger."""

SMAX_CLIENT_LOGGER: str = "smax.smax_redis_client"
"""The logger ``SmaxRedisClient`` writes to (``smax_redis_client.py``)."""

DEFAULT_REMINDER_S: float = 3600.0
"""How often a still-missing key is logged again."""

_MISSING_RE = re.compile(r"^Could not find (\S+) in Redis")
"""Matches ``smax_redis_client.py``'s ``smax_pull`` missing-key ERROR."""


class RepeatedMissingKeyFilter(logging.Filter):
    """Pass the first "Could not find <key>" per key, then one per reminder interval.

    Every other record passes unchanged, so a new missing key, or any
    other smax error, is always seen.

    Parameters
    ----------
    reminder_s : float, optional
        Seconds after a key's last logged occurrence before it is logged
        again, annotated with how many repeats were suppressed.
    clock : callable, optional
        Monotonic clock returning seconds; injectable for tests.
    """

    def __init__(self, reminder_s: float = DEFAULT_REMINDER_S,
                 clock: Callable[[], float] = time.monotonic):
        super().__init__()
        self.reminder_s = reminder_s
        self._clock = clock
        self._seen: dict[str, list] = {}  # key -> [last_logged, suppressed]

    def filter(self, record: logging.LogRecord) -> bool:
        """Decide whether ``record`` is emitted, annotating reminders.

        Parameters
        ----------
        record : logging.LogRecord
            The record being logged.

        Returns
        -------
        bool
            ``False`` for a repeat within the reminder interval;
            ``True`` otherwise.
        """
        message = record.getMessage()
        match = _MISSING_RE.match(message)
        if not match:
            return True
        key, now = match.group(1), self._clock()
        seen = self._seen.get(key)
        if seen is None:
            self._seen[key] = [now, 0]
            return True
        last, suppressed = seen
        if now - last < self.reminder_s:
            seen[1] += 1
            return False
        record.msg = f"{message} (still missing; {suppressed} repeats suppressed since last logged)"
        record.args = ()
        self._seen[key] = [now, 0]
        return True


def configure_smax_logging(level: str | int = "WARNING",
                           reminder_s: float = DEFAULT_REMINDER_S) -> RepeatedMissingKeyFilter:
    """Set the smax library's log level and install the missing-key filter.

    Call after ``logging.basicConfig(...)``. Safe to call more than once:
    an earlier :class:`RepeatedMissingKeyFilter` is replaced, not stacked.

    Parameters
    ----------
    level : str or int, optional
        Level for the ``smax`` logger hierarchy (default ``"WARNING"``,
        which hides the per-pull / per-share INFO lines).
    reminder_s : float, optional
        Passed to :class:`RepeatedMissingKeyFilter`.

    Returns
    -------
    RepeatedMissingKeyFilter
        The installed filter.
    """
    logging.getLogger(SMAX_LOGGER).setLevel(level.upper() if isinstance(level, str) else level)
    client_logger = logging.getLogger(SMAX_CLIENT_LOGGER)
    for old in [f for f in client_logger.filters if isinstance(f, RepeatedMissingKeyFilter)]:
        client_logger.removeFilter(old)
    new = RepeatedMissingKeyFilter(reminder_s=reminder_s)
    client_logger.addFilter(new)
    return new
