from abc import ABC, abstractmethod
from typing import Any, Union
import astropy.units as u
from astropy.time import Time
import numpy as np
from smax import SmaxRedisClient
from smax.smax_data_types import SmaxVarBase, _SMAX_TYPE_MAP
from enum import IntEnum, auto
from numbers import Number


class Validity(IntEnum):
    INVALID_NO_DATA = auto()
    INVALID_NO_HW = auto()
    INVALID_HW_BAD = auto()
    VALID = auto()
    VALID_NOT_CHECKED = auto()
    VALID_GOOD = auto()
    VALID_WARNING = auto()
    VALID_ERROR = auto()
    VALID_WARNING_LOW = auto()
    VALID_WARNING_HIGH = auto()
    VALID_ERROR_LOW = auto()
    VALID_ERROR_HIGH = auto()
    MAX_VALIDITY = auto()


_STATE_VALIDITY_NAMES: dict[str, Validity] = {
    "GOOD": Validity.VALID_GOOD,
    "WARNING": Validity.VALID_WARNING,
    "ERROR": Validity.VALID_ERROR,
}
"""Short aliases accepted in a MonitorPoint's ``state_validity`` map.

Full :class:`Validity` member names (e.g. ``"VALID_ERROR_HIGH"``) are also
accepted, via a fallback to ``Validity[name]``, so a state can be mapped to
any validity, not just these three common ones.
"""

class MonitorPoint(SmaxVarBase):
    def __init__(
        self,
        name: str,
        canonical_name: str,
        smax_type: str = None,
        unit: Union[u.Unit | str] = None,
        units: Union[u.Unit | str] = None,
        description: str = None,
        size: str = None,
        range: str = None,
        validity: Validity = Validity.VALID_GOOD,
        err_low: Any = None,
        err_high: Any = None,
        warn_low: Any = None,
        warn_high: Any = None,
        valid_strings: list = None,
        state_validity: dict = None,
        unknown_state: str = "ERROR",
        **kwargs
    ):
        if unit is None and units is not None:
            unit = units
        if smax_type is not None:
            if isinstance(smax_type, dict):
                print(f"Found invalid smax_type=[dict] in monitor point {canonical_name=}")
            elif smax_type in _SMAX_TYPE_MAP.keys():
                _SMAX_TYPE_MAP[smax_type].__init__(self)
            else:
                print(f"Found invalid {smax_type=} in monitor point {canonical_name=}")
        self._name = name
        self.smaxname=canonical_name
        self.description=description
        self.unit=unit=str(unit)
        self.size=size
        self._err_low = err_low
        self._err_high = err_high
        self._warn_low = warn_low
        self._warn_high = warn_high
        self._valid = True
        self._valid_strings = valid_strings  # used only for string type MPs
        self._state_validity = state_validity  # used only for string type MPs
        self._unknown_state = unknown_state
        self._smax_result = None  # stores result from smax_pull()

    @property
    def name(self) -> str:
        return self._name

    @property
    def canonical_name(self) -> str:
        return self.smaxname

    @property
    def table(self) -> str:
        return self.smaxname.rsplit(":", 1)[0]

    @property
    def key(self) -> str:
        return self.smaxname.rsplit(":", 1)[1]

    @property
    def value(self) -> Any:
        return self._smax_result

    @property
    def time(self) -> Time:
        if self._smax_result is None:
            return None
        return Time(self._smax_result.timestamp)
#
    @property
    def units(self) -> u.Unit:
        if self.unit is None:
            return None
        else:
            return u.Unit(self.unit)

    @property
    def err_low(self) -> Any:
        return self._err_low

    @property
    def err_high(self) -> Any:
        return self._err_high

    @property
    def errRange(self) -> list:
        return [self._err_low, self._err_high]

    @property
    def warn_low(self) -> Any:
        return self._warn_low

    @property
    def warn_high(self) -> Any:
        return self._warn_high

    @property
    def warnRange(self) -> list:
        return [self._warn_low, self._warn_high]

    # @todo Mps will not have validities...
    @property
    def isValid(self) -> bool:
        return self._valid  # should be validity > INVALID_HW_BAD

    def set_valid_strings(self, valid_strings: list) -> None:
        self._valid_strings = valid_strings

    @property
    def validity(self) -> Validity:
        v = self.value
        if isinstance(v, Number):
            return self._numeric_validity()

        if isinstance(v, str):
            return self._string_validity()

        if isinstance(v, bool):
            return self._bool_validity()
        return Validity.VALID_NOT_CHECKED

    def _numeric_validity(self) -> Validity:
        v = self.value
        if self.err_high is not None and v >= self.err_high:
            return Validity.VALID_ERROR_HIGH
        if self.err_low is not None and v <= self.err_low:
            return Validity.VALID_ERROR_LOW
        if self.warn_high is not None and v >= self.warn_high:
            return Validity.VALID_WARNING_HIGH
        if self.warn_low is not None and v <= self.warn_low:
            return Validity.VALID_WARNING_LOW
        return Validity.VALID_GOOD

    def _string_validity(self) -> Validity:
        if self._state_validity is not None:
            return self._state_machine_validity()
        v = self.value
        if self.err_high is not None and v in self.err_high:
            return Validity.VALID_ERROR_HIGH
        if self.err_low is not None and v in self.err_low:
            return Validity.VALID_ERROR_LOW
        if self.warn_high is not None and v in self.warn_high:
            return Validity.VALID_WARNING_HIGH
        if self.warn_low is not None and v in self.warn_low:
            return Validity.VALID_WARNING_LOW
        if self._valid_strings is not None and self.value in self._valid_strings:
            return Validity.VALID_GOOD
        if self._valid_strings is None:
            return Validity.VALID_GOOD
        return Validity.VALID_ERROR

    def _state_machine_validity(self) -> Validity:
        """Validity for a string point whose values are named states.

        Looks ``self.value`` up in ``self._state_validity``; an
        unrecognized state resolves ``self._unknown_state`` instead
        (default ``"ERROR"``), so a schema gap is a deliberate policy
        rather than a silent false alarm.

        ``self.value`` is coerced to ``str`` before the lookup: a real
        ``smax_pull()`` result is a ``smax.smax_data_types.SmaxStr``,
        which — being a dataclass with the default ``eq=True`` — has
        ``__hash__`` set to ``None`` and so cannot be used as a dict
        key directly, even though it compares equal to the plain
        ``str`` values used as keys in ``state_validity``.
        """
        name = self._state_validity.get(str(self.value), self._unknown_state)
        return _STATE_VALIDITY_NAMES.get(name) or Validity[name]

    def _bool_validity(self) -> Validity:
        return Validity.VALID_NOT_CHECKED

    def update(self, result) -> None:
        self._smax_result = result

    def isGood(self) -> bool:
        return self.validity == Validity.VALID_GOOD


class MonitorPointUpdater:
    def __init__(self, mp: MonitorPoint, client: SmaxRedisClient, lazy=False):
        self._mp = mp
        # valkey server
        self._client = client
        self._lazy = lazy

    @property
    def mp(self):
        return self._mp

    def update(self) -> None:
        """read from self.client and write data to mp"""
        result = self._client.smax_pull(self.mp.table, self.mp.key)
        self._mp.update(result)


class MonitorPointSubscriber:
    """for lazy pulling, get notified when changed
    be sure to mutex lock when read/write
    """

    def __init__(self, mp: MonitorPoint, client: SmaxRedisClient, sleep=5):
        self._mp = mp
        self._client = client
        self._sleep = sleep
        self.subscribe()

    def subscribe(self):
        self._client.subscribe(
            self._mp.canonical_name, callback=self._mp.update, pubsub_sleep=self._sleep
        )

    def unsubscribe(self):
        self._client.unsubscribe()


class MonitorPointWriter:
    def __init__(self, mp: MonitorPoint, client: SmaxRedisClient):
        self._mp = mp
        # valkey server
        self._client = client

    def write(self, value) -> None:
        """read from self.client and write data to mp"""
        self._client.smax_share(self._mp.table, self._mp.key, value)
