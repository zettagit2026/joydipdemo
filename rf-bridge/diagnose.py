#!/usr/bin/env python3
"""HackRF → CEMA end-to-end diagnostic.

Run this instead of guessing when the HackRF pill won't turn green.
Checks in order:
  1. hackrf_info      — HackRF detected + firmware ok
  2. hackrf_sweep     — a real sweep is produced + parseable
  3. Backend login    — creds work, backend reachable
  4. /api/spectrum/ingest  — waterfall push accepted
  5. /api/detections/ingest — detection push accepted
  6. /api/spectrum/waterfall — reads back HACKRF source

Emits a PASS/FAIL matrix at the end.
"""
from __future__ import annotations

import subprocess
import sys
import time
from typing import List, Tuple

import numpy as np

from common import CemaClient, cfg_float, cfg_int
from hackrf_scanner import run_sweep_once, build_waterfall_row, detect_peaks, SweepConfig

OK = "\033[32m✓ PASS\033[0m"
FAIL = "\033[31m✗ FAIL\033[0m"
WARN = "\033[33m! WARN\033[0m"

results: List[Tuple[str, str, str]] = []


def step(name: str, passed: bool, detail: str = "") -> None:
    tag = OK if passed else FAIL
    print(f"  {tag}  {name}")
    if detail:
        print(f"           {detail}")
    results.append((name, "PASS" if passed else "FAIL", detail))


def warn(name: str, detail: str) -> None:
    print(f"  {WARN}  {name}")
    print(f"           {detail}")
    results.append((name, "WARN", detail))


def main() -> int:
    print("\n=== CEMA HackRF diagnostic ===\n")

    # 1. HackRF hardware check
    print("[1] HackRF hardware")
    try:
        r = subprocess.run(["hackrf_info"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and "Found HackRF" in r.stdout:
            step("hackrf_info", True, r.stdout.splitlines()[0])
        else:
            step("hackrf_info", False,
                 f"rc={r.returncode} stdout={r.stdout[:120]!r} stderr={r.stderr[:120]!r}")
            print("\nFIX: sudo apt install hackrf ; replug USB ; check `lsusb | grep 1d50`")
            return 2
    except FileNotFoundError:
        step("hackrf_info", False, "binary not found")
        print("\nFIX: sudo apt install hackrf")
        return 2

    # 2. Sweep + parse
    print("\n[2] hackrf_sweep + CSV parse")
    swc = SweepConfig(
        low_mhz=cfg_int("HACKRF_SWEEP_LOW_MHZ", 2400),
        high_mhz=cfg_int("HACKRF_SWEEP_HIGH_MHZ", 2500),  # narrow range for speed
        bin_hz=cfg_int("HACKRF_BIN_HZ", 1_000_000),
        lna=cfg_int("HACKRF_LNA_GAIN", 32),
        vga=cfg_int("HACKRF_VGA_GAIN", 30),
        threshold_db=cfg_float("HACKRF_DETECT_THRESHOLD_DB", 20.0),
        waterfall_center_mhz=cfg_float("WATERFALL_CENTER_MHZ", 2440.0),
        waterfall_span_mhz=cfg_float("WATERFALL_SPAN_MHZ", 100.0),
        interval=0.0,
    )
    print(f"     sweep {swc.low_mhz}–{swc.high_mhz} MHz…")
    t0 = time.time()
    pts = run_sweep_once(swc)
    dur = time.time() - t0
    step("sweep produced points", bool(pts), f"{len(pts)} points in {dur:.1f}s")
    if not pts:
        print("\nFIX: try `sudo hackrf_sweep -f 2400:2500 -1 -w 1000000` manually; if that "
              "works, add your user to plugdev group.")
        return 2

    dbs = np.array([p[1] for p in pts])
    step("dBm range plausible",
         -120 <= float(dbs.min()) and float(dbs.max()) <= 40,
         f"min={dbs.min():.1f}  median={np.median(dbs):.1f}  max={dbs.max():.1f}")

    row = build_waterfall_row(pts, swc.waterfall_center_mhz, swc.waterfall_span_mhz)
    step("waterfall row built",
         len(row) > 0,
         f"{len(row)} bins @ {swc.waterfall_center_mhz}±{swc.waterfall_span_mhz/2} MHz")

    peaks = detect_peaks(pts, swc.threshold_db)
    if not peaks:
        warn("peaks over threshold",
             f"0 peaks over median+{swc.threshold_db:.0f}dB — "
             "lower HACKRF_DETECT_THRESHOLD_DB or increase gain")
    else:
        step("peaks over threshold", True,
             f"{len(peaks)} peaks; strongest {peaks[0][0]/1e9:.3f} GHz @ {peaks[0][1]:.1f} dB")

    # 3. Backend login
    print("\n[3] Backend connectivity")
    try:
        client = CemaClient()
        tok = client.login()
        step("POST /api/auth/login", bool(tok), f"base={client.base}")
    except Exception as e:
        step("POST /api/auth/login", False, str(e)[:200])
        print(f"\nFIX: check CEMA_API_URL / CEMA_EMAIL / CEMA_PASSWORD in .env")
        return 2

    # 4. Spectrum ingest
    print("\n[4] Spectrum ingest")
    try:
        r = client.post("/api/spectrum/ingest", {
            "bins": len(row) or 8,
            "rows": [row or [-80.0] * 8],
            "center_freq_ghz": round(swc.waterfall_center_mhz / 1000, 4),
            "span_mhz": swc.waterfall_span_mhz,
        })
        step("POST /api/spectrum/ingest", bool(r.get("ok")), str(r))
    except Exception as e:
        step("POST /api/spectrum/ingest", False, str(e)[:200])
        return 2

    # 5. Detection ingest
    print("\n[5] Detection ingest")
    try:
        r = client.post("/api/detections/ingest", {
            "model": "HackRF Self-Test",
            "protocol": "diagnostic",
            "threat_level": "LOW",
            "center_freq_ghz": 2.44,
            "rssi_dbm": -70,
            "system_id": 254,
            "source": "HACKRF",
        })
        step("POST /api/detections/ingest", bool(r.get("id")),
             f"callsign={r.get('callsign')} source={r.get('source')}")
    except Exception as e:
        step("POST /api/detections/ingest", False, str(e)[:200])
        return 2

    # 6. Read back and confirm source flag
    print("\n[6] Waterfall readback")
    try:
        import requests
        rr = requests.get(f"{client.base}/api/spectrum/waterfall?bins=8&rows=1",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        rr.raise_for_status()
        data = rr.json()
        step("GET /api/spectrum/waterfall source flag",
             data.get("source") == "HACKRF",
             f"source={data.get('source')}  (must be HACKRF within 10s of ingest)")
    except Exception as e:
        step("GET /api/spectrum/waterfall", False, str(e)[:200])
        return 2

    # Summary
    print("\n=== Summary ===")
    for n, s, d in results:
        colour = OK if s == "PASS" else (WARN if s == "WARN" else FAIL)
        print(f"  {colour}  {n}")
    fails = [r for r in results if r[1] == "FAIL"]
    if fails:
        print("\n\033[31mResult: FAIL — see rows above.\033[0m")
        return 1
    print("\n\033[32mResult: HackRF end-to-end healthy. The UI should show ● HACKRF LIVE.\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
