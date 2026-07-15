"""CEMA-Enabled cUAS backend.

Endpoints (all under /api):
  auth: /login /logout /me
  detections: /detections /detections/simulate /detections/upload /detections/{id}/cema-advance /detections/{id}/killchain-advance /detections/{id}
  spectrum: /spectrum/waterfall
  mavlink: /mavlink/craft /mavlink/broadcast /mavlink/packets  (ws /ws/mavlink)
  payloads: /payloads /payloads/deploy
  logs:  /logs
"""
from __future__ import annotations

from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import asyncio
import base64
import binascii
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import bcrypt
import jwt
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field
from starlette.middleware.cors import CORSMiddleware

from mavlink_codec import (
    build_packet_v1,
    build_packet_v2,
    build_command_long_payload,
    describe_packet,
    hexdump,
    CRC_EXTRA,
)
from payload_library import PAYLOAD_CATALOG, PAYLOAD_BUILDERS, get_payload_by_id
from simulator import (
    CEMA_STAGES,
    KILL_CHAIN,
    advance_cema,
    advance_kill_chain,
    generate_waterfall,
    new_detection,
    parse_iq_file_stub,
)

# ---------- Config ----------
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGO = "HS256"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "operator@cema.mil")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "cema@2026")

# ---------- Mongo ----------
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

# ---------- App ----------
app = FastAPI(title="CEMA cUAS Operator Console")
api = APIRouter(prefix="/api")
bearer = HTTPBearer(auto_error=False)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("cema")


# =====================================================================
# Auth helpers
# =====================================================================
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def create_access_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id, "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
) -> Dict[str, Any]:
    if creds is None or not creds.credentials:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
    if payload.get("type") != "access":
        raise HTTPException(401, "Wrong token type")
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(401, "User not found")
    return user


# =====================================================================
# Startup: seed admin, indexes
# =====================================================================
@app.on_event("startup")
async def startup() -> None:
    await db.users.create_index("email", unique=True)
    existing = await db.users.find_one({"email": ADMIN_EMAIL})
    if existing is None:
        await db.users.insert_one({
            "id": str(uuid.uuid4()),
            "email": ADMIN_EMAIL,
            "name": "Command Operator",
            "role": "admin",
            "clearance": "RESTRICTED",
            "password_hash": hash_password(ADMIN_PASSWORD),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("Seeded admin operator.")
    elif not verify_password(ADMIN_PASSWORD, existing["password_hash"]):
        await db.users.update_one(
            {"email": ADMIN_EMAIL},
            {"$set": {"password_hash": hash_password(ADMIN_PASSWORD)}},
        )
        logger.info("Admin password hash refreshed.")

    # Seed initial fleet of detections (idempotent-ish; only if empty)
    count = await db.detections.count_documents({})
    if count == 0:
        for _ in range(6):
            det = new_detection()
            await db.detections.insert_one(det)
        logger.info("Seeded initial detections.")


@app.on_event("shutdown")
async def shutdown() -> None:
    client.close()


# =====================================================================
# Pydantic
# =====================================================================
class LoginBody(BaseModel):
    email: EmailStr
    password: str


class MavlinkCraftBody(BaseModel):
    version: str = Field("v2", pattern="^(v1|v2)$")
    system_id: int = 255
    component_id: int = 190
    sequence: int = 0
    message_id: int = 76  # COMMAND_LONG
    target_system: int = 1
    target_component: int = 1
    command: int = 21  # NAV_LAND
    param1: float = 0.0
    param2: float = 0.0
    param3: float = 0.0
    param4: float = 0.0
    param5: float = 0.0
    param6: float = 0.0
    param7: float = 0.0


class DeployPayloadBody(BaseModel):
    payload_id: str
    target_detection_id: Optional[str] = None
    broadcast: bool = False


# =====================================================================
# WebSocket manager for live MAVLink packet feed
# =====================================================================
class WSManager:
    def __init__(self) -> None:
        self.clients: List[WebSocket] = []
        self.lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self.lock:
            self.clients.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.clients:
            self.clients.remove(ws)

    async def broadcast_json(self, data: Dict) -> None:
        stale: List[WebSocket] = []
        for ws in list(self.clients):
            try:
                await ws.send_json(data)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)


ws_manager = WSManager()


# =====================================================================
# Mission log helper
# =====================================================================
async def log_event(kind: str, message: str, meta: Optional[Dict] = None,
                    actor: Optional[str] = None) -> Dict:
    entry = {
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "message": message,
        "actor": actor or "SYSTEM",
        "meta": meta or {},
    }
    await db.mission_log.insert_one(entry.copy())
    return entry


# =====================================================================
# Routes: Auth
# =====================================================================
@api.post("/auth/login")
async def login(body: LoginBody):
    user = await db.users.find_one({"email": body.email.lower()})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    token = create_access_token(user["id"], user["email"])
    await log_event("AUTH", f"Operator login: {user['email']}", actor=user["email"])
    return {
        "token": token,
        "user": {"id": user["id"], "email": user["email"],
                 "name": user["name"], "role": user["role"],
                 "clearance": user.get("clearance", "RESTRICTED")},
    }


@api.get("/auth/me")
async def me(user: Dict = Depends(get_current_user)):
    return user


@api.post("/auth/logout")
async def logout(user: Dict = Depends(get_current_user)):
    await log_event("AUTH", f"Operator logout: {user['email']}", actor=user["email"])
    return {"ok": True}


# =====================================================================
# Routes: Detections
# =====================================================================
@api.get("/detections")
async def list_detections(user: Dict = Depends(get_current_user)):
    docs = await db.detections.find({}, {"_id": 0}).to_list(500)
    return docs


@api.get("/detections/{det_id}")
async def get_detection(det_id: str, user: Dict = Depends(get_current_user)):
    doc = await db.detections.find_one({"id": det_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Detection not found")
    return doc


@api.post("/detections/simulate")
async def simulate_detection(user: Dict = Depends(get_current_user)):
    det = new_detection()
    await db.detections.insert_one(det.copy())
    await log_event("DETECTION",
                    f"New contact {det['callsign']} ({det['model']}) — {det['threat_level']}",
                    meta={"detection_id": det["id"]}, actor=user["email"])
    det.pop("_id", None)
    return det


@api.post("/detections/upload")
async def upload_iq(file: UploadFile = File(...),
                    user: Dict = Depends(get_current_user)):
    contents = await file.read()
    meta = parse_iq_file_stub(file.filename or "capture.iq", len(contents))
    det = new_detection()
    det["source"] = "UPLOAD"
    det["upload_meta"] = meta
    det["upload_filename"] = file.filename
    det["upload_size_bytes"] = len(contents)
    await db.detections.insert_one(det.copy())
    await log_event(
        "UPLOAD",
        f"IQ/pcap ingested: {file.filename} ({len(contents)} bytes) → contact {det['callsign']}",
        meta={"detection_id": det["id"], **meta},
        actor=user["email"],
    )
    det.pop("_id", None)
    return det


@api.post("/detections/{det_id}/cema-advance")
async def cema_advance(det_id: str, user: Dict = Depends(get_current_user)):
    doc = await db.detections.find_one({"id": det_id})
    if not doc:
        raise HTTPException(404, "Detection not found")
    doc = advance_cema(doc)
    await db.detections.replace_one({"id": det_id}, doc)
    await log_event("CEMA",
                    f"{doc['callsign']} advanced to {doc['cema_stage']}",
                    meta={"detection_id": det_id, "stage": doc["cema_stage"]},
                    actor=user["email"])
    doc.pop("_id", None)
    return doc


@api.post("/detections/{det_id}/killchain-advance")
async def kc_advance(det_id: str, user: Dict = Depends(get_current_user)):
    doc = await db.detections.find_one({"id": det_id})
    if not doc:
        raise HTTPException(404, "Detection not found")
    doc = advance_kill_chain(doc)
    await db.detections.replace_one({"id": det_id}, doc)
    await log_event("KILLCHAIN",
                    f"{doc['callsign']} → {doc['kill_chain_stage']}",
                    meta={"detection_id": det_id, "stage": doc["kill_chain_stage"]},
                    actor=user["email"])
    doc.pop("_id", None)
    return doc


@api.delete("/detections/{det_id}")
async def delete_detection(det_id: str, user: Dict = Depends(get_current_user)):
    res = await db.detections.delete_one({"id": det_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Detection not found")
    await log_event("DETECTION", f"Contact removed {det_id}", actor=user["email"])
    return {"ok": True}


# =====================================================================
# Routes: RF Spectrum
# =====================================================================
@api.get("/spectrum/waterfall")
async def spectrum_waterfall(bins: int = 96, rows: int = 24,
                             user: Dict = Depends(get_current_user)):
    return {"bins": bins, "rows": [generate_waterfall(bins) for _ in range(rows)]}


# =====================================================================
# Routes: MAVLink crafting / broadcast
# =====================================================================
def _craft(body: MavlinkCraftBody) -> bytes:
    if body.message_id == 76:  # COMMAND_LONG payload
        payload = build_command_long_payload(
            body.target_system, body.target_component, body.command,
            0, body.param1, body.param2, body.param3, body.param4,
            body.param5, body.param6, body.param7,
        )
    else:
        # For other message ids, produce a synthetic payload of 8 zero bytes
        # (real-world crafting would require per-message schemas).
        if body.message_id not in CRC_EXTRA:
            raise HTTPException(400, f"CRC_EXTRA not registered for msgid={body.message_id}")
        payload = b"\x00" * 8
    if body.version == "v1":
        if body.message_id > 255:
            raise HTTPException(400, "MAVLink v1 supports msgid <= 255")
        return build_packet_v1(body.message_id, payload,
                               system_id=body.system_id,
                               component_id=body.component_id,
                               sequence=body.sequence)
    return build_packet_v2(body.message_id, payload,
                           system_id=body.system_id,
                           component_id=body.component_id,
                           sequence=body.sequence)


@api.post("/mavlink/craft")
async def craft_packet(body: MavlinkCraftBody, user: Dict = Depends(get_current_user)):
    frame = _craft(body)
    return {
        "hex": frame.hex().upper(),
        "base64": base64.b64encode(frame).decode(),
        "length": len(frame),
        "hexdump": hexdump(frame),
        "decoded": describe_packet(frame),
    }


@api.post("/mavlink/broadcast")
async def broadcast_packet(body: MavlinkCraftBody, user: Dict = Depends(get_current_user)):
    frame = _craft(body)
    pkt = {
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "hex": frame.hex().upper(),
        "length": len(frame),
        "system_id": body.system_id,
        "component_id": body.component_id,
        "target_system": body.target_system,
        "message_id": body.message_id,
        "command": body.command if body.message_id == 76 else None,
        "actor": user["email"],
        "hexdump": hexdump(frame),
        "decoded": describe_packet(frame),
    }
    await db.mav_packets.insert_one(pkt.copy())
    pkt.pop("_id", None)
    await ws_manager.broadcast_json({"type": "packet", "packet": pkt})
    await log_event("MAVLINK",
                    f"Broadcast msgid={body.message_id} cmd={body.command} → sys={body.target_system}",
                    meta={"packet_id": pkt["id"], "length": len(frame)},
                    actor=user["email"])
    return pkt


@api.get("/mavlink/packets")
async def list_packets(limit: int = 100, user: Dict = Depends(get_current_user)):
    docs = await db.mav_packets.find({}, {"_id": 0}).sort("ts", -1).to_list(limit)
    return docs


@app.websocket("/api/ws/mavlink")
async def ws_mavlink(ws: WebSocket):
    # Simple token check via query param
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=1008)
        return
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        if payload.get("type") != "access":
            await ws.close(code=1008)
            return
    except jwt.PyJWTError:
        await ws.close(code=1008)
        return
    await ws_manager.connect(ws)
    try:
        await ws.send_json({"type": "hello", "ts": datetime.now(timezone.utc).isoformat()})
        while True:
            # keep the connection open; ignore client messages
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(ws)


# =====================================================================
# Routes: Payload library
# =====================================================================
@api.get("/payloads")
async def list_payloads(user: Dict = Depends(get_current_user)):
    return [p.to_dict() for p in PAYLOAD_CATALOG]


@api.post("/payloads/deploy")
async def deploy_payload(body: DeployPayloadBody,
                         user: Dict = Depends(get_current_user)):
    spec = get_payload_by_id(body.payload_id)
    if not spec:
        raise HTTPException(404, "Unknown payload id")
    builder = PAYLOAD_BUILDERS.get(body.payload_id)
    if not builder:
        raise HTTPException(500, "No builder registered for this payload")

    target_sys = 0
    target_comp = 0
    detection = None
    if not body.broadcast:
        if not body.target_detection_id:
            raise HTTPException(400, "target_detection_id required unless broadcast=True")
        detection = await db.detections.find_one({"id": body.target_detection_id})
        if not detection:
            raise HTTPException(404, "Target detection not found")
        target_sys = detection.get("system_id", 1)
        target_comp = detection.get("component_id", 1)

    frame = builder(target_sys, target_comp, 0) if not body.broadcast else builder(seq=0)
    pkt = {
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "hex": frame.hex().upper(),
        "length": len(frame),
        "payload_id": spec.id,
        "payload_name": spec.name,
        "severity": spec.severity,
        "broadcast": body.broadcast,
        "target_detection_id": body.target_detection_id,
        "target_system": target_sys,
        "hexdump": hexdump(frame),
        "decoded": describe_packet(frame),
        "actor": user["email"],
    }
    await db.mav_packets.insert_one(pkt.copy())
    pkt.pop("_id", None)
    await ws_manager.broadcast_json({"type": "packet", "packet": pkt})
    await log_event(
        "PAYLOAD",
        f"Deployed {spec.name} ({spec.severity}) on {'BROADCAST' if body.broadcast else detection.get('callsign','?')}",
        meta={"payload_id": spec.id, "packet_id": pkt["id"], "broadcast": body.broadcast,
              "target_detection_id": body.target_detection_id},
        actor=user["email"],
    )

    # If targeting a specific drone, mark it neutralized after payload deploy
    if detection is not None:
        await db.detections.update_one(
            {"id": detection["id"]},
            {"$set": {
                "status": "NEUTRALIZED",
                "kill_chain_stage": "DEFEAT",
                "kill_chain_index": len(KILL_CHAIN) - 1,
                "cema_stage": "EXPLOIT",
                "cema_stage_index": len(CEMA_STAGES) - 1,
                "last_seen": datetime.now(timezone.utc).isoformat(),
                "last_payload": spec.name,
            }},
        )
    elif body.broadcast:
        await db.detections.update_many(
            {"status": "ACTIVE"},
            {"$set": {"status": "NEUTRALIZED",
                      "kill_chain_stage": "DEFEAT",
                      "kill_chain_index": len(KILL_CHAIN) - 1,
                      "last_payload": spec.name}},
        )

    return pkt


# =====================================================================
# Routes: Mission log
# =====================================================================
@api.get("/logs")
async def list_logs(limit: int = 200, user: Dict = Depends(get_current_user)):
    docs = await db.mission_log.find({}, {"_id": 0}).sort("ts", -1).to_list(limit)
    return docs


# =====================================================================
# Public health
# =====================================================================
@api.get("/")
async def root():
    return {"service": "cema-cuas", "status": "online",
            "cema_stages": CEMA_STAGES, "kill_chain": KILL_CHAIN}


# ---------- Register router + CORS ----------
app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
