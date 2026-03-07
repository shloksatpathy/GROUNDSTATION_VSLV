from PyQt5 import QtWidgets
from PyQt5.QtWebEngineWidgets import QWebEngineView
import pyqtgraph as pg
import folium
import io
from core.serial_manager import SerialManager
from core.plots import PlotManager
from user_interface.packet_editor import PacketEditor
from PyQt5.QtCore import QTimer

class Dashboard(QtWidgets.QMainWindow):

    def __init__(self):
        super().__init__()

        
        self.time_data = []
        self.alt_data = []
        self.pres_data = []
        self.temp_data = []

        self.roll_data = []
        self.pitch_data = []
        self.yaw_data = []
        self.vspeed_data = []


        self.serial = SerialManager()
        self.plot_manager = PlotManager()
        self.packet_editor = PacketEditor()


        self.setWindowTitle("CANSAT Ground Station v2")
        self.resize(1500, 900)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        self.grid = QtWidgets.QGridLayout()
        central.setLayout(self.grid)

        self.create_header()
        self.create_plots()
        self.create_map()
        self.create_table()
        self.refresh_ports()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_loop)
        self.timer.start(100)   # runs every 100 ms

    # ---------------- HEADER ----------------

    def create_header(self):

        layout = QtWidgets.QHBoxLayout()

        title = QtWidgets.QLabel("CANSAT Ground Station")
        title.setStyleSheet("font-size:22px; font-weight:bold")

        self.port_combo = QtWidgets.QComboBox()
        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.connect_btn = QtWidgets.QPushButton("Connect")
        self.packet_btn = QtWidgets.QPushButton("Packet format")


        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(self.port_combo)
        layout.addWidget(self.refresh_btn)
        layout.addWidget(self.connect_btn)
        layout.addWidget(self.packet_btn)

        wrapper = QtWidgets.QWidget()
        wrapper.setLayout(layout)

        self.grid.addWidget(wrapper, 0, 0, 1, 3)

        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.connect_btn.clicked.connect(self.connect_serial)
        self.packet_btn.clicked.connect(self.open_packet_editor)
    # ---------------- SERIAL ----------------

    def refresh_ports(self):

        self.port_combo.clear()

        ports = self.serial.get_available_ports()

        for p in ports:
            self.port_combo.addItem(p)

    def connect_serial(self):

        port = self.port_combo.currentText()

        if port:
            self.serial.connect(port)
    #-----------------Packet Editor----------

    def open_packet_editor(self):
        self.editor = PacketEditor()
        self.editor.show()


    # ---------------- PLOTS ----------------
    def create_plots(self):

        plots = self.plot_manager.widgets()

        self.grid.addWidget(plots["alt"], 1, 0)
        self.grid.addWidget(plots["pres"], 1, 1)
        self.grid.addWidget(plots["temp"], 1, 2)

        self.grid.addWidget(plots["roll"], 2, 0)
        self.grid.addWidget(plots["pitch"], 2, 1)
        self.grid.addWidget(plots["yaw"], 2, 2)

        self.grid.addWidget(plots["vspeed"], 3, 0, 1, 3)
    """def create_plots(self):

        pg.setConfigOption("background", "k")
        pg.setConfigOption("foreground", "w")

        self.alt_plot = pg.PlotWidget(title="Altitude")
        self.press_plot = pg.PlotWidget(title="Pressure")
        self.temp_plot = pg.PlotWidget(title="Temperature")

        self.roll_plot = pg.PlotWidget(title="Roll")
        self.pitch_plot = pg.PlotWidget(title="Pitch")
        self.yaw_plot = pg.PlotWidget(title="Yaw")

        self.grid.addWidget(self.alt_plot, 1, 0)
        self.grid.addWidget(self.press_plot, 1, 1)
        self.grid.addWidget(self.temp_plot, 1, 2)

        self.grid.addWidget(self.roll_plot, 2, 0)
        self.grid.addWidget(self.pitch_plot, 2, 1)
        self.grid.addWidget(self.yaw_plot, 2, 2)

        # plot curves
        self.alt_curve = self.alt_plot.plot(pen="y")
        self.press_curve = self.press_plot.plot(pen="c")
        self.temp_curve = self.temp_plot.plot(pen="g")

        self.roll_curve = self.roll_plot.plot(pen="r")
        self.pitch_curve = self.pitch_plot.plot(pen="m")
        self.yaw_curve = self.yaw_plot.plot(pen="b")

        # fixed ranges for orientation
        self.roll_plot.setYRange(-180, 180)
        self.pitch_plot.setYRange(-90, 90)
        self.yaw_plot.setYRange(-180, 180)
"""
    # ---------------- MAP ----------------

    def create_map(self):

        self.map_view = QWebEngineView()

        m = folium.Map(
                location=[26.7,84.3],
                zoom_start=14,
                tiles="CartoDB dark_matter"
            )
        data = io.BytesIO()
        m.save(data, close_file=False)

        self.map_view.setHtml(data.getvalue().decode())

        self.grid.addWidget(self.map_view, 3, 0, 1, 3)

    # ---------------- TABLE ----------------

    def create_table(self):

        self.table = QtWidgets.QTableWidget()

        self.table.setColumnCount(0)
        self.table.setRowCount(0)

        self.grid.addWidget(self.table, 4, 0, 1, 3)



    #---------------update loop-----------------

    def update_loop(self):

        line = self.serial.read_line()

        if not line:
            return

        print("RX:", line)

        parts = line.split(",")

        if len(parts) < 8:
            print("Incomplete packet:", parts)
            return

        t = float(parts[1])
        alt = float(parts[2])
        pres = float(parts[3])
        temp = float(parts[4])
        roll = float(parts[5])
        pitch = float(parts[6])
        yaw = float(parts[7])

        self.time_data.append(t)
        self.alt_data.append(alt)
        self.pres_data.append(pres)
        self.temp_data.append(temp)

        self.roll_data.append(roll)
        self.pitch_data.append(pitch)
        self.yaw_data.append(yaw)
        self.vspeed_data.append(0)

        MAX_POINTS = 200

        if len(self.time_data) > MAX_POINTS:
            self.time_data.pop(0)
            self.alt_data.pop(0)
            self.pres_data.pop(0)
            self.temp_data.pop(0)
            self.roll_data.pop(0)
            self.pitch_data.pop(0)
            self.yaw_data.pop(0)
            self.vspeed_data.pop(0)
        try:

            data = {
                "time": self.time_data,
                "altitude": self.alt_data,
                "pressure": self.pres_data,
                "temperature": self.temp_data,
                "roll": self.roll_data,
                "pitch": self.pitch_data,
                "yaw": self.yaw_data,
                "vspeed": self.vspeed_data
            }

            self.plot_manager.update(data)

        except Exception as e:
            print("Parse error:", e)