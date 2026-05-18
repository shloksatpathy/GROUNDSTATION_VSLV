import time


class TelemetryBuffer:

    def __init__(self, max_size=500):

        self.max_size = max_size

        self.data = {
            "time": [],
            "altitude": [],
            "pressure": [],
            "temperature": [],
            "roll": [],
            "pitch": [],
            "yaw": [],
            "lat": [],
            "lon": [],
            "vspeed": []
        }

        self.last_alt = None
        self.last_time = None

    # -----------------------------------
    # Add telemetry packet
    # -----------------------------------
    def add_packet(self, packet):

        t = time.time()

        alt = packet.get("altitude")
        pres = packet.get("pressure")
        temp = packet.get("temperature")

        roll = packet.get("roll")
        pitch = packet.get("pitch")
        yaw = packet.get("yaw")

        lat = packet.get("lat")
        lon = packet.get("lon")

        # Store values
        self.data["time"].append(t)
        self.data["altitude"].append(alt)
        self.data["pressure"].append(pres)
        self.data["temperature"].append(temp)

        self.data["roll"].append(roll)
        self.data["pitch"].append(pitch)
        self.data["yaw"].append(yaw)

        self.data["lat"].append(lat)
        self.data["lon"].append(lon)

        # ---- Vertical Speed ----
        vs = 0

        if self.last_alt is not None and alt is not None:

            dt = t - self.last_time

            if dt > 0:
                vs = (alt - self.last_alt) / dt

        self.data["vspeed"].append(vs)

        self.last_alt = alt
        self.last_time = t

        self._limit_size()

    # -----------------------------------
    # Maintain circular buffer
    # -----------------------------------
    def _limit_size(self):

        for key in self.data:

            if len(self.data[key]) > self.max_size:
                self.data[key].pop(0)

    # -----------------------------------
    # Return full dataset
    # -----------------------------------
    def get_data(self):

        return self.data

    # -----------------------------------
    # Return last N packets
    # -----------------------------------
    def get_last(self, n=10):

        result = {}

        for key in self.data:
            result[key] = self.data[key][-n:]

        return result

    # -----------------------------------
    # Return latest packet
    # -----------------------------------
    def latest(self):

        if len(self.data["time"]) == 0:
            return None

        packet = {}

        for key in self.data:
            packet[key] = self.data[key][-1]

        return packet

    # -----------------------------------
    # Clear buffer
    # -----------------------------------
    def clear(self):

        for key in self.data:
            self.data[key].clear()

        self.last_alt = None
        self.last_time = None