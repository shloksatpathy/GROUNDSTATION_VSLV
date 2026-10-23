# Remote Monitoring — Beyond the LAN

Options for letting monitor stations watch the host from anywhere, not only
from the same local network — including from launch sites with no internet —
with an implementation plan for each.

Status: proposal. Nothing here is implemented yet.

---

## Where we are today

Monitor mode (v3.2.0, `application/core/relay.py`) is a UDP protocol:

- The monitor sends `join {code}` to the host every 2 s; that doubles as the
  keep-alive.
- The host answers to the address the join came from, then streams `pkt`,
  `ref`, `sim`, `reset` and `status` messages back to it.
- Discovery is a UDP broadcast beacon on port 5601.

Because the monitor always speaks first and the host only replies, **the
monitor side already works through any home router or NAT**. Only the host
needs to be reachable. What ties it to the LAN:

| Blocker | Where | Effect off the LAN |
|---|---|---|
| Broadcast discovery | `RelayServer._send_beacon`, `BeaconListener` | Broadcasts never leave the LAN; the host must be typed in by hand |
| Host behind NAT | network | A join from outside never reaches the host unless a port is forwarded |
| Typed host must be an IP | `RelayClient._send_join` uses `QHostAddress(self.host)` | A DNS name (`gcs.example.com`, a Tailscale/DDNS name) becomes a null address, so the join is silently never sent |
| Large `sim` / `welcome` datagrams | `_SIM_MAX_POINTS = 600` → about 35 KB of JSON | Fine on a LAN; on the internet it fragments into ~25 IP fragments, which are often dropped, so the monitor never gets the trajectory and may never see `welcome` |
| IPv4 only | `bind(QHostAddress.AnyIPv4, ...)` | Can't use a public IPv6 address, which many mobile and fibre connections offer even when IPv4 is behind carrier NAT |
| Plaintext | whole protocol | The monitor code and the telemetry cross the internet readable by anyone on the path |
| No brute-force limit | `RelayServer._on_ready_read` | An open internet port lets anyone guess monitor codes as fast as they like |

---

## Option A — Overlay VPN (Tailscale / ZeroTier)

Put the host and every monitor on one private virtual network. Each machine
gets a stable private IP (Tailscale: `100.x.y.z`) that works from anywhere,
through any router or carrier NAT, with all traffic encrypted.

**Pros**
- Works today with no code changes: join with the host's VPN IP.
- Encrypted and authenticated by the VPN; the relay port is never exposed to
  the internet.
- No router configuration.

**Cons**
- Every monitor machine has to install the VPN and be invited to the network.
- Discovery still doesn't work; the host IP is typed in.
- Hostnames (Tailscale MagicDNS names) only work after the DNS fix from
  Option B, step 1.

**Implementation plan**
1. Install Tailscale on the host and each monitor machine; sign in to one
   tailnet (or share the host device with the monitors' accounts).
2. On the host, read its address with `tailscale ip -4`.
3. Monitors enter that address and port 5600 in the join dialog.
4. Docs: add a "Monitoring from anywhere" section to the README with these steps.

Effort: an hour of setup, no code.

---

## Option B — Direct internet access (port forwarding + protocol fixes)

Keep the UDP protocol and make the host reachable on a public address.

**Pros**
- No third-party software on monitor machines.
- Smallest code change that makes the app itself internet-capable.

**Cons**
- Needs access to the host's router to forward a port, and a public IPv4 or
  IPv6 address. Fails behind carrier NAT (common on mobile data and some ISPs)
  unless IPv6 is used.
- The host's home IP is exposed; it usually changes, so a dynamic DNS name is
  needed.
- Still plaintext: the code and telemetry are readable on the path. Only
  acceptable for non-sensitive telemetry.

**Implementation plan**
1. **Resolve hostnames** — in `RelayClient.join`, resolve `host` with
   `QHostInfo.fromName` (or `socket.getaddrinfo`) once and keep the resulting
   `QHostAddress`; report "Can't resolve <host>" in the join dialog on failure.
   Also benefits Option A.
2. **Keep every datagram under ~1200 bytes** — send the simulated trajectory
   as numbered chunks (`sim_part {id, i, n, x, y, z}`), reassembled on the
   monitor, and stop embedding `sim` in `welcome` (send the chunks right after
   it instead). Round coordinates to 0.1 m to cut the size further.
3. **Dual-stack** — bind the host socket to `QHostAddress.Any` instead of
   `AnyIPv4`, so it is reachable on IPv6 too. The client binds to match.
4. **Rate-limit failed joins** — after a few wrong codes from one host, ignore
   it for a cool-down (e.g. 5 wrong codes → 60 s), so the code can't be
   brute-forced through the open port.
5. **Router + DNS** — forward UDP 5600 to the host machine; point a dynamic
   DNS name (DuckDNS, No-IP, or the router's own) at it.
6. **UI** — change the join dialog's placeholder to "IP address or hostname";
   add the public port and address hints to the Monitor Settings tab.
7. **Docs** — README section on port forwarding, DDNS, and the plaintext
   caveat.

Effort: about 1–2 days of code and testing. Testing needs a monitor on a
genuinely different network (e.g. a laptop on a phone hotspot).

---

## Option C — Cloud relay server

Add a small server on a public VPS. The host connects **out** to it and
monitors connect to it, so neither side needs port forwarding, and the
transport is encrypted WebSocket (`wss://`).

```
 Host GCS ──wss──►  Relay server (VPS)  ◄──wss── Monitor
 (radio link)       public hostname, TLS         (anywhere)
```

The server is a dumb tunnel: it carries the existing JSON messages unchanged,
tagging each monitor connection with an ID. The host still decides everything
— code check, allowlist, kicks, hidden fields — so what a monitor can see is
still enforced on the host, not on the server.

**Pros**
- Works from anywhere, including behind carrier NAT, with no router setup or
  software on monitor machines beyond the app.
- Encrypted with TLS; the host's home IP is never exposed.
- TCP-based, so message size and fragmentation stop mattering.
- Natural base for later features: a browser-based viewer, or recording and
  replay on the server (ties in with v3.3.0's replay mode).

**Cons**
- A new component to build, deploy and keep running, and a VPS to pay for
  (a small $5/month instance is enough).
- WebSocket is TCP: on a bad link packets queue and arrive late rather than
  being dropped. Mitigated by the host's existing send-rate cap and by the
  server dropping a slow monitor's backlog.
- The allowlist would match a monitor's public IP as seen by the server, and
  monitors behind the same router share one IP.

**Implementation plan**
1. **Server** (`server/relay_server.py`, new): Python `asyncio` +
   `websockets`. Two endpoints:
   - `/host` — one host connection, authenticated with a host key from the
     server's config.
   - `/monitor` — any number of monitor connections. Each gets an ID; frames
     from a monitor are forwarded to the host as `{monitor_id, peer_ip, msg}`,
     and frames from the host addressed to an ID (or to all) go to those
     monitors.
   - If the host is offline, monitors get `denied {"Host station is offline"}`.
2. **Transport split in `core/relay.py`** — move the socket handling out of
   `RelayServer` / `RelayClient` behind two small transports: the current UDP
   one and a WebSocket one using `PyQt5.QtWebSockets.QWebSocket` (ships with
   PyQt5, no new client dependency). Subscriber keys become
   `(monitor_id, peer_ip)` for the WebSocket transport; everything else in the
   protocol stays as is.
3. **Host settings** — Monitor Settings tab gets a "Connection" choice:
   *Local network (UDP)* or *Relay server* with server URL and host key. New
   `config.json` keys: `relay_mode`, `relay_server_url`, `relay_host_key`.
4. **Join dialog** — a "Relay server" field (URL) alongside the LAN list.
5. **Deployment** — run the server under systemd on the VPS, with Caddy in
   front for automatic TLS certificates (`wss://relay.example.com`).
   Document it in `server/README.md`.
6. **Testing** — host on one network, two monitors on others (hotspot +
   another site); check join, revoke by code change, kick, pause, field
   hiding, host restart recovery and server restart recovery.

Effort: about 1–2 weeks including deployment and testing.

---

## Option D — Long-range radio relay (no internet, 30–40 km)

For launch sites with no internet or mobile coverage, the host can
re-broadcast telemetry over a second radio to monitors that each have a
matching radio, 30–40 km away.

### A second radio on its own port

The host's existing receiver module stays dedicated to the vehicle link. The
relay uses a **second radio module on its own USB-serial port** (another COM
or `/dev/ttyUSB*` port). `SerialManager` in `core/serial_manager.py` already
manages one port per object, so a second instance can drive the relay radio
without touching the vehicle link.

Re-using the vehicle receiver is not an option:

- These radios are half-duplex. Every re-broadcast would take airtime from
  the vehicle's downlink and could collide with its packets, so the flight
  link would lose data.
- The vehicle's own radio would hear the re-broadcasts, and the host already
  sends commands to the vehicle over that port.

Keep the two links apart:

- **Different band** where possible — e.g. vehicle on 433 MHz, relay on
  865 MHz — otherwise at least a different channel and network ID (XBee PAN
  ID, LoRa sync word).
- **Antenna separation** — a 1 W relay transmitter next to the receiver can
  drown out the weak vehicle signal. Mount the two antennas several metres
  apart, ideally one above the other.

Use **plain LoRa, not LoRaWAN**: LoRaWAN routes through a gateway and a
network server (e.g. The Things Network), which needs internet.

### Range: line of sight decides, not power

**Link budget is not the problem.** At 865 MHz over 35 km, free-space loss
is about 122 dB. India's licence-free 865–867 MHz band allows 1 W (30 dBm)
transmit power; with directional (Yagi) antennas of ~9 dBi at both ends the
received signal is about −75 dBm, against LoRa receiver sensitivities of
about −123 to −137 dBm. That is 50+ dB of margin, so even LoRa's faster
settings work.

**Height is the problem.** For a reliable 35 km link the straight line
between the antennas has to clear the ground with margin:

| At the midpoint of a 35 km path | 865 MHz |
|---|---|
| Earth's curvature (standard refraction) | ~18 m |
| 60% of the first Fresnel zone (the clearance the beam needs) | ~33 m |
| **Line of sight needed above the terrain** | **~40–50 m** |

On flat ground that means two masts of 25 m or more. In practice, put one
or both ends on a hill, a tall building or a tower. Without elevation,
expect 5–15 km over flat ground.

### Hardware

| | Data rate | 30–40 km? | Encryption | Notes |
|---|---|---|---|---|
| **RFDesign RFD868x** (868 MHz variant of the RFD900x) | 64–250 kbps | Yes, with elevation and directional antennas | AES in firmware | Standard telemetry radio for drones and rockets; fast enough for the full packet stream. Confirm it can be set to 865–867 MHz for India. |
| **LoRa at 1 W** (e.g. Ebyte E22-900T30, or SX1262 + amplifier) | ~1–5 kbps at long-range settings | Yes, with elevation | None; added in the app | Cheap; carries a packed summary at about 1 Hz, not the full stream |
| **XBee 868 / 865LP** | 10–80 kbps | Borderline | AES-128 built in | Lower-power regional variants. The XBee-PRO 900HP's 45 km figure is for the US 902–928 MHz band, which isn't legal in India. |

**Antennas**
- **Host:** an omnidirectional collinear antenna (~6–9 dBi) on the highest
  point available, so monitors in any direction can hear it.
- **Monitors:** a Yagi pointed at the host.
- **Repeater:** where a monitor has no line of sight to the host, a repeater
  on a hill between them. DigiMesh and the RFD radios support relaying.

**Regulation:** in India the licence-free band is 865–867 MHz, limited to
1 W transmit power and 4 W EIRP. Check the limits for any other country.

**Before buying,** run a terrain-based link calculation for the actual sites
(Radio Mobile or HeyWhatsThat, both free), then do a range test at the real
locations.

### What goes over the air

- **RFD868x / XBee:** the same `pkt`, `ref` and `status` JSON messages the
  UDP relay sends, at a capped rate. `sim` goes as numbered chunks (see
  Option B step 2), repeated now and then.
- **LoRa:** a packed binary summary, about 25 bytes:

| Field | Type | Bytes |
|---|---|---|
| Sequence number | uint16 | 2 |
| Mission time (s) | uint32 | 4 |
| Latitude, longitude (1e-7 deg) | int32 × 2 | 8 |
| Altitude (dm) | int32 | 4 |
| Vertical speed (cm/s) | int16 | 2 |
| Flight state | uint8 | 1 |
| Battery (%) | uint8 | 1 |
| Packet count since last summary | uint16 | 2 |

  The launch reference goes out as its own small message every few seconds;
  the simulated trajectory is too large for LoRa and isn't sent.

Either way, the host's hidden-field and share-position settings apply
before anything is transmitted.

**Access control changes.** Broadcast radio has no join handshake: the host
can't see who is listening, so the allowlist, kicks and the monitor limit
don't apply. Access comes down to encryption — whoever has the key can
listen, and changing the key locks everyone else out.

### Implementation plan

1. **Hardware and site survey** — pick the radio (RFD868x if the full stream
   is wanted, LoRa if a summary is enough), run the terrain calculation for
   the real sites, and do a range test before writing code.
2. **`core/radio_relay.py`** (new) — host side. Opens the relay radio's port
   with `pyserial`, takes the same filtered packets `RelayServer` publishes,
   and writes framed messages (start byte, length, CRC-16) at a capped rate.
   For LoRa, packs the summary with `struct.pack`.
3. **Encryption** — rely on the radio's AES where it has one (RFD, XBee);
   for raw LoRa, encrypt each frame with AES-GCM using a key derived from
   the monitor code (adds 28 bytes per frame).
4. **Host settings** — a "Radio relay" box on the Monitor Settings tab:
   on/off, serial port, baud rate, send rate, radio type. New `config.json`
   keys: `radio_relay_enabled`, `radio_relay_port`, `radio_relay_baud`,
   `radio_relay_rate_hz`, `radio_relay_kind`.
5. **Monitor side** — a `RadioClient` that reads frames from the monitor's
   own radio and emits the same signals as `RelayClient`
   (`packet_received`, `reference_received`, ...), so the monitor window is
   unchanged. The join dialog gets a "Radio" tab: serial port, baud rate and
   key.
6. **Monitor UI** — show the link as "via radio" with packet age and loss
   from the sequence numbers; on LoRa, say that only the summary is shown.
7. **Testing** — first on the bench with two radios, then with the vehicle
   receiver running alongside to confirm the relay transmitter doesn't hurt
   the downlink, then at the real sites.

Effort: about 1 week of code and testing, plus hardware lead time and field
tests.

### Nearby monitors: no extra radio needed

If the monitors are within a few hundred metres of the host:

- **Field Wi-Fi hotspot** — the host laptop or a portable router creates a
  Wi-Fi network; monitors join it and use today's LAN mode, discovery
  included. Works with v3.2.0 as is.
- **Point-to-point Wi-Fi bridges** — directional outdoor bridges extend that
  LAN to a second site several kilometres away.

---

## Comparison

| | A: VPN | B: Port forwarding | C: Cloud relay | D: Radio relay |
|---|---|---|---|---|
| Code changes | None | Small | Large | Medium |
| Host needs internet | Yes | Yes | Yes | No |
| Works behind carrier NAT | Yes | Only via IPv6 | Yes | n/a |
| Router setup | No | Yes | No | No |
| Extra install on monitors | VPN client | No | No | Radio + antenna |
| Encrypted | Yes | No | Yes (TLS) | Radio AES or app-level AES |
| Data | Full stream | Full stream | Full stream | Full stream (RFD) or ~1 Hz summary (LoRa) |
| Range | Anywhere | Anywhere | Anywhere | 30–40 km with elevation |
| Running cost | Free tier | Free | Small VPS | One-time hardware |
| Host IP exposed | No | Yes | No | No |
| Effort | ~1 hour | ~1–2 days | ~1–2 weeks | ~1 week + field tests |

---

## Recommendation

1. **Now:** use **Option A** for real flights. It needs no code and is the only
   option that is both encrypted and available today.
2. **Next:** do **Option B steps 1 and 2** (hostname resolution and small
   datagrams). They are cheap, make the VPN setup nicer (MagicDNS names), and
   remove a real reliability problem with the trajectory message. Skip opening
   a public port unless the telemetry is not sensitive.
3. **Later:** build **Option C** if monitors need to be people who can't
   install a VPN, or if a browser-based viewer or server-side replay becomes a
   goal.
4. **Sites with no internet:** if monitors are nearby, use a field Wi-Fi
   hotspot with today's LAN mode. Up to 30–40 km away, use **Option D** with a
   second radio, after a terrain check and range test at the real sites.
