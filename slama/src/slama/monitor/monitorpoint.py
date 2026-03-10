from abc import ABC, abstractmethod
from typing import Any, Union
import astropy.units as u
from astropy.time import Time
import numpy as np
from smax import SmaxRedisClient
from smax.smax_data_types import SmaxVarBase, _SMAX_TYPE_MAP
from pathlib import Path
import json
from collections import UserList
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
    
class AMonitorPoint:
    """Represents a collection of primitive (leaf) values or a list."""
    def __init__(self, name, values):
        self.name = name
        self.values = values  # dict (for key/values) or list (for arrays)

    def __repr__(self):
        if isinstance(self.values, dict):
            return f"<MonitorPoint {self.name}: {len(self.values)} values>"
        else:
            return f"<MonitorPoint {self.name}: list of {len(self.values)} items>"


class MonitorPoint(SmaxVarBase):
    def __init__(
        self,
        name: str,
        canonical_name: str,
        smax_type: str,       
        unit: Union[u.Unit | str] = None,
        description: str = None,
        size: str = None,
        range: str = None,
        validity: Validity = Validity.VALID_GOOD,
        err_low: Any = None,
        err_high: Any = None,
        warn_low: Any = None,
        warn_high: Any = None,
        valid_strings: list = None,
        **kwargs
    ):
        #print(f"{name=},{canonical_name=},{smax_type=},{description=},{range=},{unit=},{kwargs=}\n")
        if isinstance(smax_type,dict) :
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

    def _bool_validity(self) -> Validity:
        return Validity.VALID_NOT_CHECKED

    def update(self, result) -> None:
        self._smax_result = result

    def isGood(self) -> bool:
        return self.validity == Validity.VALID_GOOD


class MonitorPointList(UserList):
    def __init__(self, mpjsonlist):
        mplist = []
        for m in mpjsonlist:
            mplist.append(MonitorPoint(**m))
        UserList.__init__(self, mplist)

    @classmethod
    def from_file(self, path: Path):
        mplist = json.load(open(path, "r"))
        return MonitorPointList(mplist["monitorpoints"])


class MonitorListUpdater:
    def __init__(
        self, mplist: MonitorPointList, client: SmaxRedisClient, lazy=False, updatenow=True
    ):
        self._mplist = mplist
        # valkey server
        self._client = client
        self._lazy = lazy
        if updatenow:
            self.update()

    @property
    def mplist(self):
        return self._mplist

    def __getitem__(self, index):
        return self._mplist[index]

    def __len__(self):
        return len(self._mplist)

    def update(self) -> None:
        """read from self.client and write data to mp"""
        # @todo use lazy pull -- Not Implemented in Python

        for mp in self.mplist:
            result = self._client.smax_pull(mp.table, mp.key)
            mp.update(result)


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
