#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simulate SMA observatory observations by writing fake antenna
tracking, weather, and tsys data to SMAX via the monitor point API.

Usage:
    cd src/slama
    uv run fakeobs.py
"""

import random
import time

import numpy as np
from astropy.coordinates import SkyCoord
import astropy.units as u
from pathlib import Path
from smax import SmaxRedisClient

from slama.monitor import (
    MonitorPointList,
    MonitorPointUpdater,
    MonitorPointWriter,
)


class FakeObs:
    def __init__(self):
        self._client = SmaxRedisClient("localhost", redis_port=6380)
        conf_path = Path(__file__).parent / "conf" / "mpdefs.json"
        self._mplist = MonitorPointList.from_file(conf_path)

        # Index monitor points by canonical name for quick lookup
        self._mp_by_name = {mp.canonical_name: mp for mp in self._mplist}

        # Pre-create writers and updaters for each monitor point
        self._writers = {
            name: MonitorPointWriter(mp, self._client)
            for name, mp in self._mp_by_name.items()
        }
        self._updaters = {
            name: MonitorPointUpdater(mp, self._client)
            for name, mp in self._mp_by_name.items()
        }

        self._coord = SkyCoord(12.936435, -5.7893122222, unit=(u.hr, u.deg), frame="icrs")
        self._source = "3c279"
        self._freq = 345.0
        self._vel = 0
        self.setsource(self._source, self._coord, self._vel, self._freq)
        self._lst = 10.33813
        self._ut = 15.77354516
        self.time()
        self.tsys(init=True)
        self._rh = 3.3428
        self._tamb = 4.513
        self._vwind = 3.1
        self._winddir = 42.31
        self._patm = 626.8255
        self.weather(init=True)
        self.slew(119.6513, 47.281)
        self._sources = {
            "ORIMSR": SkyCoord("5:35:14.5 -05:22:30.5", frame="icrs", unit=(u.hr, u.deg)),
            "3c279": SkyCoord("12:56:11.167 -05:47:21.52", frame="icrs", unit=(u.hr, u.deg)),
        }

    def write(self, canonical_name, value):
        """Write a value to a monitor point via the MonitorPointWriter API."""
        self._writers[canonical_name].write(value)

    def read(self, canonical_name):
        """Read the current value of a monitor point via MonitorPointUpdater.

        Returns the raw numeric value (float) for numeric types,
        or the value as-is for non-numeric types.
        """
        self._updaters[canonical_name].update()
        value = self._mp_by_name[canonical_name].value
        try:
            return float(value)
        except (TypeError, ValueError):
            return value

    def observe(self, source):
        self._source = source
        self._vel = 5.0
        self._freq = 230.538
        self._coord = self._sources[source]
        self.setsource(self._source, self._coord, self._vel, self._freq)
        if source == "ORIMSR":
            az = 95
            el = 30
        elif source == "3c279":
            az = 170
            el = 45

        azincr = 0.004
        elincr = 0.003
        timeincr = 0.003
        self.slew(az, el)
        i = 0
        while i < 20:
            i += 1
            if el > 89.0:
                elincr = -0.016
            az += azincr
            el += elincr
            self._ut += timeincr
            self._lst += timeincr
            self.time()
            self.slew(az, el)
            self.time()
            if i % 500 == 0:
                self.tsys()
                self.time()
            self.weather()
            self.time()
            self.oops()
            self.time()

    def setsource(self, source, coord, vel, freq):
        self.write("RM:acc1:RM_SOURCE_C34", source)
        self.write("RM:acc1:RM_SVEL_KMPS_D", round(vel, 3))
        self.write("RM:acc1:RM_LOW_RX_LO_FREQUENCY_D", round(freq, 4))
        self.write("RM:acc1:RM_RA_CAT_HOURS_D", round(coord.ra.hour, 5))
        self.write("RM:acc1:RM_DEC_CAT_DEG_D", round(coord.dec.degree, 5))

    def tick(self):
        timeincr = 0.003
        self._ut += timeincr
        self._lst += timeincr

    def time(self):
        self.tick()
        self.write("RM:acc1:RM_LST_HOURS_F", round(self._lst, 5))
        self.write("RM:acc1:RM_UTC_HR_D", round(self._ut, 5))

    def slew(self, az, el):
        alltrack = False
        elerr = np.full(8, 999.0)
        azerr = np.full(8, 999.0)
        okdiff = 0.2  # arcsec
        while not alltrack:
            time.sleep(1)
            self.time()
            for i in range(1, 9):
                if np.abs(elerr[i - 1]) < okdiff and np.abs(azerr[i - 1]) < okdiff:
                    continue
                azstart = self.read(f"RM:acc{i}:RM_TRACK_AZ_F")
                elstart = self.read(f"RM:acc{i}:RM_TRACK_EL_F")
                azdiff = az - azstart
                azstep = azdiff / 5.0  # rate of slew proportional to difference
                if np.abs(azstep) < 1:  # avoid zeno
                    azstep = azdiff
                azgo = azstart + azstep
                eldiff = el - elstart
                elstep = eldiff / 5.0
                if np.abs(elstep) < 1:
                    elstep = eldiff
                elgo = elstart + elstep
                elerr[i - 1] = (el - elgo) * 3600.0
                azerr[i - 1] = (az - azgo) * 3600.0
                ja = self.jitter
                je = self.jitter
                azgo -= ja
                azerr[i - 1] += ja
                elgo -= je
                elerr[i - 1] += je
                self.write(f"RM:acc{i}:RM_TRACK_AZ_F", round(azgo, 4))
                self.write(f"RM:acc{i}:RM_TRACK_EL_F", round(elgo, 4))
                self.write(f"RM:acc{i}:RM_AZ_TRACKING_ERROR_F", round(azerr[i - 1], 2))
                self.write(f"RM:acc{i}:RM_EL_TRACKING_ERROR_F", round(elerr[i - 1], 2))
            alltrack = np.all(np.abs(elerr) < okdiff) and np.all(np.abs(azerr) < okdiff)

    @property
    def jitter(self):
        return random.uniform(-0.2, 0.2)

    def tsys(self, init=False):
        for i in range(1, 9):
            name = f"RM:acc{i}:RM_TSYS_D"
            if init:
                value = random.uniform(90, 250)
            else:
                value = self.read(name) + random.uniform(-11, 12)
            self.write(name, round(value, 2))
            self.write(f"RM:acc{i}:RM_GUNN1_LOCKED_S", True)

    def weather(self, init=False):
        if not init:
            self._tamb = self.read("RM:acc1:RM_WEATHER_TEMP_F")
            self._rh = self.read("RM:acc1:RM_WEATHER_HUMIDITY_F")
            self._vwind = self.read("RM:acc1:RM_WEATHER_WINDSPEED_F")
            self._winddir = self.read("RM:acc1:RM_WEATHER_WINDDIR_F")
            self._patm = self.read("RM:acc1:RM_WEATHER_MBAR_F")
            self._tamb += random.uniform(-1, 1)
            self._rh += random.uniform(-2, 2)
            self._vwind += random.uniform(-0.5, 1)
            self._winddir += random.uniform(-3, 3)
            self._patm += random.uniform(-3, 3)

        self.write("RM:acc1:RM_WEATHER_TEMP_F", np.round(self._tamb, 3))
        self.write("RM:acc1:RM_WEATHER_HUMIDITY_F", np.round(self._rh, 1))
        self.write("RM:acc1:RM_WEATHER_WINDSPEED_F", np.round(self._vwind, 2))
        self.write("RM:acc1:RM_WEATHER_WINDDIR_F", np.round(self._winddir, 2))
        self.write("RM:acc1:RM_WEATHER_MBAR_F", np.round(self._patm, 2))

    def mixerH(self):
       points = {
           "antenna:{ant}:receiver:H:lo_plate:mixer:1:109_control": np.array([1,2]),
           "antenna:{ant}:receiver:H:lo_plate:mixer:1:109_source": np.array([1,2]),
           "antenna:{ant}:receiver:H:lo_plate:mixer:1:attenuator": np.arange(0,4095),
           "antenna:{ant}:receiver:H:lo_plate:mixer:1:attenuator_control":np.arange(0,4095),
           "antenna:{ant}:receiver:H:lo_plate:mixer:1:frequency":  np.array([180.,220.,350.,410.]),
           "antenna:{ant}:receiver:H:lo_plate:mixer:1:frequency_set": np.array([180.,220.,350.,410.]),
       }
       for p in points:
           for ant in range(1,9):
               mp = f"{p.format(ant=ant)}"
               value = random.choice(points[p])
               if "freq" in p:
                  self.write(mp, value)
               else:
                  self.write(mp, int(value))
            

    def oops(self):
        for i in range(1, 9):
            v = random.random()
            if v < 0.05:
                self.write(f"RM:acc{i}:RM_GUNN1_LOCKED_S", False)
            else:
                self.write(f"RM:acc{i}:RM_GUNN1_LOCKED_S", True)

            v = random.random()
            if v > 0.9:
                self.write(f"RM:acc{i}:RM_TSYS_D", round(random.uniform(500, 1500), 2))
            else:
                self.write(f"RM:acc{i}:RM_TSYS_D", round(random.uniform(90, 250), 2))

            v = random.random()
            if v > 0.96:
                self.write(f"RM:acc{i}:RM_ACTIVE_LOW_RECEIVER_C10", "garbage")
            else:
                self.write(
                    f"RM:acc{i}:RM_ACTIVE_LOW_RECEIVER_C10",
                    random.choice(["A1", "B1", "C", "E"]),
                )


if __name__ == "__main__":
    fo = FakeObs()
    #fo.observe("3c279")
    fo.mixerH()
