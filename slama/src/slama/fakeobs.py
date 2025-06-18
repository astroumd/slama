#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jun 18 08:30:04 2025

@author: mpound
"""

import random
from slama.monitor import (
    # MonitorPoint,
    # MonitorPointSubscriber,
    MonitorPointList,
    MonitorListUpdater,
    # Validity,
)
from smax import SmaxRedisClient
from pathlib import Path
from astropy.coordinates import SkyCoord
import astropy.units as u
import time
import numpy as np


class FakeObs:
    def __init__(self):
        self._smax_client = SmaxRedisClient("localhost", redis_port=6380)
        self._path = Path("mpdefs.json")
        self._mpl = MonitorPointList.from_file(self._path)
        self._mlu = MonitorListUpdater(self._mpl, self._smax_client)
        self._mlu.update()
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

    def observe(self):
        self._source = "ORIMSR"
        self._vel = 5.0
        self._freq = 230.538
        self._coord = SkyCoord("5:35:14.5 -05:22:30.5", frame="icrs", unit=(u.hr, u.deg))
        self.setsource(self._source, self._coord, self._vel, self._freq)
        az = 95
        el = 30
        azincr = 0.004
        elincr = 0.003
        timeincr = 0.003
        self.slew(az, el)
        i = 0
        if True:
            while i < 10:
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
        self._smax_client.smax_share("RM:acc1", "RM_SOURCE_C34", source)
        self._smax_client.smax_share("RM:acc1", "RM_SVEL_KMPS_D", round(vel, 3))
        self._smax_client.smax_share("RM:acc1", "RM_LOW_RX_LO_FREQUENCY_D", round(freq, 4))
        self._smax_client.smax_share("RM:acc1", "RM_RA_CAT_HOURS_D", round(coord.ra.hour, 5))
        self._smax_client.smax_share("RM:acc1", "RM_DEC_CAT_DEG_D", round(coord.dec.degree, 5))

    def tick(self):
        timeincr = 0.003
        self._ut += timeincr
        self._lst += timeincr

    def time(
        self,
    ):
        self.tick()
        self._smax_client.smax_share("RM:acc1", "RM_LST_HOURS_F", round(self._lst, 5))
        self._smax_client.smax_share("RM:acc1", "RM_UTC_HR_D", round(self._ut, 5))

    def slew(self, az, el):
        alltrack = False
        elerr = np.full(8, 999.0)
        azerr = np.full(8, 999.0)
        okdiff = 0.2  # arcsec
        while not alltrack:
            time.sleep(1)
            self.time()
            for i in range(1, 9):
                s = f"RM:acc{i}"
                if np.abs(elerr[i - 1]) < okdiff and np.abs(azerr[i - 1]) < okdiff:
                    # print(f"Antenna {i} is tracking")
                    continue
                azstart = self._smax_client.smax_pull(s, "RM_TRACK_AZ_F")
                elstart = self._smax_client.smax_pull(s, "RM_TRACK_EL_F")
                azdiff = az - azstart
                azstep = azdiff / 5.0  # rate of slew proportional to difference!
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
                if False:
                    print(
                        f"{i} {az=} {azgo=} {azstep=} {azerr[i-1]=} {el=} {elgo=} {elstep=} {elerr[i-1]=}"
                    )
                ja = self.jitter
                je = self.jitter
                azgo -= ja
                azerr[i - 1] += ja
                elgo -= je
                elerr[i - 1] += je
                self._smax_client.smax_share(s, "RM_TRACK_AZ_F", round(azgo, 4))
                self._smax_client.smax_share(s, "RM_TRACK_EL_F", round(elgo, 4))
                self._smax_client.smax_share(s, "RM_AZ_TRACKING_ERROR_F", round(azerr[i - 1], 2))
                self._smax_client.smax_share(s, "RM_EL_TRACKING_ERROR_F", round(elerr[i - 1], 2))
            alltrack = np.all(np.abs(elerr) < okdiff) and np.all(np.abs(azerr) < okdiff)

    @property
    def jitter(self):
        return random.uniform(-0.2, 0.2)

    def tsys(self, init=False):
        for i in range(1, 9):
            s = f"RM:acc{i}"
            if init:
                value = random.uniform(90, 250)
            else:
                value = self._smax_client.smax_pull(s, "RM_TSYS_D").asdict()[
                    "data"
                ] + random.uniform(-11, 12)
            self._smax_client.smax_share(s, "RM_TSYS_D", round(value, 2))
            self._smax_client.smax_share(s, "RM_GUNN1_LOCKED_S", True)

    def weather(self, init=False):
        if not init:
            self._tamb = self._smax_client.smax_pull("RM:acc1", "RM_WEATHER_TEMP_F").asdict()[
                "data"
            ]
            self._rh = self._smax_client.smax_pull("RM:acc1", "RM_WEATHER_HUMIDITY_F").asdict()[
                "data"
            ]
            self._vwind = self._smax_client.smax_pull("RM:acc1", "RM_WEATHER_WINDSPEED_F").asdict()[
                "data"
            ]
            self._winddir = self._smax_client.smax_pull("RM:acc1", "RM_WEATHER_WINDDIR_F").asdict()[
                "data"
            ]
            self._patm = self._smax_client.smax_pull("RM:acc1", "RM_WEATHER_MBAR_F").asdict()[
                "data"
            ]
            self._tamb += random.uniform(-1, 1)
            self._rh += random.uniform(-2, 2)
            self._vwind += random.uniform(-0.5, 1)
            self._winddir += random.uniform(-3, 3)
            self._patm += random.uniform(-3, 3)

        self._smax_client.smax_share("RM:acc1", "RM_WEATHER_TEMP_F", np.round(self._tamb, 3))
        self._smax_client.smax_share("RM:acc1", "RM_WEATHER_HUMIDITY_F", np.round(self._rh, 1))
        self._smax_client.smax_share("RM:acc1", "RM_WEATHER_WINDSPEED_F", np.round(self._vwind, 2))
        self._smax_client.smax_share("RM:acc1", "RM_WEATHER_WINDDIR_F", np.round(self._winddir, 2))
        self._smax_client.smax_share("RM:acc1", "RM_WEATHER_MBAR_F", np.round(self._patm, 2))

    def oops(self):
        for i in range(1, 9):
            v = random.random()
            s = f"RM:acc{i}"
            # print(v)
            if v < 0.05:
                self._smax_client.smax_share(s, "RM_GUNN1_LOCKED_S", False)
            else:
                self._smax_client.smax_share(s, "RM_GUNN1_LOCKED_S", True)

            v = random.random()
            if v > 0.9:
                self._smax_client.smax_share(s, "RM_TSYS_D", round(random.uniform(500, 1500), 2))
            else:
                self._smax_client.smax_share(s, "RM_TSYS_D", round(random.uniform(90, 250), 2))

            v = random.random()
            if v > 0.95:
                self._smax_client.smax_share(s, "RM_ACTIVE_LOW_RECEIVER_C10", "garbage")
            else:
                self._smax_client.smax_share(
                    s, "RM_ACTIVE_LOW_RECEIVER_C10", random.choice(["A1", "B1", "C", "E"])
                )
