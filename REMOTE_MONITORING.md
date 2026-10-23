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

## Option D — No internet at the host: satellite messaging

For launch sites with no mobile coverage or internet, the host can push
telemetry out over a satellite link instead.

### GNSS modules can't send data

A GNSS receiver (GPS, NavIC, Galileo, GLONASS) only **receives** timing
signals from the satellites; it has no transmitter, so it can't send
packets. The vehicle's GNSS module stays what it is today: the source of
position. Sending data needs a separate **satellite messaging modem** on the
host.

The one exception is **BeiDou**: besides positioning, it offers a two-way
short-message service (RDSS). It needs a dedicated BeiDou messaging terminal
and a service card, not an ordinary BeiDou receiver. Messages are short (tens
of characters globally, longer over the Asia-Pacific region), and terminals
and service are mainly sold in China. Practical only if the program operates
there.

### Satellite messaging services

| Service | Coverage | Message size | Typical latency | Hardware | Notes |
|---|---|---|---|---|---|
| **Iridium SBD** (e.g. RockBLOCK 9603) | Global, incl. poles and sea | 340 bytes up | ~5–30 s | Serial modem + antenna, needs clear sky | Pay per message; the most common choice for balloons, rockets and buoys |
| **Iridium Certus / Garmin inReach** | Global | Short texts | ~seconds to minutes | Handheld or modem | Consumer-friendly, little control over the data format |
| **Inmarsat (IsatData Pro)** | Global except poles | Few KB | ~seconds to a minute | Terminal | In India, Inmarsat services are offered through BSNL |
| **Astrocast, Myriota, Lacuna** (satellite IoT) | Global, in passes | ~20–160 bytes | Minutes to hours | IoT modem | Too slow for live flight tracking; fine for "landed here" messages |
| **Starlink** | Wide, where licensed | Full internet | ~50 ms | Dish + power | Gives real internet at the site; Options A–C then work unchanged. Not yet licensed everywhere (including India). |

**Regulation:** satellite phones and terminals are restricted in some
countries. In India, using Iridium or Thuraya devices requires Department of
Telecommunications permission; Inmarsat through BSNL is the licensed route.
Check before buying hardware.

### What fits through the link

Satellite messaging carries a **summary**, not the full stream. With Iridium
SBD, a realistic rate is one message every 10–30 s, paid per message, so
monitors would see a slow-updating position and status rather than live
plots.

A packed binary summary fits in about 25 bytes:

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

The host's hidden-field and share-position settings apply before packing,
so the satellite path follows the same visibility rules as the relay.

### Where the messages land

The satellite provider delivers each message to the provider's cloud, which
forwards it by HTTP webhook or email (RockBLOCK: an HTTP POST to a URL you
choose). So the **monitors still need internet** — only the host is offline.
That makes Option C's relay server the natural receiver: it gets the webhook,
unpacks the summary and sends it to monitors as an ordinary `pkt` message.

```
 Host GCS ──serial──► Iridium modem ──► satellite ──► provider cloud
                                                          │ HTTP POST
 Monitor ◄──────────wss────────── Relay server (VPS) ◄────┘
```

Messages can also go the other way (provider → modem, 270 bytes on Iridium),
which could carry pause/resume or kick commands later, but each one costs a
message credit.

### Implementation plan

1. **Hardware** — a RockBLOCK 9603 (or similar Iridium SBD modem) on a USB
   serial adapter, antenna with a clear view of the sky, and a RockBLOCK
   account with line rental and credits.
2. **`core/sat_uplink.py`** (new) — opens the modem with `pyserial` (already
   a dependency) and sends with the standard AT commands: `AT+SBDWB` to load
   the binary message, `AT+SBDIX` to transmit. Runs on a timer at the
   configured interval and always sends the latest packet, never a backlog.
3. **Summary packing** — `struct.pack` with the layout above, taking fields
   from the same enriched packet the relay publishes, after hidden fields are
   stripped.
4. **Host settings** — a "Satellite uplink" box on the Monitor Settings tab:
   on/off, serial port, send interval, and a running count of messages sent
   (each one costs money). New `config.json` keys: `sat_enabled`, `sat_port`,
   `sat_interval_s`.
5. **Relay server** — a `/sat-webhook` endpoint on the Option C server that
   checks the provider's credentials, unpacks the summary, and forwards it to
   monitors as `pkt`.
6. **Monitor UI** — label satellite packets ("via satellite, 18 s old") so
   operators don't mistake a slow summary for a live feed.
7. **Testing** — bench test with the modem outdoors; confirm delivery time
   and per-message cost before relying on it in flight.

Effort: about 1 week after Option C exists, plus hardware lead time.
Running cost: modem hardware, monthly line rental and per-message credits.

### Offline alternatives without satellites

If the monitors are near the launch site rather than far away, no internet
or satellite link is needed at all:

- **Field Wi-Fi hotspot** — the host laptop (or a portable router) creates a
  Wi-Fi network; monitors join it and use today's LAN mode, discovery
  included. Works with v3.2.0 as is.
- **Long-range point-to-point Wi-Fi** — directional outdoor bridges extend
  that LAN to a second site several kilometres away.
- **Re-broadcast over radio** — a second LoRa or telemetry radio on the host
  re-transmits the summary to monitors with their own receivers, kilometres
  away, without any network.

---

## Comparison

| | A: VPN | B: Port forwarding | C: Cloud relay | D: Satellite |
|---|---|---|---|---|
| Code changes | None | Small | Large | Medium (needs C) |
| Host needs internet | Yes | Yes | Yes | No |
| Works behind carrier NAT | Yes | Only via IPv6 | Yes | n/a |
| Router setup | No | Yes | No | No |
| Extra install on monitors | VPN client | No | No | No |
| Encrypted | Yes | No | Yes (TLS) | Provider link; TLS from server |
| Data | Full stream | Full stream | Full stream | Summary every 10–30 s |
| Running cost | Free tier | Free | Small VPS | Modem + per-message credits |
| Host IP exposed | No | Yes | No | No |
| Effort | ~1 hour | ~1–2 days | ~1–2 weeks | ~1 week after C |

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
   hotspot with today's LAN mode. If they are far away, add **Option D**
   (Iridium SBD summaries) on top of Option C, after checking local rules on
   satellite terminals.
