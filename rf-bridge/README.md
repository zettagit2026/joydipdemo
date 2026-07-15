# CEMA cUAS — RF Bridge (HackRF + FPV Telemetry Radio)

Turns the CEMA cUAS app from **simulation** into a **live RF operator console**.

- **HackRF One** → wide-band drone signal detection & waterfall (real RF).
- **FPV telemetry radio on `/dev/ttyUSB0`** (SiK / RFD900) → real MAVLink
  transmit to and receive from the target drone.

This bridge is a plain host-side Python service (not dockerised — USB
passthrough of SDR into Docker is brittle and offers no benefit here).

---

## 1. Prerequisites

- Debian / Ubuntu (22.04+) with `sudo`.
- **HackRF One** plugged in via USB.
- **FPV telemetry ground module** (SiK-family or RFD900) on `/dev/ttyUSB0`
  paired with the airborne module on the drone.
- The CEMA cUAS backend already running (see `../INSTALL.md`).

## 2. Install

```bash
cd rf-bridge
chmod +x install-deps.sh run.sh
./install-deps.sh
# log out and back in so the 'dialout' group takes effect
```

`install-deps.sh` will:

- `apt install hackrf libhackrf-dev libusb-1.0-0-dev`
- Add your user to `dialout` and `plugdev` groups.
- Create a Python `.venv` and install `pyserial`, `pymavlink`, `websocket-client`, `numpy`.
- Copy `env.example` → `.env` (edit if the backend isn't on `localhost:8001`).

Verify:

```bash
hackrf_info               # should list your HackRF
ls -l /dev/ttyUSB0        # should exist
```

## 3. Configure

Edit `.env`:

```
CEMA_API_URL=http://localhost:8001      # or http://drone-lab01:8001
CEMA_EMAIL=operator@cema.mil
CEMA_PASSWORD=cema@2026

HACKRF_SWEEP_LOW_MHZ=400
HACKRF_SWEEP_HIGH_MHZ=2500
HACKRF_BIN_HZ=1000000
WATERFALL_CENTER_MHZ=2440
WATERFALL_SPAN_MHZ=100

MAVLINK_SERIAL=/dev/ttyUSB0
MAVLINK_BAUD=57600
MAVLINK_RX_ENABLED=1
```

The SiK default baud rate is 57600. If your radio is set to 115200, change it.

## 4. Run

```bash
./run.sh          # start BOTH workers, foreground
./run.sh scanner  # only HackRF sweep
./run.sh bridge   # only MAVLink serial bridge
```

You should see (in the app UI):

- **RF waterfall** on the dashboard turns from `SIM` (simulated) to real
  HackRF data (source flag `HACKRF`).
- **New detections** flow in with `source=HACKRF` or `source=SIK_RADIO`.
- Any packet you craft in the **MAVLink Console** or deploy via the
  **Payload Library** is **written straight to the radio on `/dev/ttyUSB0`**
  → **broadcast to the drone**.

## 5. Auto-start on boot (optional)

```bash
sudo cp -r . /opt/cema/rf-bridge
sudo cp cema-rf-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cema-rf-bridge
journalctl -u cema-rf-bridge -f
```

## 6. Architecture

```
                         ┌──────────────────────────────────┐
                         │      CEMA cUAS Web App           │
                         │  (backend + frontend + Mongo)    │
                         └────────────┬─────────────────────┘
                     REST + WebSocket │  /api/*  /api/ws/mavlink
                                      │
     ┌────────────────────────────────┴─────────────────────────────┐
     │                       RF BRIDGE (this dir)                   │
     │                                                              │
     │  hackrf_scanner.py                     mavlink_bridge.py     │
     │  ─ hackrf_sweep 400–2500 MHz           ─ WS subscribe TX     │
     │  ─ peak detect                         ─ pymavlink RX/TX     │
     │  → POST /api/detections/ingest         ─ /dev/ttyUSB0         │
     │  → POST /api/spectrum/ingest                                 │
     └───────┬───────────────────────────────────┬──────────────────┘
             │                                   │
      USB ┌──┴───┐                       USB ┌───┴────┐
          │HackRF│                           │ SiK/RFD│
          └──────┘                           └────────┘
             │                                   │
        ═══ RF air ═══                       ═══ RF air ═══
             │                                   │
         Drone RF                          Drone MAVLink C2
       (detection only)                    (bidirectional)
```

## 7. Legal / operational warning

Transmitting on 433/868/915 MHz or 2.4 GHz **may require a license**
depending on your country and power. This bridge sends real MAVLink
takedown commands the moment you click a payload in the UI. Only use
in a **screened test range** or against **your own** drone.

`RESTRICTED` — for MoD-style evaluation. Not for public / operational deployment.

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `hackrf_info` says "No HackRF found" | Replug USB, `dmesg | tail`, check `lsusb` for `1d50:6089`. |
| `Permission denied: /dev/ttyUSB0` | You aren't in `dialout` group — `sudo usermod -a -G dialout $USER` then log out/in. |
| Waterfall still shows `SIM` in UI | Scanner not running or backend rejecting ingest. Check `journalctl -u cema-rf-bridge` or the run.sh stdout. |
| MAVLink TX has no effect | Check your radio's air-side baud & net-ID match. Try `mavproxy.py --master=/dev/ttyUSB0` to verify link independently. |
| `hackrf_sweep` runs but no peaks found | Increase `HACKRF_LNA_GAIN` (up to 40) and `HACKRF_VGA_GAIN` (up to 62), or lower `HACKRF_DETECT_THRESHOLD_DB`. |
