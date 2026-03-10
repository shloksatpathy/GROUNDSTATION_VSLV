import serial
import serial.tools.list_ports

class SerialManager:
    def __init__(self, baudrate=9600):
        self.baudrate = baudrate
        self.ser = None

    def available_ports(self):
        return [p.device for p in serial.tools.list_ports.comports()]

    def connect(self, port):
        self.ser = serial.Serial(port, self.baudrate, timeout=0.02)

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    def read_line(self):
        if not self.ser:
            return None
        if self.ser.in_waiting:
            return self.ser.readline().decode("utf-8", errors="ignore").strip()
        return None