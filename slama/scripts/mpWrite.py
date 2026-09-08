#!/usr/bin/env python3
import argparse
import os
import random
import time
import sys
import numpy as np
from astropy.coordinates import SkyCoord, EarthLocation
from astropy.table import Table
import astropy.units as u
from pathlib import Path
from smax import SmaxRedisClient

from slama.monitor import (
    MonitorPoint,
    MonitorPointUpdater,
    MonitorPointWriter,
)
from slama.coordinates import SMA
SMALOC = SMA()

_DEFAULT_HOST = os.environ.get("SMAX_HOST", "localhost")
_DEFAULT_PORT = int(os.environ.get("SMAX_PORT", 6380))

class MpWrite:

    def __init__( self, mpname:str, smax_type:str,unit:str,description:str,value, host: str = _DEFAULT_HOST, port: int = _DEFAULT_PORT):
        self._client = SmaxRedisClient(host, redis_port=port)
        self._mp = MonitorPoint(name=mpname,canonical_name=mpname,smax_type=smax_type, unit=unit, description=description)
        self._mpw = MonitorPointWriter(self._mp,self._client)
        self._mpu = MonitorPointUpdater(self._mp,self._client)
        self._value=value

    def write(self):
        self._mpw.write(self._value, meta=True)

    def update(self):
        self._mpu.update()


def main() -> None:
    doc = "Writes monitor points to the SMAX database. Python analog of smaxWrite. Can be used to update values of existing monitor points or create new monitor points on the fly."
    parser = argparse.ArgumentParser(prog = "SMAX monitor point writer",description=doc)
    parser.add_argument("--host", default=_DEFAULT_HOST, help="SMAX/Redis host (default: $SMAX_HOST or localhost)")
    parser.add_argument("--port", "-p", type=int, default=_DEFAULT_PORT, help="SMAX/Redis port (default: $SMAX_PORT or 6380)")
    parser.add_argument("--type", "-t", type=str, required=True, help="type e.g., int, float, string, bool, raw")
    parser.add_argument("--description", "-d", type=str, required=False, help="description string", default="")
    parser.add_argument("--unit", "-u", type=str, required=False, help="unit string", default="")
    parser.add_argument("--check", "-c", action="store_true", help="Check that the point exists before writing.  Do not write if it does not exist")
    parser.add_argument("mpname", type=str, help="monitor point canonical name, must be able to be represented as form table:key")
    parser.add_argument("mpvalue", help="monitor point value")
    args = parser.parse_args()

    sw = MpWrite(args.mpname, args.type, args.unit, args.description, args.mpvalue, args.host,args.port)
    if args.check:
        try:
            sw.update()
        except Exception as exc:
            print(f"monitor point {args.mpname} does not exist {exc}")
            sys.exit()
        print(f"monitor point {args.mpname} exists with value={sw._mp.value} with {sw._mp.metadata}")
    sw.write()

    
if __name__ == "__main__":
    main()
