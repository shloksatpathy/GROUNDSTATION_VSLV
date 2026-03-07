import serial
import serial.tools.list_ports


class SerialManager:

    def __init__(self, baudrate=9600):
        self.baudrate = baudrate
        self.ser = None

    def get_available_ports(self):

        ports = []

        for port in serial.tools.list_ports.comports():
            ports.append(port.device)

        return ports


    def connect(self, port):

        try:
            self.ser = serial.Serial(port, self.baudrate, timeout=0.1)
            print("Connected to", port)

        except Exception as e:
            print("Connection failed:", e)


    def disconnect(self):

        if self.ser and self.ser.is_open:
            self.ser.close()
            print("Serial disconnected")


    def read_line(self):

        if not self.ser:
            return None

        if self.ser.in_waiting:
            return self.ser.readline().decode("utf-8", errors="ignore").strip()

        return None