import serial
import serial.tools.list_ports
from PyQt5.QtCore import QThread, pyqtSignal, QObject
from core.config import load_config


class SerialReaderThread(QThread):
    """Background thread to read serial lines without blocking the UI."""
    line_received = pyqtSignal(str)
    
    def __init__(self, ser):
        super().__init__()
        self.ser = ser
        self.running = False
        
    def run(self):
        self.running = True
        while self.running and self.ser and self.ser.is_open:
            try:
                # Only block/read if there is data waiting
                if self.ser.in_waiting > 0:
                    line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                    if line:
                        self.line_received.emit(line)
                else:
                    self.msleep(5)  # Yield to avoid 100% CPU usage
            except Exception:
                self.msleep(5)

    def stop(self):
        """Signal thread to stop and wait for it."""
        self.running = False
        self.wait()


class SerialManager(QObject):
    """Manages the serial port connection and reading thread."""
    line_received = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        cfg = load_config()
        self.baudrate = cfg.get("baud_rate", 9600)
        self.ser = None
        self.thread = None

    def available_ports(self):
        """Return list of available COM ports."""
        return [p.device for p in serial.tools.list_ports.comports()]

    def connect(self, port, baudrate=None):
        """Connect to port and start the reader thread."""
        if baudrate is not None:
            self.baudrate = baudrate
            
        # Ensure clean state before connecting
        self.disconnect()
        
        self.ser = serial.Serial(port, self.baudrate, timeout=0.02)
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass
            
        # Start background reader thread
        self.thread = SerialReaderThread(self.ser)
        # Forward thread's signal to manager's signal
        self.thread.line_received.connect(self.line_received.emit)
        self.thread.start()

    def disconnect(self):
        """Stop thread and close port."""
        if self.thread:
            self.thread.stop()
            self.thread = None
            
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def write(self, data):
        """Write raw bytes to serial port."""
        if self.ser and self.ser.is_open:
            self.ser.write(data)
