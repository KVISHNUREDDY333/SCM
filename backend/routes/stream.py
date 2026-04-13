from fastapi import APIRouter, Query, HTTPException, Cookie
from fastapi.responses import StreamingResponse
from backend.auth.jwt_handler import decodeJWT
from typing import Optional, Set
from aiokafka import AIOKafkaConsumer
import asyncio
import json
import random
import uuid
import datetime
import os
from backend.config.database import (
    broadcast_collection, 
    shipment_collection, 
    device_stream_collection,
    user_collection
)
from dotenv import load_dotenv

load_dotenv()
router = APIRouter()

KAFKA_SERVER = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "device_data")

# --- CONCURRENCY OPTIMIZATION: GLOBAL BROADCASTER ---
# This ensures only ONE Kafka listener (or simulator) runs, regardless of how many admins watch.
class TelemetryBroadcaster:
    def __init__(self):
        self._subscribers: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._running_task = None

    async def subscribe(self) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers.add(queue)
            if not self._running_task:
                self._running_task = asyncio.create_task(self._main_broadcaster_loop())
        return queue

    async def unsubscribe(self, queue: asyncio.Queue):
        async with self._lock:
            self._subscribers.remove(queue)
            if not self._subscribers and self._running_task:
                self._running_task.cancel()
                self._running_task = None

    async def _main_broadcaster_loop(self):
        """The single master loop for data ingest."""
        kafka_available = False
        consumer = None
        
        try:
            # Attempt Kafka Connection
            try:
                consumer = AIOKafkaConsumer(
                    KAFKA_TOPIC,
                    bootstrap_servers=KAFKA_SERVER,
                    value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                    auto_offset_reset='latest',
                    enable_auto_commit=False,
                    group_id=f"scm_master_broadcaster_{str(uuid.uuid4())[:8]}"
                )
                await consumer.start()
                kafka_available = True
                print("Broadcaster: KAFKA LINK ESTABLISHED.")
            except Exception:
                print("Broadcaster: KAFKA OFFLINE. Simulation Mode Activated.")

            if kafka_available:
                async for msg in consumer:
                    await self._process_and_broadcast(msg.value)
            else:
                # Simulation Logic
                routes = ['Newyork,USA', 'Chennai, India', 'Bengaluru, India', 'London,UK']
                while True:
                    await asyncio.sleep(1) # Frequency
                    routefrom, routeto = random.sample(routes, 2)
                    mock_data = {
                        "Shipment_Number": f"SHP-{random.randint(1000, 9999)}",
                        "Device": f"IOT-{random.randint(1150, 1158)}",
                        "Temperature": round(random.uniform(10, 40.0), 1),
                        "Battery": f"{random.randint(20, 100)}%",
                        "Location": f"{routefrom} ➝ {routeto}",
                        "Route_Details": f"{routefrom} ➝ {routeto}",
                        "timestamp": datetime.datetime.now().timestamp(),
                        "is_kafka": True,
                        "created_by": "KAFKA_SYSTEM"
                    }
                    await self._process_and_broadcast(mock_data)

        except asyncio.CancelledError:
            print("Broadcaster: Master task shutting down.")
        finally:
            if consumer:
                await consumer.stop()

    async def _process_and_broadcast(self, data):
        """Process incoming data, save to DB ONCE, and push to all queues."""
        # Standardize
        formatted = {
            "Shipment_Number": data.get("Shipment_Number", "Unknown"),
            "Device": data.get("Device", "Unknown"),
            "Temperature": data.get("Temperature", 0.0),
            "Location": data.get("Location") or data.get("Route_Details", "Unknown"),
            "Route_Details": data.get("Route_Details") or data.get("Location", "Unknown"),
            "Battery": data.get("Battery", "0%"),
            "timestamp": data.get("timestamp") or datetime.datetime.now().timestamp(),
            "is_kafka": True
        }

        # Save to DB (Singleton Write Strategy)
        await shipment_collection.update_one(
            {"Shipment_Number": formatted["Shipment_Number"]},
            {"$set": formatted},
            upsert=True
        )
        await device_stream_collection.insert_one(formatted.copy())

        # Check Broadcasts
        now = datetime.datetime.now()
        broadcast = await broadcast_collection.find_one({"expires_at": {"$gt": now}})
        broadcast_pkg = None
        if broadcast:
            broadcast_pkg = {"type": "broadcast", "content": broadcast['message']}

        # Push to all active sub-processes
        async with self._lock:
            for q in self._subscribers:
                try:
                    q.put_nowait(formatted)
                    if broadcast_pkg: q.put_nowait(broadcast_pkg)
                except asyncio.QueueFull:
                    pass

# Singleton Instance
broadcaster = TelemetryBroadcaster()

@router.get("/events")
async def message_stream(
    token: Optional[str] = Query(None), 
    scm_token: Optional[str] = Cookie(None)
):
    active_token = scm_token or token
    decoded = decodeJWT(active_token)
    if not active_token or not decoded:
        raise HTTPException(status_code=403, detail="Unauthenticated Stream Request")
    
    user = await user_collection.find_one({"email": decoded.get("email")})
    if not user or not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin privileges required for stream access.")

    async def stream():
        queue = await broadcaster.subscribe()
        try:
            while True:
                data = await queue.get()
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await broadcaster.unsubscribe(queue)

    return StreamingResponse(
        stream(), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no" # Critical for Nginx/Proxy performance
        }
    )