# slama plotting
from .monitor import MonitorPointUpdater
import matplotlib.pyplot as plt
import astropy.units as u
from time import sleep
import numpy as np

class MonitorPointPlot():
    def __init__(self,mpu:MonitorPointUpdater,interval=1, loop=None):
        self._mpu = mpu
        self.mp = self._mpu.mp
        self._interval = interval
        self._loop = loop
        self._mpu.update()
        self._init_plot()
        self.run()

    def _init_plot(self):
        plt.ion()
        self._x = list(np.arange(0,10))
        self._y = [0]*len(self._x)
        self._figure = plt.figure()
        self._ax = self._figure.add_subplot(111)
        lines = self._ax.plot(self._x,self._y,'b-')
        self._line = lines[0]
        self._ax.set_ylim(-10,10)
        self._ax.set_xlim(0,10)
        title = f"{self.mp.name} ({self.mp.canonical_name})"
        self._ax.set_title(title)
        self._ax.set_xlabel("delta time (seconds)")
        self._ax.set_ylabel(f"value ({self.mp.units})")

    def _update_mp(self):
        self._mpu.update()

    def _update_plot(self):
        self._update_mp()
        self._y.append(self.mp.value)
        print(f"{len(self._y)=}")
        self._line.set_ydata(self._y)
        self._x = np.arange(0,len(self._y))
        self._line.set_xdata(self._x)
        print(f"{len(self._x)=}, {len(self._y)=}")
        #if (len(self._x)>10):
        self._ax.set_xlim(0,self._x.max())
        #if (len(self._y)>10):
        self._ax.set_ylim(1.5*np.min(self._y),1.5*np.max(self._y),auto=True)
        self._figure.canvas.draw()
        self._figure.canvas.flush_events()

    def run(self):
        if self._loop is None:
            while(True):
                self._update_plot()
                sleep(self._interval)
        else:
            for i in range(loop):
                self._update_plot()
                sleep(interval)

