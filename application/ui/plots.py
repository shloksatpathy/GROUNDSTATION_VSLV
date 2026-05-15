import pyqtgraph as pg
from PyQt5.QtGui import QColor


class PlotManager:

    def __init__(self):

        # ----- Global Plot Style -----
        pg.setConfigOption("background", "#121212")
        pg.setConfigOption("foreground", "w")

        # ----- Create Plot Widgets -----
        self.plot_alt = pg.PlotWidget(title="Altitude vs Time")
        self.plot_pres = pg.PlotWidget(title="Pressure vs Time")
        self.plot_temp = pg.PlotWidget(title="Temperature vs Time")

        self.plot_roll = pg.PlotWidget(title="Roll vs Time")
        self.plot_pitch = pg.PlotWidget(title="Pitch vs Time")
        self.plot_yaw = pg.PlotWidget(title="Yaw vs Time")

        self.plot_vspeed = pg.PlotWidget(title="Vertical Speed")

        # ----- Plot Lines -----
        self.cur_alt = self.plot_alt.plot(
            pen=pg.mkPen(QColor(0, 120, 215), width=2)
        )

        self.cur_pres = self.plot_pres.plot(
            pen=pg.mkPen(QColor(255, 165, 0), width=2)
        )

        self.cur_temp = self.plot_temp.plot(
            pen=pg.mkPen(QColor(0, 200, 0), width=2)
        )

        self.cur_roll = self.plot_roll.plot(
            pen=pg.mkPen(QColor(220, 20, 60), width=2)
        )

        self.cur_pitch = self.plot_pitch.plot(
            pen=pg.mkPen(QColor(199, 21, 133), width=2)
        )

        self.cur_yaw = self.plot_yaw.plot(
            pen=pg.mkPen(QColor(0, 206, 209), width=2)
        )

        self.cur_vspeed = self.plot_vspeed.plot(
            pen=pg.mkPen(QColor(255, 100, 50), width=2)
        )

        # ----- Enable Grid -----
        plots = [
            self.plot_alt,
            self.plot_pres,
            self.plot_temp,
            self.plot_roll,
            self.plot_pitch,
            self.plot_yaw,
            self.plot_vspeed,
        ]

        for p in plots:
            p.showGrid(x=True, y=True, alpha=0.3)

        # ----- Fix Attitude Scale -----
        self.plot_roll.setYRange(-180, 180)
        self.plot_pitch.setYRange(-90, 90)
        self.plot_yaw.setYRange(-180, 180)

        # ----- Buffer Limit -----
        self.max_points = 200

    # -------------------------------
    # Return Plot Widgets
    # -------------------------------
    def widgets(self):

        return {
            "alt": self.plot_alt,
            "pres": self.plot_pres,
            "temp": self.plot_temp,
            "roll": self.plot_roll,
            "pitch": self.plot_pitch,
            "yaw": self.plot_yaw,
            "vspeed": self.plot_vspeed,
        }

    # -------------------------------
    # Update Plots
    # -------------------------------
    def update(self, data):

        if not data:
            return

        t = data.get("time", [])

        if not t:
            return

        alt = data.get("altitude", [])
        pres = data.get("pressure", [])
        temp = data.get("temperature", [])

        roll = data.get("roll", [])
        pitch = data.get("pitch", [])
        yaw = data.get("yaw", [])

        vspeed = data.get("vspeed", [])

        # Limit buffer size
        t = t[-self.max_points:]

        alt = alt[-self.max_points:]
        pres = pres[-self.max_points:]
        temp = temp[-self.max_points:]

        roll = roll[-self.max_points:]
        pitch = pitch[-self.max_points:]
        yaw = yaw[-self.max_points:]

        vspeed = vspeed[-self.max_points:]

        # Replace None with 0 to prevent pyqtgraph crash
        def safe(lst):
            return [v if v is not None else 0 for v in lst]

        # Update lines
        self.cur_alt.setData(t, safe(alt))
        self.cur_pres.setData(t, safe(pres))
        self.cur_temp.setData(t, safe(temp))

        self.cur_roll.setData(t, safe(roll))
        self.cur_pitch.setData(t, safe(pitch))
        self.cur_yaw.setData(t, safe(yaw))

        self.cur_vspeed.setData(t, safe(vspeed))

    # -------------------------------
    # Clear Plots
    # -------------------------------
    def clear(self):

        self.cur_alt.clear()
        self.cur_pres.clear()
        self.cur_temp.clear()

        self.cur_roll.clear()
        self.cur_pitch.clear()
        self.cur_yaw.clear()

        self.cur_vspeed.clear()