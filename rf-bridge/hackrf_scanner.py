#!/usr/bin/env python3
"""HackRF wide-band sweep → CEMA cUAS backend.

Uses the `hackrf_sweep` CLI (part of the standard hackrf-tools package).
Parses its stdout, computes:
  - a downsampled waterfall row (pushed to POST /api/spectrum/ingest)
  - peak detections above noise floor (pushed to POST /api/detections/ingest)

Frequency band → protocol heuristic:
  0.400–0.500 GHz  → SiK / LoRa / 433 MHz C2  (MAVLink v2)
  0.860–0.930 GHz  → 868/915 MHz ExpressLRS / RFD900
  1.200–1.320 GHz  → analog video downlink
  2.400–2.500 GHz  → WiFi/BT/DJI OcuSync/MAVLink 2.4G
  5.150–5.900 GHz  → 5.8 GHz FPV/DJI (HackRF stops at 6 GHz)

Requires:
  sudo apt install hackrf
  and the HackRF plugged in via USB.
"""
from __future__ import annotations

import logging
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

from common import CemaClient, cfg, cfg_float, cfg_int

log = logging.getLogger("hackrf-scanner")

BANDS: List[Tuple[float, float, str, str, str]] = [
    (0.400, 0.500, "MAVLink v1/v2", "SiK 433 MHz C2",     "HIGH"),
    (0.860, 0.930, "MAVLink v2",    "RFD900 / ExpressLRS", "HIGH"),
    (1.200, 1.320, "Analog Video",  "1.2 GHz FPV video",   "MEDIUM"),
    (2.400, 2.500, "MAVLink 2G",    "2.4 GHz C2 / DJI",    "HIGH"),
    (5.150, 5.900, "OcuSync",       "5.8 GHz FPV / DJI",   "MEDIUM"),
]


def classify_band(freq_ghz: float) -> Tuple[str, str, str]:
    for lo, hi, proto, model, threat in BANDS:
        if lo <= freq_ghz <= hi:
            return proto, model, threat
    return "Unknown", "Unclassified UAV", "LOW"


@dataclass
class SweepConfig:
    low_mhz: int
    high_mhz: int
    bin_hz: int
    lna: int
    vga: int
    threshold_db: float
    waterfall_center_mhz: float
    waterfall_span_mhz: float
    interval: float


def load_cfg() -> SweepConfig:
    return SweepConfig(
        low_mhz=cfg_int("HACKRF_SWEEP_LOW_MHZ", 400),
        high_mhz=cfg_int("HACKRF_SWEEP_HIGH_MHZ", 2500),
        bin_hz=cfg_int("HACKRF_BIN_HZ", 1_000_000),
        lna=cfg_int("HACKRF_LNA_GAIN", 32),
        vga=cfg_int("HACKRF_VGA_GAIN", 30),
        threshold_db=cfg_float("HACKRF_DETECT_THRESHOLD_DB", 20.0),
        waterfall_center_mhz=cfg_float("WATERFALL_CENTER_MHZ", 2440.0),
        waterfall_span_mhz=cfg_float("WATERFALL_SPAN_MHZ", 100.0),
        interval=cfg_float("HACKRF_SWEEP_INTERVAL", 3.0),
    )


def check_hackrf() -> bool:
    """Verify hackrf_sweep is on PATH and a HackRF is attached."""
    try:
        r = subprocess.run(["hackrf_info"], capture_output=True, text=True, timeout=5)
    except FileNotFoundError:
        log.error("hackrf_info not found. Install with:  sudo apt install hackrf")
        return False
    except subprocess.TimeoutExpired:
        log.error("hackrf_info timed out.")
        return False
    if r.returncode != 0 or "Found HackRF" not in r.stdout:
        log.error("No HackRF detected.\n%s\n%s", r.stdout, r.stderr)
        return False
    log.info("HackRF present:\n%s", r.stdout.splitlines()[0] if r.stdout else "?")
    return True


def run_sweep_once(cfg_: SweepConfig) -> List[Tuple[float, float]]:
    """Run a single hackrf_sweep pass and return [(freq_hz, power_db), ...]."""
    cmd = [
        "hackrf_sweep",
        "-f", f"{cfg_.low_mhz}:{cfg_.high_mhz}",
        "-w", str(cfg_.bin_hz),
        "-l", str(cfg_.lna),
        "-g", str(cfg_.vga),
        "-1",  # one-shot
    ]
    log.debug("running: %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        log.warning("hackrf_sweep timeout")
        return []
    if proc.returncode != 0:
        log.warning("hackrf_sweep rc=%d stderr=%s", proc.returncode, proc.stderr[:200])

    # CSV: date, time, hz_low, hz_high, hz_bin_width, num_samples, db_bin0, db_bin1, ...
    points: List[Tuple[float, float]] = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split(", ")
        if len(parts) < 7:
            continue
        try:
            hz_low = float(parts[2])
            hz_bin = float(parts[4])
            dbs = [float(x) for x in parts[6:]]
        except ValueError:
            continue
        for i, db in enumerate(dbs):
            freq = hz_low + hz_bin * (i + 0.5)
            points.append((freq, db))
    return points


def detect_peaks(points: List[Tuple[float, float]],
                 threshold_db: float,
                 min_gap_hz: float = 5e6) -> List[Tuple[float, float]]:
    """Return list of (freq_hz, db) peaks above (median + threshold_db)."""
    if not points:
        return []
    freqs = np.array([p[0] for p in points])
    dbs = np.array([p[1] for p in points])
    order = np.argsort(freqs)
    freqs, dbs = freqs[order], dbs[order]

    noise = float(np.median(dbs))
    mask = dbs > noise + threshold_db

    peaks: List[Tuple[float, float]] = []
    last_peak_hz = -1e12
    for f, d, m in zip(freqs, dbs, mask):
        if not m:
            continue
        if f - last_peak_hz < min_gap_hz:
            # merge into previous peak — keep the stronger
            if peaks and d > peaks[-1][1]:
                peaks[-1] = (float(f), float(d))
            continue
        peaks.append((float(f), float(d)))
        last_peak_hz = f
    return peaks


def build_waterfall_row(points: List[Tuple[float, float]],
                         center_mhz: float,
                         span_mhz: float,
                         bins_out: int = 96) -> List[float]:
    if not points:
        return []
    low = (center_mhz - span_mhz / 2) * 1e6
    high = (center_mhz + span_mhz / 2) * 1e6
    slice_pts = [(f, d) for f, d in points if low <= f <= high]
    if not slice_pts:
        return []
    freqs = np.array([p[0] for p in slice_pts])
    dbs = np.array([p[1] for p in slice_pts])
    order = np.argsort(freqs)
    freqs, dbs = freqs[order], dbs[order]

    edges = np.linspace(low, high, bins_out + 1)
    row = []
    for i in range(bins_out):
        m = (freqs >= edges[i]) & (freqs < edges[i + 1])
        row.append(float(np.mean(dbs[m])) if np.any(m) else float(np.median(dbs)))
    return row


def peak_to_detection(freq_hz: float, db: float) -> Dict:
    freq_ghz = round(freq_hz / 1e9, 4)
    proto, model, threat = classify_band(freq_ghz)
    return {
        "model": model,
        "protocol": proto,
        "threat_level": threat,
        "center_freq_ghz": freq_ghz,
        "bandwidth_mhz": 20.0,
        "rssi_dbm": round(float(db), 1),
        "snr_db": 15.0,
        "bearing_deg": 0.0,
        "distance_m": 0.0,
        "altitude_m": 0.0,
        "speed_ms": 0.0,
        "system_id": 1,
        "component_id": 1,
        "encrypted": freq_ghz >= 2.4,
        "source": "HACKRF",
    }


def main() -> int:
    logging.getLogger().setLevel(logging.INFO)
    cfg_ = load_cfg()
    if not check_hackrf():
        return 2

    client = CemaClient()
    client.login()

    # de-dup: don't spam the app with a new detection every sweep if a peak
    # persists — instead only report when peak first appears (5-min window).
    seen: Dict[int, float] = {}  # rounded_MHz → last_seen_ts
    dedup_window_s = 300

    stop = False
    def _sig(*_): nonlocal stop; stop = True
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    log.info("Sweep %d–%d MHz, bin %d Hz, LNA %d dB, VGA %d dB, thresh +%.0f dB",
             cfg_.low_mhz, cfg_.high_mhz, cfg_.bin_hz, cfg_.lna, cfg_.vga, cfg_.threshold_db)

    while not stop:
        t0 = time.time()
        points = run_sweep_once(cfg_)
        if not points:
            log.warning("empty sweep — retry in %.1fs", cfg_.interval)
            time.sleep(cfg_.interval)
            continue
        log.info("sweep done: %d bins, elapsed %.1fs", len(points), time.time() - t0)

        # 1) Publish waterfall slice
        row = build_waterfall_row(points, cfg_.waterfall_center_mhz, cfg_.waterfall_span_mhz)
        if row:
            try:
                client.post("/api/spectrum/ingest", {
                    "bins": len(row),
                    "rows": [row],
                    "center_freq_ghz": round(cfg_.waterfall_center_mhz / 1000, 4),
                    "span_mhz": cfg_.waterfall_span_mhz,
                })
            except Exception as e:
                log.warning("spectrum ingest failed: %s", e)

        # 2) Publish detections
        peaks = detect_peaks(points, cfg_.threshold_db)
        now = time.time()
        for freq_hz, db in peaks:
            key = int(round(freq_hz / 1e6))
            if key in seen and (now - seen[key]) < dedup_window_s:
                continue
            seen[key] = now
            det = peak_to_detection(freq_hz, db)
            try:
                r = client.post("/api/detections/ingest", det)
                log.info("+ live contact %.3f GHz %.1f dBm → %s (%s)",
                         freq_hz / 1e9, db, r.get("callsign", "?"), det["model"])
            except Exception as e:
                log.warning("detection ingest failed: %s", e)

        # purge old seen keys
        seen = {k: v for k, v in seen.items() if (now - v) < dedup_window_s}
        time.sleep(max(0.2, cfg_.interval))

    log.info("stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
