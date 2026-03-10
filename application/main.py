import sys
from PyQt5 import QtWidgets
from core.serial_manager import SerialManager
from core.kalman_filter import AltitudeKalman
from core.telemetry_processor import TelemetryProcessor
from user_interface.dashboard import Dashboard

app = QtWidgets.QApplication(sys.argv)

serial_manager = SerialManager(9600)
port = serial_manager.available_ports()
print(port)
serial_manager.connect('COM3') 
kalman = AltitudeKalman()
processor = TelemetryProcessor(kalman)

window = Dashboard(serial_manager, processor)
window.show()

sys.exit(app.exec_())
