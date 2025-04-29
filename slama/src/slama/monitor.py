from abc import ABC, abstractmethod
from typing import Any, Union
import astropy.units as u
import numpy as np

class MonitorPoint:
    def __init__(self,name:str,value:Any,units:Union[u.Unit|str],description:str = None, errLo:Any=None, errHi:Any = None, warnLo:any = None, warnHi:any=None):
        self._name = name
        self._description = description
        self._value = value
        self._units = units
        self._errLo = errLo
        self._errHi = errHi
        self._warnLo = errLo
        self._warnHi = warnHi
        self._valid = True

    @property
    def name(self) -> str:
        return self._name

    @property
    def value(self) -> Any:
        return self._value

    @property
    def units(self)-> u.Unit:
        if self._units is None:
            return u.dimensionless_unscaled
        # this could raise a ValueError if self._units is not a valid
        # unit.  Are we allowing non-astropy units?
        return u.Unit(self._units)

    @property
    def errLo(self) -> Any:
        return self._errLo

    @property
    def errHi(self) -> Any:
        return self._errHi

    @property 
    def errRange(self) -> list:
        return [self._errLo, self._errHi]

    @property
    def warnLo(self) -> Any:
        return self._warnLo

    @property
    def warnHi(self) -> Any:
        return self._warnHi

    @property 
    def warnRange(self) -> list:
        return [self._warnLo, self._warnHi]

    @property
    def isValid(self) -> bool:
        return self._valid

class MonitorPointUpdater:
    def __init__(self,url:str):
        # valkey server
        self._url = url

    def update(mp:MonitorPoint) -> None:
        """ read from self.url and write data to mp """
        pass



