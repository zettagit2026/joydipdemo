"""Simulated drone detection + RF spectrum generators for the cUAS console."""
from __future__ import annotations
import random
import uuid
import math
from datetime import datetime, timezone
from typing import Dict, List

DRONE_MODELS = [
    ("DJI Mavic 3", "DJI OcuSync 3.0", 2.4, 5.8),
    ("DJI Phantom 4", "DJI Lightbridge", 2.4, 5.8),
    ("Autel EVO II", "Autel proprietary", 2.4, 5.8),
    ("Skydio X2", "MAVLink v2", 5.8, 900e-3),
    ("Parrot Anafi", "MAVLink v2", 2.4, 5.8),
    ("Custom FPV", "ExpressLRS", 0.915, 2.4),
    ("Shahed-style loiter", "MAVLink v1", 0.433, 0.868),
    ("Bayraktar-class", "Encrypted C2", 1.2, 5.4),
]

CEMA_STAGES = ["CAPTURE", "ANALYZE", "SEGREGATE", "DEMODULATE",
               "DECODE", "DECRYPT", "EXPLOIT"]

KILL_CHAIN = ["DETECT", "TRACK", "IDENTIFY", "DECIDE", "DEFEAT"]


def _rand_freq(base_ghz: float) -> float:
    return round(base_ghz + random.uniform(-0.05, 0.05), 4)


def new_detection() -> Dict:
    model, protocol, band_a, band_b = random.choice(DRONE_MODELS)
    center_freq = _rand_freq(band_a)
    threat = random.choices(
        ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
        weights=[15, 35, 30, 20],
    )[0]
    swarm_id = None
    if random.random() < 0.35:
        swarm_id = f"SWARM-{random.randint(1,3):02d}"

    return {
        "id": str(uuid.uuid4()),
        "callsign": f"UAV-{random.randint(1000,9999)}",
        "model": model,
        "protocol": protocol,
        "swarm_id": swarm_id,
        "threat_level": threat,
        "center_freq_ghz": center_freq,
        "bandwidth_mhz": round(random.uniform(10, 40), 2),
        "rssi_dbm": round(random.uniform(-95, -55), 1),
        "snr_db": round(random.uniform(4, 25), 1),
        "bearing_deg": round(random.uniform(0, 360), 1),
        "distance_m": round(random.uniform(120, 4200), 1),
        "altitude_m": round(random.uniform(30, 900), 1),
        "speed_ms": round(random.uniform(2, 35), 1),
        "system_id": random.randint(1, 250),
        "component_id": 1,
        "encrypted": random.random() < 0.55,
        "cema_stage": "CAPTURE",
        "cema_stage_index": 0,
        "kill_chain_stage": "DETECT",
        "kill_chain_index": 0,
        "status": "ACTIVE",
        "first_seen": datetime.now(timezone.utc).isoformat(),
        "last_seen": datetime.now(timezone.utc).isoformat(),
    }


def advance_cema(det: Dict) -> Dict:
    idx = det.get("cema_stage_index", 0)
    if idx < len(CEMA_STAGES) - 1:
        det["cema_stage_index"] = idx + 1
        det["cema_stage"] = CEMA_STAGES[idx + 1]
    det["last_seen"] = datetime.now(timezone.utc).isoformat()
    return det


def advance_kill_chain(det: Dict) -> Dict:
    idx = det.get("kill_chain_index", 0)
    if idx < len(KILL_CHAIN) - 1:
        det["kill_chain_index"] = idx + 1
        det["kill_chain_stage"] = KILL_CHAIN[idx + 1]
    det["last_seen"] = datetime.now(timezone.utc).isoformat()
    return det


def generate_waterfall(bins: int = 128) -> List[float]:
    """Produce one row of an RF spectrum waterfall (dBm values)."""
    row = []
    peaks = [random.randint(10, bins - 10) for _ in range(random.randint(2, 5))]
    for i in range(bins):
        base = -90 + random.uniform(-3, 3)
        for p in peaks:
            base += 40 * math.exp(-((i - p) ** 2) / (2 * random.uniform(2, 8) ** 2))
        row.append(round(base, 1))
    return row


def parse_iq_file_stub(filename: str, size_bytes: int) -> Dict:
    """A stub 'parser' that returns plausible metadata for uploaded IQ / pcap files."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    if ext == "pcap":
        return {
            "file_type": "PCAP",
            "packets_estimated": max(1, size_bytes // 96),
            "protocols_detected": random.sample(
                ["MAVLink v2", "MAVLink v1", "DJI OcuSync", "MQTT", "ExpressLRS"],
                k=random.randint(1, 3),
            ),
            "duration_s": round(size_bytes / (500 * 1024), 2),
        }
    return {
        "file_type": "IQ",
        "sample_rate_msps": random.choice([2, 5, 10, 20, 25]),
        "samples_estimated": max(1, size_bytes // 8),
        "center_freq_ghz": round(random.uniform(0.4, 5.9), 3),
        "modulation_guess": random.choice(["FHSS", "OFDM", "GFSK", "QPSK"]),
        "duration_s": round(size_bytes / (10 * 1024 * 1024), 2),
    }
