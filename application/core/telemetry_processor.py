class TelemetryProcessor:
    def __init__(self, kalman):
        self.kalman = kalman
        self.prev_time = None

    def process(self, raw_altitude, time_stamp):
        if self.prev_time is None:
            self.prev_time = time_stamp
            return raw_altitude, 0.0

        dt = time_stamp - self.prev_time
        self.prev_time = time_stamp

        if dt <= 0:
            dt = 0.01

        return self.kalman.update(raw_altitude, dt)