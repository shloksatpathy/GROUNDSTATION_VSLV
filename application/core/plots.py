import pyqtgraph as pg
from PyQt5 import QtWidgets
from PyQt5.QtGui import QColor

class PlotManager:

    def __init__(self):

        pg.setConfigOption("background", "k")
        pg.setConfigOption("foreground", "w")
        
        # --- Create plots ---
        self.plot_alt = pg.PlotWidget(title="Altitude (m)")
        self.plot_pres = pg.PlotWidget(title="Pressure (Pa)")
        self.plot_temp = pg.PlotWidget(title="Temperature (C)")

        self.plot_roll = pg.PlotWidget(title="Roll (deg)")
        self.plot_pitch = pg.PlotWidget(title="Pitch (deg)")
        self.plot_yaw = pg.PlotWidget(title="Yaw (deg)")

        self.plot_vspeed = pg.PlotWidget(title="Vertical Speed (m/s)")

        # --- Curves ---
        self.cur_alt = self.plot_alt.plot(pen=pg.mkPen(QColor(0,120,215), width=2))
        self.cur_pres = self.plot_pres.plot(pen=pg.mkPen(QColor(255,165,0), width=2))
        self.cur_temp = self.plot_temp.plot(pen=pg.mkPen(QColor(0,200,0), width=2))

        self.cur_roll = self.plot_roll.plot(pen=pg.mkPen(QColor(220,20,60), width=2))
        self.cur_pitch = self.plot_pitch.plot(pen=pg.mkPen(QColor(199,21,133), width=2))
        self.cur_yaw = self.plot_yaw.plot(pen=pg.mkPen(QColor(0,206,209), width=2))

        self.cur_vspeed = self.plot_vspeed.plot(pen=pg.mkPen(QColor(255,100,50), width=2))

        # Enable grids
        for p in [
            self.plot_alt, self.plot_pres, self.plot_temp,
            self.plot_roll, self.plot_pitch, self.plot_yaw,
            self.plot_vspeed
        ]:
            p.showGrid(x=True, y=True, alpha=0.3)

        # Fix attitude ranges
        self.plot_roll.setYRange(-180, 180)
        self.plot_pitch.setYRange(-90, 90)
        self.plot_yaw.setYRange(-180, 180)

    def widgets(self):
        return {
            "alt": self.plot_alt,
            "pres": self.plot_pres,
            "temp": self.plot_temp,
            "roll": self.plot_roll,
            "pitch": self.plot_pitch,
            "yaw": self.plot_yaw,
            "vspeed": self.plot_vspeed
        }

    def update(self, data):

        t = data["time"]

        self.cur_alt.setData(t, data["altitude"])
        self.cur_pres.setData(t, data["pressure"])
        self.cur_temp.setData(t, data["temperature"])

        self.cur_roll.setData(t, data["roll"])
        self.cur_pitch.setData(t, data["pitch"])
        self.cur_yaw.setData(t, data["yaw"])

        self.cur_vspeed.setData(t, data["vspeed"])