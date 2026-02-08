# app_resilient.py
"""
Resilient Groundstation example:
- Avoids permanent port-hold when worker hangs on write by:
  * using write_timeout on serial port
  * starting a GUI watchdog timer on each send
  * forcibly closing and cleaning the worker if the watchdog fires
- Minimal feature set to match your previous layout (buttons, manual send, line endings).
"""
import sys, os, io, datetime
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot, QObject, QThread
from PyQt5.QtWebEngineWidgets import QWebEngineView
import pyqtgraph as pg
import folium
import pandas as pd
import serial, serial.tools.list_ports

CSV_PATH = "Flight_2024ASI-CANSAT0032.csv"
TEAM_ID = "2024ASI-CANSAT0032"
DEFAULT_BAUD = 115200
WINDOW_SEC = 10

def now():
    return datetime.datetime.now()

class SerialWorker(QObject):
    line_received = pyqtSignal(str)
    connected = pyqtSignal(str)
    disconnected = pyqtSignal()
    error = pyqtSignal(str)
    write_finished = pyqtSignal()

    def __init__(self, write_timeout=1.0, post_write_delay_ms=50):
        super().__init__()
        self.ser = None
        self.port = None
        self.baud = None
        self._running = False
        self.paused = False
        self.write_timeout = float(write_timeout)
        self.post_write_delay_ms = int(post_write_delay_ms)

    @pyqtSlot()
    def open(self):
        if not self.port:
            self.error.emit("No port specified")
            self.disconnected.emit()
            return
        try:
            # open with write_timeout so write won't block indefinitely
            self.ser = serial.Serial(self.port, self.baud, timeout=0.12, write_timeout=self.write_timeout)
            self._running = True
            self.connected.emit(f"{self.port}@{self.baud}")
        except Exception as e:
            self.error.emit(f"Open error: {repr(e)}")
            self._running = False
            self.disconnected.emit()
            return

        try:
            while self._running and self.ser and self.ser.is_open:
                if self.paused:
                    QtCore.QThread.msleep(6)
                    continue
                try:
                    raw = self.ser.readline()
                except Exception as e:
                    self.error.emit(f"Read error: {repr(e)}")
                    QtCore.QThread.msleep(50)
                    continue
                if not raw:
                    continue
                try:
                    line = raw.decode('utf-8', errors='ignore').strip()
                except:
                    line = raw.decode('latin-1', errors='ignore').strip()
                self.line_received.emit(line)
        except Exception as e:
            # guard: ensure worker crashes are reported
            try:
                self.error.emit(f"Worker main loop exception: {repr(e)}")
            except:
                pass
        finally:
            # attempt to close serial if open
            try:
                if self.ser and self.ser.is_open:
                    try: self.ser.close()
                    except: pass
            except: pass
            self._running = False
            self.disconnected.emit()

    @pyqtSlot()
    def close(self):
        # mark stopped; closing port will unblock reads/writes
        self._running = False
        try:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                except Exception as e:
                    self.error.emit(f"Close exception: {repr(e)}")
        except Exception:
            pass
        # ensure signal
        self.disconnected.emit()

    @pyqtSlot(str)
    def write_with_pause(self, text):
        """Pause reader thread loop, write bytes, flush, sleep a bit, then resume. Always emit write_finished in finally."""
        try:
            self.paused = True
            if not self.ser or not getattr(self.ser, "is_open", False):
                self.error.emit("Write error: port not open")
                return
            outb = text.encode('utf-8') if isinstance(text, str) else bytes(text)
            try:
                # write will raise or respect write_timeout
                self.ser.write(outb)
                try:
                    self.ser.flush()
                except Exception:
                    # flush might not exist or can fail; ignore
                    pass
                if self.post_write_delay_ms > 0:
                    QtCore.QThread.msleep(self.post_write_delay_ms)
            except Exception as e:
                # write exception (timeouts, OS errors) reported
                self.error.emit(f"Write exception: {repr(e)}")
        except Exception as e:
            self.error.emit(f"write_with_pause top-level exception: {repr(e)}")
        finally:
            self.paused = False
            # always emit so GUI can reset
            try:
                self.write_finished.emit()
            except Exception:
                pass

class Groundstation(QtWidgets.QMainWindow):
    send_to_worker_with_pause = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Groundstation — Resilient")
        self.resize(1100, 700)

        # worker/thread
        self.worker = None
        self.serial_thread = None

        # state
        self.columns = ["TEAM_ID","TIME_SINCE_S","PACKET_COUNT","ALTITUDE_M","PRESSURE_PA","TEMP_C",
                        "VOLTAGE_V","GNSS_TIME","GNSS_LAT","GNSS_LON","GNSS_ALT_M","GNSS_SATS",
                        "ACCEL_X_MPS2","ACCEL_Y_MPS2","ACCEL_Z_MPS2","ROLL_DEG","PITCH_DEG",
                        "GYRO_SPIN_RATE_DPS","FLIGHT_STATE","OPTIONAL_DATA"]
        self.buffer = []
        self.packet_count = 0
        self.power_on_time = now()
        self.flight_state = "boot"
        self.recording = False

        # send state
        self.send_in_progress = False
        self.watchdog_ms = 2000  # if no write_finished in this ms, force-close worker

        self._build_ui()
        if not os.path.exists(CSV_PATH):
            pd.DataFrame(columns=self.columns).to_csv(CSV_PATH, index=False)

        # periodic UI tick
        self.timer = QtCore.QTimer(); self.timer.timeout.connect(self.tick); self.timer.start(80)

    def _build_ui(self):
        self.setStyleSheet("""
            QWidget { background:#121212; color:#E0E0E0; font-size:13px }
            QPushButton { background:#1E1E1E; padding:6px; border:1px solid #333 }
            QLineEdit { background:#1A1A1A; padding:6px }
        """)
        g = QtWidgets.QGridLayout()
        root = QtWidgets.QWidget(); root.setLayout(g)
        self.setCentralWidget(root)

        # top
        self.port_combo = QtWidgets.QComboBox()
        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.refresh_ports()
        self.baud_combo = QtWidgets.QComboBox(); self.baud_combo.addItems(["9600","19200","38400","57600","74880","115200","230400"])
        self.baud_combo.setCurrentText(str(DEFAULT_BAUD))
        self.connect_btn = QtWidgets.QPushButton("Connect"); self.connect_btn.clicked.connect(self.toggle_connection)
        self.lbl_conn = QtWidgets.QLabel("Not connected"); self.lbl_conn.setStyleSheet("color: orange")
        top_h = QtWidgets.QHBoxLayout()
        top_h.addWidget(QtWidgets.QLabel("Port:")); top_h.addWidget(self.port_combo); top_h.addWidget(self.refresh_btn)
        top_h.addWidget(QtWidgets.QLabel("Baud:")); top_h.addWidget(self.baud_combo); top_h.addWidget(self.connect_btn)
        top_h.addWidget(self.lbl_conn)
        top_wrap = QtWidgets.QWidget(); top_wrap.setLayout(top_h); g.addWidget(top_wrap, 0, 0, 1, 4)

        title = QtWidgets.QLabel(f"Team: {TEAM_ID} — Groundstation"); title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-weight:600; font-size:15px"); g.addWidget(title, 1, 0, 1, 4)

        # commands
        btn_h = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("SEND START"); self.btn_stop = QtWidgets.QPushButton("SEND STOP"); self.btn_reset = QtWidgets.QPushButton("SEND RESET")
        for b in (self.btn_start, self.btn_stop, self.btn_reset):
            b.setEnabled(False); btn_h.addWidget(b)
        self.btn_start.clicked.connect(lambda: self.send_command("START"))
        self.btn_stop.clicked.connect(lambda: self.send_command("STOP"))
        self.btn_reset.clicked.connect(lambda: self.send_command("RESET"))

        self.line_ending = QtWidgets.QComboBox(); self.line_ending.addItems(["No line ending","\\n (LF)","\\r (CR)","\\r\\n (CRLF)"]); self.line_ending.setCurrentIndex(1)
        self.cmd_input = QtWidgets.QLineEdit(); self.cmd_input.setPlaceholderText("Type command and press Send")
        self.cmd_send = QtWidgets.QPushButton("Send"); self.cmd_send.clicked.connect(lambda: self.send_command(None))
        self.cmd_input.returnPressed.connect(lambda: self.send_command(None))
        self.last_sent = QtWidgets.QLabel("Last sent: —")

        cmd_wrap = QtWidgets.QWidget(); cmd_layout = QtWidgets.QHBoxLayout()
        cmd_layout.addLayout(btn_h); cmd_layout.addWidget(QtWidgets.QLabel("Line ending:")); cmd_layout.addWidget(self.line_ending)
        cmd_layout.addWidget(self.cmd_input); cmd_layout.addWidget(self.cmd_send); cmd_layout.addWidget(self.last_sent)
        cmd_wrap.setLayout(cmd_layout); g.addWidget(cmd_wrap, 2, 0, 1, 4)

        # minimal stats
        self.record_start = QtWidgets.QPushButton("Start Recording"); self.record_stop = QtWidgets.QPushButton("Stop Recording")
        self.record_start.clicked.connect(self.start_recording); self.record_stop.clicked.connect(self.stop_recording)
        self.lbl_time = QtWidgets.QLabel("Time: 0s"); self.lbl_pkt = QtWidgets.QLabel("Packets: 0")
        stats = QtWidgets.QHBoxLayout(); stats.addWidget(self.record_start); stats.addWidget(self.record_stop); stats.addStretch(); stats.addWidget(self.lbl_time); stats.addWidget(self.lbl_pkt)
        sw = QtWidgets.QWidget(); sw.setLayout(stats); g.addWidget(sw, 3, 0, 1, 4)

        # plots placeholders (kept, minimal)
        pg.setConfigOption('background', 'k'); pg.setConfigOption('foreground', 'w')
        self.plot_alt = pg.PlotWidget(title="Altitude vs Time (m)"); self.plot_alt.setMinimumHeight(150); g.addWidget(self.plot_alt, 4, 0, 1, 2)
        self.plot_temp = pg.PlotWidget(title="Temp vs Time (C)"); self.plot_temp.setMinimumHeight(150); g.addWidget(self.plot_temp, 4, 2, 1, 2)

        # table
        self.table = QtWidgets.QTableWidget(); self.table.setColumnCount(len(self.columns)); self.table.setHorizontalHeaderLabels(self.columns)
        self.table.horizontalHeader().setStretchLastSection(True); self.table.setMinimumHeight(180); g.addWidget(self.table, 5, 0, 1, 4)

        # watchdog timer used per-send
        self.send_watchdog = QtCore.QTimer(); self.send_watchdog.setSingleShot(True); self.send_watchdog.timeout.connect(self._on_send_watchdog)

    def refresh_ports(self):
        self.port_combo.clear()
        for p in serial.tools.list_ports.comports():
            self.port_combo.addItem(p.device)

    def toggle_connection(self):
        if self.worker is not None:
            # attempt graceful stop
            self.stop_worker_and_wait(force=True)
            return
        port = self.port_combo.currentText()
        if not port:
            self.lbl_conn.setText("No port selected"); self.lbl_conn.setStyleSheet("color: red"); return
        try:
            baud = int(self.baud_combo.currentText())
        except:
            baud = DEFAULT_BAUD
        # quick open/close sanity
        try:
            tmp = serial.Serial(port, baud, timeout=0.1)
            tmp.close()
        except Exception as e:
            self.lbl_conn.setText(f"Open failed: {e}"); self.lbl_conn.setStyleSheet("color: red"); print("Port open test failed:", e); return
        self._start_worker(port, baud)

    def _start_worker(self, port, baud):
        if self.worker is not None:
            return
        self.serial_thread = QThread()
        self.worker = SerialWorker(write_timeout=1.0, post_write_delay_ms=60)
        self.worker.port = port; self.worker.baud = baud
        self.worker.moveToThread(self.serial_thread)
        self.serial_thread.started.connect(lambda: QtCore.QMetaObject.invokeMethod(self.worker, "open", QtCore.Qt.QueuedConnection))

        # connect worker signals
        self.worker.connected.connect(self._on_worker_connected)
        self.worker.disconnected.connect(self._on_worker_disconnected)
        self.worker.line_received.connect(self._on_line_received)
        self.worker.error.connect(self._on_worker_error)
        self.worker.write_finished.connect(self._on_worker_write_finished)

        # wire GUI -> worker write
        self.send_to_worker_with_pause.connect(self.worker.write_with_pause)

        # cleanup
        self.serial_thread.finished.connect(self._cleanup_worker)

        self.serial_thread.start()

    def stop_worker_and_wait(self, force=False):
        # attempt graceful close first
        if self.worker is None:
            return
        try:
            QtCore.QMetaObject.invokeMethod(self.worker, "close", QtCore.Qt.QueuedConnection)
        except Exception:
            pass
        # wait briefly
        if self.serial_thread:
            self.serial_thread.quit()
            self.serial_thread.wait(1500)
        # if still running and force requested, try to forcibly cleanup
        if getattr(self, 'serial_thread', None) and self.serial_thread.isRunning() and force:
            print("Force cleaning worker/thread")
            try:
                # best-effort: disconnect signals, then mark worker None; port will be released by OS on app exit
                try: self.send_to_worker_with_pause.disconnect()
                except: pass
                try: 
                    if self.worker:
                        self.worker._running = False
                except: pass
                try:
                    self.serial_thread.terminate()  # unsafe but used as last resort
                except Exception as e:
                    print("terminate failed:", e)
            except Exception:
                pass
            self.worker = None
            self.serial_thread = None

    def _cleanup_worker(self):
        try: self.send_to_worker_with_pause.disconnect()
        except: pass
        # disconnect worker signals
        try:
            if self.worker:
                try: self.worker.line_received.disconnect()
                except: pass
                try: self.worker.error.disconnect()
                except: pass
                try: self.worker.connected.disconnect()
                except: pass
                try: self.worker.disconnected.disconnect()
                except: pass
                try: self.worker.write_finished.disconnect()
                except: pass
        except: pass
        self.worker = None
        if getattr(self, 'serial_thread', None):
            try: self.serial_thread.quit(); self.serial_thread.wait(200)
            except: pass
            self.serial_thread = None

    # worker signal handlers
    @pyqtSlot(str)
    def _on_worker_connected(self, info):
        self.lbl_conn.setText("Connected: " + info); self.lbl_conn.setStyleSheet("color: lightgreen")
        self.connect_btn.setText("Disconnect")
        for b in (self.btn_start, self.btn_stop, self.btn_reset):
            b.setEnabled(True)
        self.cmd_send.setEnabled(True); self.cmd_input.setEnabled(True)

    @pyqtSlot()
    def _on_worker_disconnected(self):
        self.lbl_conn.setText("Disconnected"); self.lbl_conn.setStyleSheet("color: orange")
        self.connect_btn.setText("Connect")
        for b in (self.btn_start, self.btn_stop, self.btn_reset):
            b.setEnabled(False)
        self.cmd_send.setEnabled(False); self.cmd_input.setEnabled(False)
        # ensure any in-progress UI state resets
        self._reset_send_state()

    @pyqtSlot(str)
    def _on_worker_error(self, msg):
        print("Worker error:", msg)
        self.lbl_conn.setText("Error: " + str(msg))
        self.lbl_conn.setStyleSheet("color: red")

    @pyqtSlot()
    def _on_worker_write_finished(self):
        # called by worker always in finally in write_with_pause
        self.send_watchdog.stop()
        self._reset_send_state()

    def _reset_send_state(self):
        self.send_in_progress = False
        for b in (self.btn_start, self.btn_stop, self.btn_reset):
            if self.worker is not None:
                b.setEnabled(True)
            else:
                b.setEnabled(False)
        self.cmd_send.setEnabled(True)
        self.cmd_input.setEnabled(True)

    @pyqtSlot(str)
    def _on_line_received(self, line):
        parsed = self._parse_line_to_row(line)
        if parsed and self.recording:
            self._consume_row(parsed)

    # parsing / consuming unchanged (kept minimal)
    def _parse_line_to_row(self, line):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3 and parts[0].upper().startswith("ASI-"):
            row = {c: 0 for c in self.columns}
            row["TEAM_ID"] = parts[0]
            row["TIME_SINCE_S"] = int((now() - self.power_on_time).total_seconds())
            row["FLIGHT_STATE"] = self.flight_state
            try: row["GNSS_LAT"] = float(parts[1])
            except: row["GNSS_LAT"] = 0.0
            try: row["PACKET_COUNT"] = int(float(parts[2]))
            except:
                try: row["PACKET_COUNT"] = int(parts[2])
                except: row["PACKET_COUNT"] = self.packet_count + 1
            return row
        if len(parts) >= len(self.columns):
            row = {c: 0 for c in self.columns}
            row["TIME_SINCE_S"] = int((now() - self.power_on_time).total_seconds())
            row["FLIGHT_STATE"] = self.flight_state
            for i, col in enumerate(self.columns):
                try:
                    if col in ("TEAM_ID","GNSS_TIME","FLIGHT_STATE","OPTIONAL_DATA"):
                        row[col] = parts[i]
                    else:
                        row[col] = float(parts[i])
                except:
                    pass
            return row
        return None

    def _consume_row(self, row):
        try: incoming_count = int(row.get("PACKET_COUNT",0))
        except: incoming_count = 0
        if incoming_count and incoming_count > self.packet_count:
            self.packet_count = incoming_count
        else:
            self.packet_count += 1
            row["PACKET_COUNT"] = self.packet_count
        row["TIME_SINCE_S"] = int((now() - self.power_on_time).total_seconds())
        self.buffer.append(row)
        try:
            pd.DataFrame([row])[self.columns].to_csv(CSV_PATH, mode='a', header=False, index=False)
        except Exception:
            pd.DataFrame([row]).to_csv(CSV_PATH, mode='a', header=False, index=False)
        latest = self.buffer[-10:]
        self.table.setRowCount(len(latest))
        for i, r in enumerate(latest):
            for j, col in enumerate(self.columns):
                val = r.get(col, "")
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(str(val)))

    # send helpers
    def _format_with_line_ending(self, base_text):
        mode = self.line_ending.currentText()
        if mode == "\\n (LF)": return base_text + "\n"
        if mode == "\\r (CR)": return base_text + "\r"
        if mode == "\\r\\n (CRLF)": return base_text + "\r\n"
        return base_text

    def send_command(self, cmd_text=None):
        if self.worker is None:
            self.lbl_conn.setText("Not connected"); self.lbl_conn.setStyleSheet("color: red"); return
        if self.send_in_progress:
            # already waiting for write_finished
            return
        if cmd_text is None:
            cmd_text = self.cmd_input.text().strip()
            if not cmd_text:
                return
        out = self._format_with_line_ending(cmd_text)
        # UI state
        self.send_in_progress = True
        for b in (self.btn_start, self.btn_stop, self.btn_reset):
            b.setEnabled(False)
        self.cmd_send.setEnabled(False); self.cmd_input.setEnabled(False)
        self.last_sent.setText(f"Last sent: {cmd_text}")

        # start watchdog: if worker doesn't emit write_finished in time, force-close worker
        self.send_watchdog.start(self.watchdog_ms)

        # attempt to emit to worker
        try:
            self.send_to_worker_with_pause.emit(out)
        except Exception as e:
            print("Send emit failed:", e)
            self.send_watchdog.stop()
            self._reset_send_state()
            self.lbl_conn.setText(f"Send failed: {e}"); self.lbl_conn.setStyleSheet("color: red")

    def _on_send_watchdog(self):
        # worker didn't respond in time -> forcefully close and cleanup to release port
        print("Send watchdog fired - worker unresponsive; forcing close.")
        self.lbl_conn.setText("Watchdog: worker unresponsive")
        self.lbl_conn.setStyleSheet("color: red")
        # attempt graceful close then force cleanup
        self.stop_worker_and_wait(force=True)
        # UI reset
        self._reset_send_state()

    # tick
    def tick(self):
        t_since = int((now() - self.power_on_time).total_seconds())
        try:
            self.lbl_time.setText(f"Time: {t_since}s")
            self.lbl_pkt.setText(f"Packets: {self.packet_count}")
        except Exception:
            pass

    # recording
    def start_recording(self):
        self.recording = True
        self.flight_state = "idle"

    def stop_recording(self):
        self.recording = False
        self.flight_state = "idle"

    def closeEvent(self, event):
        try:
            self.stop_worker_and_wait(force=True)
        except Exception as e:
            print("Error stopping worker:", e)
        event.accept()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    win = Groundstation()
    win.show()
    sys.exit(app.exec_())
