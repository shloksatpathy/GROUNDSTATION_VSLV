"""
Telemetry relay between the admin ground station and read-only monitors.

The admin GCS owns the radio link. Every packet it processes is forwarded,
already parsed and Kalman-filtered, to each monitor that has joined with the
monitor access code — so a monitor shows exactly what the admin sees and
never needs the packet schema, the serial port, or a radio of its own.

Protocol: one JSON object per UDP datagram, discriminated by "type".

  monitor -> admin  join     {"code"}              sent every HEARTBEAT_MS;
                                                   doubles as the keep-alive
  admin -> monitor  welcome  {"station", "ref", "sim"}   first accepted join
                    denied   {"reason"}            wrong code (or code changed)
                    pkt      {"seq", "data"}       one enriched telemetry packet
                    ref      {"lat", "lon", "alt"} launch reference moved
                    sim      {"result"}            new simulated trajectory
                    reset    {}                    admin restarted recording
                    status   {"paused"}            admin froze / resumed the feed
  admin -> LAN      beacon   {"station", "port"}   broadcast for discovery

What a monitor may see is decided here, not on the monitor: hidden fields are
stripped from each packet, and the reference / simulation / position can be
withheld, so a modified monitor build cannot ask for more. Joins can also be
refused by host allowlist, ban, or monitor cap (see RelayServer.set_policy).

Because the heartbeat re-sends the code, changing the code on the admin
revokes every monitor still holding the old one within one heartbeat, and a
restarted admin picks its monitors back up without them rejoining by hand.

Like ui/auth_dialog.py's code, this is an access checkpoint, not a security
boundary: the code and the telemetry both cross the LAN in plaintext.
"""

import json
import math
import time

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtNetwork import QHostAddress, QUdpSocket

DEFAULT_RELAY_PORT = 5600
DISCOVERY_PORT = 5601

HEARTBEAT_MS = 2000
# A monitor silent for this long is dropped from the admin's subscriber list.
SUBSCRIBER_TIMEOUT_S = 8.0
# A monitor that has heard nothing for this long reports the link as lost.
LINK_TIMEOUT_S = 5.0
BEACON_MS = 2000

# Simulated trajectories run to thousands of samples; a UDP datagram tops out
# just under 64 KB. Decimating keeps the "sim" message to one datagram.
_SIM_MAX_POINTS = 600


# Packet keys that locate the vehicle; withheld when position sharing is off.
POSITION_KEYS = frozenset({
    "GNSS_LAT", "lat", "LAT", "latitude",
    "GNSS_LON", "lon", "LON", "longitude",
})


def _bare_host(host):
    """Peer address without the IPv4-mapped IPv6 prefix Qt adds."""
    return host.replace("::ffff:", "")


def _encode(msg_type, **fields):
    fields["type"] = msg_type
    # default=str: enriched packets can carry odd values (numpy scalars,
    # bytes from a malformed field) — stringify rather than drop the packet.
    return json.dumps(fields, default=str, allow_nan=False).encode("utf-8")


def _decode(datagram):
    try:
        msg = json.loads(bytes(datagram).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return msg if isinstance(msg, dict) and "type" in msg else None


def _json_safe(value):
    """NaN/inf are not JSON; map them to None like a missing reading."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def sim_result_to_wire(result):
    """Decimated, JSON-friendly copy of a core/rocket_sim result dict."""
    n = len(result["x"])
    step = max(1, math.ceil(n / _SIM_MAX_POINTS))
    idx = list(range(0, n, step))
    if idx and idx[-1] != n - 1:
        idx.append(n - 1)  # keep the landing point
    return {
        "x": [float(result["x"][i]) for i in idx],
        "y": [float(result["y"][i]) for i in idx],
        "z": [float(result["z"][i]) for i in idx],
        "apogee_agl": float(result["apogee_agl"]),
        "max_speed": float(result["max_speed"]),
    }


def sim_result_from_wire(wire):
    """Inverse of sim_result_to_wire — arrays as Trajectory3DView expects."""
    import numpy as np
    return {
        "x": np.asarray(wire["x"], dtype=float),
        "y": np.asarray(wire["y"], dtype=float),
        "z": np.asarray(wire["z"], dtype=float),
        "apogee_agl": wire["apogee_agl"],
        "max_speed": wire["max_speed"],
    }


class RelayServer(QObject):
    """Admin side: authenticates monitors and fans telemetry out to them."""

    # Emitted with the current list of "host:port" strings whenever a monitor
    # joins, leaves, or is revoked.
    subscribers_changed = pyqtSignal(list)
    status_changed = pyqtSignal(str)

    def __init__(self, station_name, code, parent=None):
        super().__init__(parent)
        self.station_name = station_name
        self.code = code
        self.port = None

        self._sock = None
        self._beacon_sock = None
        self._subscribers = {}  # (QHostAddress str, port) -> {"seen", "since"}
        self._banned = set()    # bare hosts removed by the admin, until unbanned

        # Display / access policy, set from the admin's Monitor Settings tab.
        self.max_monitors = 0           # 0 = unlimited
        self.allowed_hosts = frozenset()  # empty = any host may join
        self.hidden_fields = frozenset()
        self.share_position = True
        self.share_reference = True
        self.share_simulation = True
        self.max_rate_hz = 0.0          # 0 = every packet
        self.paused = False
        self._last_pkt_time = 0.0
        self._seq = 0
        # Replayed in each welcome so a monitor that joins mid-session gets
        # the same reference frame and ideal trajectory as the admin.
        self._ref = None
        self._sim_wire = None

        self._sweep_timer = QTimer(self)
        self._sweep_timer.timeout.connect(self._sweep)
        self._beacon_timer = QTimer(self)
        self._beacon_timer.timeout.connect(self._send_beacon)

    # -----------------------------------
    # Lifecycle
    # -----------------------------------
    def start(self, port):
        self.stop()
        sock = QUdpSocket(self)
        if not sock.bind(QHostAddress.AnyIPv4, port):
            self.status_changed.emit(f"Relay could not bind UDP {port}: {sock.errorString()}")
            sock.deleteLater()
            return False

        self._sock = sock
        self._sock.readyRead.connect(self._on_ready_read)
        self._beacon_sock = QUdpSocket(self)
        self.port = port
        self._sweep_timer.start(1000)
        self._beacon_timer.start(BEACON_MS)
        self._send_beacon()
        self.status_changed.emit(f"Relay listening on UDP {port}")
        return True

    def stop(self):
        self._sweep_timer.stop()
        self._beacon_timer.stop()
        for sock in (self._sock, self._beacon_sock):
            if sock is not None:
                sock.close()
                sock.deleteLater()
        self._sock = None
        self._beacon_sock = None
        self.port = None
        if self._subscribers:
            self._subscribers.clear()
            self.subscribers_changed.emit([])

    def is_running(self):
        return self._sock is not None

    def set_code(self, code):
        """Change the monitor code. Monitors on the old code are revoked at
        their next heartbeat, in _on_ready_read."""
        self.code = code

    def set_policy(self, *, max_monitors, allowed_hosts, hidden_fields, share_position,
                   share_reference, share_simulation, max_rate_hz):
        """Replace the access/display policy. Takes effect on the next packet;
        monitors already joined but no longer permitted are removed now."""
        self.max_monitors = max(0, int(max_monitors))
        self.allowed_hosts = frozenset(allowed_hosts)
        self.hidden_fields = frozenset(hidden_fields)
        self.share_position = bool(share_position)
        newly_ref = share_reference and not self.share_reference
        newly_sim = share_simulation and not self.share_simulation
        self.share_reference = bool(share_reference)
        self.share_simulation = bool(share_simulation)
        self.max_rate_hz = max(0.0, float(max_rate_hz))

        if self.allowed_hosts:
            for key in [k for k in self._subscribers
                        if _bare_host(k[0]) not in self.allowed_hosts]:
                self._remove(key, "This host is no longer allowed by the admin station.")
        # Turning sharing on should not wait for the admin to move the
        # reference or rerun the solver.
        if newly_ref and self._ref is not None:
            self._broadcast(_encode("ref", **self._ref))
        if newly_sim and self._sim_wire is not None:
            self._broadcast(_encode("sim", result=self._sim_wire))

    def set_paused(self, paused):
        """Freeze the feed: monitors keep their last view and are told why."""
        self.paused = bool(paused)
        self._broadcast(_encode("status", paused=self.paused))

    def kick(self, key):
        """Remove one monitor and refuse its host until unbanned."""
        if key in self._subscribers:
            self._banned.add(_bare_host(key[0]))
            self._remove(key, "Removed by the admin station.")

    def unban(self, host):
        self._banned.discard(host)

    def banned_hosts(self):
        return sorted(self._banned)

    def subscriber_info(self):
        """[(key, "host:port", seconds connected)] for the settings tab."""
        now = time.monotonic()
        return [(k, f"{_bare_host(k[0])}:{k[1]}", now - v["since"])
                for k, v in self._subscribers.items()]

    # -----------------------------------
    # Publishing (called from the admin UI)
    # -----------------------------------
    def publish_packet(self, enriched):
        if not self._subscribers or self.paused:
            return
        if self.max_rate_hz > 0:
            now = time.monotonic()
            if now - self._last_pkt_time < 1.0 / self.max_rate_hz:
                return
            self._last_pkt_time = now
        self._seq += 1  # only sent packets count, so throttling isn't "loss"
        hidden = self.hidden_fields
        if not self.share_position:
            hidden = hidden | POSITION_KEYS
        data = {k: _json_safe(v) for k, v in enriched.items() if k not in hidden}
        try:
            payload = _encode("pkt", seq=self._seq, data=data)
        except ValueError as e:
            # A non-finite value nested somewhere _json_safe doesn't reach.
            # Losing one monitor packet beats breaking the admin's pipeline.
            print(f"[RELAY] Could not encode packet {self._seq}: {e}")
            return
        self._broadcast(payload)

    def publish_reference(self, lat, lon, alt):
        self._ref = {"lat": lat, "lon": lon, "alt": alt}
        if self.share_reference:
            self._broadcast(_encode("ref", **self._ref))

    def publish_simulation(self, result):
        self._sim_wire = sim_result_to_wire(result)
        if self.share_simulation:
            self._broadcast(_encode("sim", result=self._sim_wire))

    def publish_reset(self):
        self._broadcast(_encode("reset"))

    # -----------------------------------
    # Internals
    # -----------------------------------
    def _broadcast(self, payload):
        if self._sock is None:
            return
        for host, port in list(self._subscribers):
            self._sock.writeDatagram(payload, QHostAddress(host), port)

    def _on_ready_read(self):
        while self._sock is not None and self._sock.hasPendingDatagrams():
            size = self._sock.pendingDatagramSize()
            datagram, host, port = self._sock.readDatagram(max(size, 1))
            msg = _decode(datagram)
            if msg is None or msg.get("type") != "join":
                continue

            key = (host.toString(), port)
            bare = _bare_host(key[0])
            known = key in self._subscribers

            if str(msg.get("code", "")).strip().upper() != self.code.strip().upper():
                reason = "Incorrect monitor access code."
            elif bare in self._banned:
                reason = "This host was removed by the admin station."
            elif self.allowed_hosts and bare not in self.allowed_hosts:
                reason = "This host is not on the admin station's allowed list."
            elif (not known and self.max_monitors
                  and len(self._subscribers) >= self.max_monitors):
                reason = "The admin station has reached its monitor limit."
            else:
                reason = None

            if reason is not None:
                self._sock.writeDatagram(_encode("denied", reason=reason), host, port)
                if self._subscribers.pop(key, None) is not None:
                    self._emit_subscribers()
                continue

            now = time.monotonic()
            if known:
                self._subscribers[key]["seen"] = now
            else:
                self._subscribers[key] = {"seen": now, "since": now}
                self._sock.writeDatagram(
                    _encode("welcome", station=self.station_name, paused=self.paused,
                            ref=self._ref if self.share_reference else None,
                            sim=self._sim_wire if self.share_simulation else None),
                    host, port)
                self._emit_subscribers()

    def _remove(self, key, reason):
        """Tell a monitor it is out (best effort), then forget it."""
        if self._sock is not None:
            self._sock.writeDatagram(_encode("denied", reason=reason),
                                     QHostAddress(key[0]), key[1])
        if self._subscribers.pop(key, None) is not None:
            self._emit_subscribers()

    def _sweep(self):
        cutoff = time.monotonic() - SUBSCRIBER_TIMEOUT_S
        stale = [k for k, v in self._subscribers.items() if v["seen"] < cutoff]
        for k in stale:
            del self._subscribers[k]
        if stale:
            self._emit_subscribers()
        if self.paused:
            # No packets flow while paused; keep the monitors' link alive.
            self._broadcast(_encode("status", paused=True))

    def _emit_subscribers(self):
        self.subscribers_changed.emit(
            [f"{_bare_host(h)}:{p}" for h, p in self._subscribers])

    def _send_beacon(self):
        if self._beacon_sock is None:
            return
        self._beacon_sock.writeDatagram(
            _encode("beacon", station=self.station_name, port=self.port),
            QHostAddress.Broadcast, DISCOVERY_PORT)


class RelayClient(QObject):
    """Monitor side: joins an admin relay and re-emits what it forwards."""

    joined = pyqtSignal(str)            # admin station name
    denied = pyqtSignal(str)            # reason
    packet_received = pyqtSignal(dict)  # enriched telemetry packet
    reference_received = pyqtSignal(float, float, float)
    simulation_received = pyqtSignal(dict)
    reset_received = pyqtSignal()
    link_changed = pyqtSignal(bool)     # True while datagrams keep arriving
    paused_changed = pyqtSignal(bool)   # admin froze / resumed the feed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.host = None
        self.port = None
        self.code = None
        self.station = None
        self.dropped = 0  # packets lost in transit, from gaps in "seq"
        # Latest of each, kept for a window created after the welcome that
        # carried them (the join dialog runs before the monitor window).
        self.reference = None   # (lat, lon, alt)
        self.simulation = None  # wire-format sim result

        self._sock = QUdpSocket(self)
        # Ephemeral port: several monitors can run on one machine.
        self._sock.bind(QHostAddress.AnyIPv4, 0)
        self._sock.readyRead.connect(self._on_ready_read)

        self._last_rx = None
        self._last_seq = None
        self._link_up = False
        self._paused = False
        self._heartbeat = QTimer(self)
        self._heartbeat.timeout.connect(self._send_join)
        self._watchdog = QTimer(self)
        self._watchdog.timeout.connect(self._check_link)

    def join(self, host, port, code):
        """Start (or retarget) the join heartbeat. Outcome arrives as
        joined/denied; silence means no admin is answering at host:port."""
        self.host = host
        self.port = port
        self.code = code
        self.station = None
        self._last_seq = None
        self._send_join()
        self._heartbeat.start(HEARTBEAT_MS)
        self._watchdog.start(1000)

    def leave(self):
        self._heartbeat.stop()
        self._watchdog.stop()
        self.station = None

    def _send_join(self):
        if self.host:
            self._sock.writeDatagram(_encode("join", code=self.code),
                                     QHostAddress(self.host), self.port)

    def _check_link(self):
        up = self._last_rx is not None and time.monotonic() - self._last_rx < LINK_TIMEOUT_S
        if up != self._link_up:
            self._link_up = up
            self.link_changed.emit(up)

    def _on_ready_read(self):
        while self._sock.hasPendingDatagrams():
            size = self._sock.pendingDatagramSize()
            datagram, _host, _port = self._sock.readDatagram(max(size, 1))
            msg = _decode(datagram)
            if msg is None:
                continue
            self._last_rx = time.monotonic()
            self._dispatch(msg)
        self._check_link()

    def _dispatch(self, msg):
        kind = msg["type"]
        if kind == "pkt":
            self._set_paused(False)  # a lost "resume" status must not stick
            seq = msg.get("seq")
            if isinstance(seq, int):
                if self._last_seq is not None and seq > self._last_seq + 1:
                    self.dropped += seq - self._last_seq - 1
                self._last_seq = seq
            if isinstance(msg.get("data"), dict):
                self.packet_received.emit(msg["data"])
        elif kind == "welcome":
            self.station = msg.get("station") or "Ground Station"
            self.joined.emit(self.station)
            self._set_paused(bool(msg.get("paused")))
            ref = msg.get("ref")
            if ref:
                self._emit_reference(ref)
            if msg.get("sim"):
                self.simulation = msg["sim"]
                self.simulation_received.emit(msg["sim"])
        elif kind == "denied":
            # Stop knocking — a wrong code won't become right on its own.
            self.leave()
            self.denied.emit(msg.get("reason") or "Access denied.")
        elif kind == "ref":
            self._emit_reference(msg)
        elif kind == "sim" and msg.get("result"):
            self.simulation = msg["result"]
            self.simulation_received.emit(msg["result"])
        elif kind == "reset":
            self._last_seq = None
            self.reset_received.emit()
        elif kind == "status":
            self._set_paused(bool(msg.get("paused")))

    def _set_paused(self, paused):
        if paused != self._paused:
            self._paused = paused
            self.paused_changed.emit(paused)

    def _emit_reference(self, ref):
        try:
            self.reference = (float(ref["lat"]), float(ref["lon"]),
                              float(ref.get("alt") or 0.0))
        except (KeyError, TypeError, ValueError):
            return
        self.reference_received.emit(*self.reference)


class BeaconListener(QObject):
    """Collects admin stations announcing themselves on the LAN."""

    station_found = pyqtSignal(str, str, int)  # name, host, port

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sock = QUdpSocket(self)
        # ShareAddress so a second monitor on the same machine can listen too.
        self._sock.bind(QHostAddress.AnyIPv4, DISCOVERY_PORT,
                        QUdpSocket.ShareAddress | QUdpSocket.ReuseAddressHint)
        self._sock.readyRead.connect(self._on_ready_read)

    def _on_ready_read(self):
        while self._sock.hasPendingDatagrams():
            size = self._sock.pendingDatagramSize()
            datagram, host, _port = self._sock.readDatagram(max(size, 1))
            msg = _decode(datagram)
            if msg is None or msg.get("type") != "beacon":
                continue
            try:
                port = int(msg.get("port"))
            except (TypeError, ValueError):
                continue
            self.station_found.emit(str(msg.get("station") or "Ground Station"),
                                    host.toString().replace("::ffff:", ""), port)
