from PyQt5 import QtWidgets
import pyqtgraph as pg
import time

class Dashboard(QtWidgets.QMainWindow):
    def __init__(self, serial_manager, processor):
        super().__init__()
        self.serial = serial_manager
        self.processor = processor

        self.setWindowTitle("Primary Ground Station v2.0")
        self.resize(1200, 800)

        self.plot = pg.PlotWidget(title="Filtered Altitude")
        self.curve = self.plot.plot(pen='y')

        self.setCentralWidget(self.plot)

        self.times = []
        self.alts = []

        self.timer = pg.QtCore.QTimer()
        self.timer.timeout.connect(self.update_loop)
        self.timer.start(50)

    def update_loop(self):
        line = self.serial.read_line()
        if not line:
            return

        try:
            raw_alt = float(line)
            t = time.time()

            filt_alt, vel = self.processor.process(raw_alt, t)

            self.times.append(t)
            self.alts.append(filt_alt)

            self.curve.setData(self.times, self.alts)

        except:
            pass
