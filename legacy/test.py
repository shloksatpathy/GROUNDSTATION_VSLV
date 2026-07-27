import serial, time
s = serial.Serial('COM5', 9600, timeout=1, write_timeout=2)
s.write(b'STOP\n')
s.flush()
time.sleep(0.2)
s.close()
print("Wrote START")
