# CEMA cUAS — Product Requirements

## Original Problem Statement
> "create an app to meet the objective stated in the document. detect and broadcast signal on MAVLINK protocol, along with scripts as payload to alter physical properties of a drone like memory erase, stopping propeller or any other scenario where the drone stops functioning"

Based on:
- `CEMA_cUAS_Methodology_Zettawise.pdf` — 7-stage CEMA pipeline for MoD evaluation
- `CEMA_cUAS_Requirements_Gap_Analysis_Zettawise.pdf` — Indian Army Tech Team observations & gap analysis

## Personas
- **Command Operator** (admin) — runs the console, initiates payloads, monitors kill chain
- **Analyst** — future — reviews mission logs & audit trail

## Core Requirements (v0.9 MVP — IMPLEMENTED 2026-07-15)
- JWT-based operator login (bcrypt hashing, 12h token)
- Command Center dashboard with live RF waterfall (simulated), stat tiles, active contacts, priority targets
- Signal Analysis: 7-stage CEMA pipeline visualisation, per-target advancement, IQ / pcap file ingest
- MAVLink Console: byte-accurate v1/v2 packet crafter (CRC-16/MCRF4XX + CRC_EXTRA seeds) for real MAVLink emission, hex/binary preview, WebSocket live packet stream
- Payload Library: 10 cyber-physical payloads (FORCE LAND, RTL, FORCE DISARM, FLIGHT TERMINATION, PROPELLER STOP, MEMORY ERASE, AUTOPILOT REBOOT, RTH HOME SPOOF, GNSS DENIAL, BROADCAST TAKEDOWN) with real MAVLink COMMAND_LONG frames
- Kill Chain Tracker: Detect → Track → Identify → Decide → Defeat visual
- Mission Log: chronological audit trail
- RESTRICTED classification banner (top + bottom)
- Simulated drone detections + waterfall generator

## Architecture
- **Frontend**: React 19 + Tailwind + shadcn/ui + framer + lucide-react + sonner. Chivo / IBM Plex Sans / JetBrains Mono. Dark tactical theme.
- **Backend**: FastAPI + Motor (MongoDB async) + PyJWT + bcrypt. `/api/*` routes. WebSocket at `/api/ws/mavlink`.
- **Data**: MongoDB (users, detections, mav_packets, mission_log)

## Backlog (post-MVP)
- **P0**: Real SDR ingest via GNU Radio / UHD bridge (currently simulated)
- **P0**: DoA (Direction of Arrival) beamforming using URA/ULA arrays
- **P1**: Non-MAVLink protocol support (DJI OcuSync, ExpressLRS, Herelink)
- **P1**: GNSS spoofing engine integration
- **P1**: Multi-drone concurrent CEMA pipeline (parallel FPGA workers)
- **P1**: FPGA (RFSoC/ADRV9009) hardware acceleration hooks
- **P2**: Swarm behavior classifier (YOLOv8 + RF fingerprinting)
- **P2**: PDF mission report export
- **P2**: Role separation (Analyst / Operator / Commander)
