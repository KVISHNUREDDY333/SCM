from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from aiokafka import AIOKafkaConsumer
import asyncio
import json
import random
import datetime
import os
from dotenv import load_dotenv

load_dotenv()
router = APIRouter()

KAFKA_SERVER = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "device_data")

async def event_generator():
    """
    Generator that yields Server-Sent Events (SSE).
    If Kafka is offline, it falls back to generating mock data.
    """
    kafka_available = False
    consumer = None

    # 1. Try connecting to Kafka
    try:
        consumer = AIOKafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=KAFKA_SERVER,
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),  # Add deserializer
            auto_offset_reset='latest',
            enable_auto_commit=True,
            group_id="scm_dashboard_group"
        )
        await consumer.start()
        kafka_available = True
        print(f"Connected to Kafka topic: {KAFKA_TOPIC}")
    except Exception as e:
        print(f"Kafka Connection Failed ({e}). Switching to SIMULATION MODE.")
        kafka_available = False

    try:
        if kafka_available:
            # --- REAL KAFKA MODE ---
            async for msg in consumer:
                data = msg.value  # Already deserialized by value_deserializer
                # Ensure data has the expected fields for frontend
                formatted_data = {
                    "Shipment_Number": data.get("Shipment_Number", "Unknown"),
                    "Device": data.get("Device", "Unknown"),
                    "Temperature": data.get("Temperature", 0.0),
                    "Location": data.get("Route_Details", "Unknown"),  # Map Route_Details to Location for frontend
                    "Battery": data.get("Battery", "0%"),
                    "timestamp": data.get("timestamp", datetime.datetime.now().timestamp())
                }
                yield f"data: {json.dumps(formatted_data)}\n\n"
        else:
            # --- SIMULATION MODE ---
            routes = ['Newyork,USA', 'Chennai, India', 'Bengaluru, India', 'London,UK']
            
            while True:
                await asyncio.sleep(3)  # Match producer delay
                
                # Generate fake sensor data matching your producer format
                routefrom = random.choice(routes)
                routeto = random.choice(routes)
                while routefrom == routeto:
                    routeto = random.choice(routes)
                
                mock_data = {
                    "Shipment_Number": f"SHP-{random.randint(1000, 9999)}",
                    "Device": f"IOT-{random.randint(1150, 1158)}",
                    "Temperature": round(random.uniform(10, 40.0), 1),
                    "Location": f"{routefrom} ➝ {routeto}",  # Use Route_Details format
                    "Battery": f"{random.randint(20, 100)}%",  # Convert to percentage for frontend
                    "timestamp": datetime.datetime.now().timestamp()
                }
                
                yield f"data: {json.dumps(mock_data)}\n\n"

    except asyncio.CancelledError:
        print("❌ Client disconnected from stream.")
    except Exception as e:
        print(f"❌ Stream error: {e}")
    finally:
        # Ensure proper cleanup
        if kafka_available and consumer:
            await consumer.stop()

@router.get("/events")
async def message_stream():
    """Endpoint that frontend EventSource connects to."""
    return StreamingResponse(
        event_generator(), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control"
        }
    )