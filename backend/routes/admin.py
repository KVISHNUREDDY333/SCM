from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from backend.config.database import (
    user_collection, 
    shipment_collection, 
    database, 
    audit_collection, 
    broadcast_collection, 
    settings_collection, 
    direct_messages_collection,
    device_stream_collection
)
from backend.middleware.security import VerifyAdmin, JWTBearer
from backend.models.admin_models import UserUpdateSchema, AuditLogSchema, BroadcastSchema, MaintenanceSchema, DirectMessageSchema
from backend.auth.jwt_handler import decodeJWT
from bson import ObjectId
import os
import socket
import csv
import io
from datetime import datetime, timedelta

router = APIRouter()
SUPER_ADMIN_EMAIL = "vishnureddyk3333@gmail.com"

async def log_admin_action(admin_email: str, action: str, details: str):
    """Helper to record administrative actions for the audit trail."""
    log = {
        "admin_email": admin_email,
        "action": action,
        "details": details,
        "timestamp": datetime.now()
    }
    await audit_collection.insert_one(log)

@router.get("/admin/stats", dependencies=[Depends(VerifyAdmin())])
async def get_admin_stats():
    """Returns granular global system statistics with explicit error safety."""
    
    async def get_metrics_optimized(query):
        try:
            pipeline = [
                {"$match": query},
                {"$group": {
                    "_id": None,
                    "total": {"$sum": 1},
                    "transit": {"$sum": {"$cond": [{"$regexMatch": {"input": {"$ifNull": ["$Status", "In Transit"]}, "regex": "Transit", "options": "i"}}, 1, 0]}},
                    "delayed": {"$sum": {"$cond": [{"$regexMatch": {"input": {"$ifNull": ["$Status", ""]}, "regex": "Delayed", "options": "i"}}, 1, 0]}},
                    "delivered": {"$sum": {"$cond": [{"$regexMatch": {"input": {"$ifNull": ["$Status", ""]}, "regex": "Delivered", "options": "i"}}, 1, 0]}},
                    "cancelled": {"$sum": {"$cond": [{"$regexMatch": {"input": {"$ifNull": ["$Status", ""]}, "regex": "Cancelled", "options": "i"}}, 1, 0]}},
                    "devices": {"$addToSet": "$Device"}
                }}
            ]
            cursor = shipment_collection.aggregate(pipeline)
            result = await cursor.to_list(length=1)
            
            if not result:
                return {"total": 0, "transit": 0, "delayed": 0, "delivered": 0, "cancelled": 0, "devices": 0}
            
            data = result[0]
            return {
                "total": int(data.get("total", 0)),
                "transit": int(data.get("transit", 0)),
                "delayed": int(data.get("delayed", 0)),
                "delivered": int(data.get("delivered", 0)),
                "cancelled": int(data.get("cancelled", 0)),
                "devices": int(len(data.get("devices", [])))
            }
        except Exception as e:
            print(f"Metrics Error: {e}")
            return {"total": 0, "transit": 0, "delayed": 0, "delivered": 0, "cancelled": 0, "devices": 0}

    user_query = {"$or": [{"is_kafka": {"$exists": False}}, {"is_kafka": False}]}
    kafka_query = {"is_kafka": True}

    try:
        results = await asyncio.gather(
            get_metrics_optimized(user_query),
            get_metrics_optimized(kafka_query),
            user_collection.count_documents({}),
            device_stream_collection.count_documents({})
        )
        
        user_m, kafka_m, u_count, t_count = results
        
        # Override Kafka with absolute telemetry counts
        kafka_m["total"] = t_count
        kafka_m["delivered"] = t_count

        return {
            "total_users": int(u_count),
            "user_shipments": user_m,
            "kafka_shipments": kafka_m,
            "total_shipments": int(user_m["total"] + kafka_m["total"]),
            "active_devices": int(user_m["devices"] + kafka_m["devices"])
        }
    except Exception as e:
        print(f"Global Stats Error: {e}")
        return {"total_users": 0, "user_shipments": {}, "kafka_shipments": {}, "total_shipments": 0, "active_devices": 0}

@router.get("/admin/users", dependencies=[Depends(VerifyAdmin())])
async def get_all_users():
    """Returns a list of all registered users."""
    users = []
    async for user in user_collection.find({}, {"password": 0}):
        user["_id"] = str(user["_id"])
        users.append(user)
    return users

@router.delete("/admin/users/{user_id}", dependencies=[Depends(VerifyAdmin())])
async def delete_user(user_id: str, token: str = Depends(JWTBearer())):
    """Deletes a user account. STRICT ACCESS: SUPER ADMIN ONLY."""
    try:
        obj_id = ObjectId(user_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid User ID format")

    decoded = decodeJWT(token)
    current_admin_email = decoded.get("email")
    if current_admin_email != SUPER_ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Only the main admin can delete users.")

    result = await user_collection.delete_one({"_id": obj_id})
    if result.deleted_count == 1:
        # LOG ACTION
        await log_admin_action(current_admin_email, "DELETE_USER", f"Permanently purged user registry entry ID {user_id}")
        return {"message": "User purged by Super Admin."}
    
    raise HTTPException(status_code=404, detail="User not found")

@router.put("/admin/users/{user_id}", dependencies=[Depends(VerifyAdmin())])
async def update_user(user_id: str, payload: UserUpdateSchema, token: str = Depends(JWTBearer())):
    """Updates a user's role or username. Prevents self-demotion."""
    try:
        obj_id = ObjectId(user_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid User ID format")

    decoded = decodeJWT(token)
    current_user_email = decoded.get("email")

    user = await user_collection.find_one({"_id": obj_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # --- HIERARCHY ENFORCEMENT ---
    # Only the Super Admin can promote/demote or modify access roles.
    if payload.is_admin is not None or payload.role is not None:
        if current_user_email != SUPER_ADMIN_EMAIL:
             raise HTTPException(status_code=403, detail="Insufficient Administrative Tier to manage roles.")

    # SELF-PROTECTION: Don't allow active admin to demote themselves
    if user["email"] == current_user_email and (payload.is_admin is False or payload.role == "user"):
        raise HTTPException(status_code=400, detail="You cannot demote your own account status.")

    update_data = {k: v for k, v in payload.dict().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No profile modifications specified.")

    await user_collection.update_one({"_id": obj_id}, {"$set": update_data})
    
    # LOG ACTION
    await log_admin_action(current_user_email, "UPDATE_USER", f"Administrative Tier Action on {user['email']}: {update_data}")
    
    return {"message": "Identity modified successfully."}

@router.get("/admin/device-stream", dependencies=[Depends(VerifyAdmin())])
async def get_device_stream():
    """Returns historical raw telemetry from the device_stream collection."""
    telemetry = []
    async for entry in device_stream_collection.find().sort("_id", -1).limit(1000):
        entry["_id"] = str(entry["_id"])
        telemetry.append(entry)
    return telemetry

@router.delete("/admin/device-stream/{record_id}", dependencies=[Depends(VerifyAdmin())])
async def delete_telemetry(record_id: str, token: str = Depends(JWTBearer())):
    """Deletes a specific telemetry record from the device_stream archive."""
    try:
        obj_id = ObjectId(record_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid ID format")

    result = await device_stream_collection.delete_one({"_id": obj_id})
    if result.deleted_count == 1:
        email = decodeJWT(token).get("email")
        await log_admin_action(email, "TELEMETRY_DELETE", f"Purged historical telemetry record ID: {record_id}")
        return {"message": "Telemetry record purged successfully"}
    
    raise HTTPException(status_code=404, detail="Record not found")

@router.get("/admin/system-health", dependencies=[Depends(VerifyAdmin())])
async def get_system_health():
    """Checks the health of the Database and Kafka producer."""
    # 1. Database Check
    db_status = "Offline"
    try:
        await database.command("ping")
        db_status = "Online"
    except Exception:
        db_status = "Offline"

    # 2. Kafka Status (Simulated)
    # Since Kafka depends on the separate producer/consumer containers,
    # we'll assume it's online if the bootstrap server environment is reachable.
    kafka_status = "Offline"
    kafka_server = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    try:
        # Simple hostname check
        import socket
        host, port = kafka_server.split(":")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            if s.connect_ex((host, int(port))) == 0:
                kafka_status = "Online"
    except:
        kafka_status = "Offline"

    # 3. Maintenance Mode Status
    config = await settings_collection.find_one({"key": "maintenance_config"})
    maintenance_status = config.get("value", {}).get("is_active", False) if config else False

    return {
        "database": db_status,
        "kafka": kafka_status,
        "maintenance": maintenance_status
    }

# --- ENTERPRISE SUITE ENDPOINTS ---

@router.get("/admin/audit-logs", dependencies=[Depends(VerifyAdmin())])
async def get_audit_logs(limit: int = Query(50, ge=1, le=200)):
    """Fetches the latest administrative actions from the audit trail."""
    logs = []
    async for log in audit_collection.find().sort("timestamp", -1).limit(limit):
        log["_id"] = str(log["_id"])
        logs.append(log)
    return logs

@router.post("/admin/broadcast", dependencies=[Depends(VerifyAdmin())])
async def create_broadcast(payload: BroadcastSchema, token: str = Depends(JWTBearer())):
    """Creates a global announcement that will be pushed to all connected clients."""
    decoded = decodeJWT(token)
    payload.admin_email = decoded.get("email")
    
    broadcast_dict = payload.dict()
    # Add timestamp if not present
    from datetime import datetime
    broadcast_dict["timestamp"] = datetime.now().isoformat()
    await broadcast_collection.insert_one(broadcast_dict)
    
    # LOG ACTION
    await log_admin_action(payload.admin_email, "BROADCAST_CREATE", f"Broadcast Sent: {payload.message}")
    
    return {"message": "Broadcast transmitted successfully"}

@router.get("/admin/broadcasts", dependencies=[Depends(JWTBearer())])
async def get_broadcasts(limit: int = Query(50, ge=1, le=200), token: str = Depends(JWTBearer())):
    """Retrieves broadcast messages, excluding ones the user has personally dismissed."""
    decoded = decodeJWT(token)
    email = decoded.get("email", "")
    user = await user_collection.find_one({"email": email})
    dismissed = user.get("dismissed_broadcasts", []) if user else []

    broadcasts = []
    async for b in broadcast_collection.find().sort("timestamp", -1).limit(limit):
        b["_id"] = str(b["_id"])
        if b["_id"] not in dismissed:
            broadcasts.append(b)
    return broadcasts

@router.post("/broadcasts/{id}/dismiss", dependencies=[Depends(JWTBearer())])
async def dismiss_broadcast(id: str, token: str = Depends(JWTBearer())):
    """Soft-deletes a broadcast for the current user only. Does NOT affect other users."""
    decoded = decodeJWT(token)
    email = decoded.get("email")
    await user_collection.update_one(
        {"email": email},
        {"$addToSet": {"dismissed_broadcasts": id}}
    )
    return {"message": "Broadcast dismissed for your account"}

@router.delete("/broadcasts/dismiss-all", dependencies=[Depends(JWTBearer())])
async def dismiss_all_broadcasts(token: str = Depends(JWTBearer())):
    """Clears all current broadcasts from the current user's view only."""
    decoded = decodeJWT(token)
    email = decoded.get("email")
    # Get all current broadcast IDs and add them all to dismissed list
    all_ids = []
    async for b in broadcast_collection.find({}, {"_id": 1}):
        all_ids.append(str(b["_id"]))
    await user_collection.update_one(
        {"email": email},
        {"$addToSet": {"dismissed_broadcasts": {"$each": all_ids}}}
    )
    return {"message": "All broadcasts dismissed for your account"}

@router.delete("/admin/broadcasts/{id}", dependencies=[Depends(VerifyAdmin())])
async def delete_broadcast(id: str, token: str = Depends(JWTBearer())):
    """ADMIN: Permanently deletes a broadcast for ALL users."""
    res = await broadcast_collection.delete_one({"_id": ObjectId(id)})
    if res.deleted_count == 1:
        email = decodeJWT(token).get("email")
        await log_admin_action(email, "BROADCAST_DELETE", f"Deleted broadcast ID: {id}")
        return {"message": "Broadcast permanently removed for all users"}
    raise HTTPException(status_code=404, detail="Broadcast not found")

@router.delete("/admin/broadcasts", dependencies=[Depends(VerifyAdmin())])
async def clear_all_broadcasts(token: str = Depends(JWTBearer())):
    """ADMIN: Permanently purges the entire global broadcast history for all users."""
    await broadcast_collection.delete_many({})
    email = decodeJWT(token).get("email")
    await log_admin_action(email, "BROADCAST_PURGE", "Purged entire broadcast registry history for all users.")
    return {"message": "All broadcasts permanently cleared for all users"}

@router.post("/admin/message", dependencies=[Depends(VerifyAdmin())])
async def send_direct_message(payload: DirectMessageSchema, token: str = Depends(JWTBearer())):
    """Sends a targeted direct message from admin to a specific user's inbox."""
    decoded = decodeJWT(token)
    payload.sender_email = decoded.get("email")
    msg_dict = payload.dict()
    msg_dict["timestamp"] = datetime.now().isoformat()
    await direct_messages_collection.insert_one(msg_dict)
    await log_admin_action(payload.sender_email, "DIRECT_MESSAGE", f"Sent message to {payload.recipient_email}: {payload.title}")
    return {"message": "Message dispatched successfully"}

@router.get("/messages/inbox", dependencies=[Depends(JWTBearer())])
async def get_inbox(token: str = Depends(JWTBearer())):
    """Returns all direct messages addressed to the logged-in user."""
    decoded = decodeJWT(token)
    email = decoded.get("email")
    msgs = []
    async for m in direct_messages_collection.find({"recipient_email": email}).sort("timestamp", -1):
        m["_id"] = str(m["_id"])
        msgs.append(m)
    return msgs

@router.patch("/messages/{msg_id}/read", dependencies=[Depends(JWTBearer())])
async def mark_message_read(msg_id: str):
    """Marks a specific direct message as read."""
    await direct_messages_collection.update_one({"_id": ObjectId(msg_id)}, {"$set": {"is_read": True}})
    return {"message": "Marked as read"}

@router.delete("/messages/{msg_id}", dependencies=[Depends(JWTBearer())])
async def delete_direct_message(msg_id: str, token: str = Depends(JWTBearer())):
    """Deletes a specific direct message from the inbox."""
    decoded = decodeJWT(token)
    email = decoded.get("email")
    res = await direct_messages_collection.delete_one({"_id": ObjectId(msg_id), "recipient_email": email})
    if res.deleted_count == 1:
        return {"message": "Message deleted"}
    raise HTTPException(status_code=404, detail="Message not found")

@router.post("/admin/maintenance", dependencies=[Depends(VerifyAdmin())])
async def toggle_maintenance(payload: MaintenanceSchema, token: str = Depends(JWTBearer())):
    """Toggles global maintenance mode for the entire application."""
    decoded = decodeJWT(token)
    admin_email = decoded.get("email")
    
    await settings_collection.update_one(
        {"key": "maintenance_config"},
        {"$set": {"value": payload.dict()}},
        upsert=True
    )
    
    status = "ACTIVATED" if payload.is_active else "DEACTIVATED"
    await log_admin_action(admin_email, "MAINTENANCE_TOGGLE", f"System Maintenance Mode {status}")
    
    return {"message": f"Maintenance mode {status}", "is_active": payload.is_active}

@router.get("/admin/export/shipments")
async def export_shipments_csv(token: str = Query(...)):
    """Generates and streams a CSV report of all global shipments. Supports query-string token for direct download."""
    decoded = decodeJWT(token)
    if not decoded:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user = await user_collection.find_one({"email": decoded.get("email")})
    if not user or not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # LOG ACTION
    await log_admin_action(user["email"], "EXPORT_CSV", "Exported global shipment report.")
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write Headers
    headers = ["Shipment_Number", "Device", "Route", "Created_By", "Expected_Delivery"]
    writer.writerow(headers)
    
    async for s in shipment_collection.find():
        writer.writerow([
            s.get("Shipment_Number"),
            s.get("Device"),
            f"{s.get('Route_Details')}",
            s.get("created_by"),
            s.get("Expected_Delivery_Date")
        ])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=shipment_report.csv"}
    )

@router.get("/admin/stats/trends", dependencies=[Depends(VerifyAdmin())])
async def get_shipment_trends():
    """Calculates shipment volume trends over the last 14 days for Chart.js."""
    fourteen_days_ago = datetime.now() - timedelta(days=14)
    
    # Aggregation to group by date
    # Note: This assumes Expected_Delivery_Date or a 'created_at' field exists as ISO date
    pipeline = [
        {"$match": {"Expected_Delivery_Date": {"$exists": True}}},
        {"$group": {
            "_id": {"$substr": ["$Expected_Delivery_Date", 0, 10]},
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
    ]
    
    trends = []
    async for item in shipment_collection.aggregate(pipeline):
        trends.append({"date": item["_id"], "count": item["count"]})
        
    
    return trends

@router.get("/admin/device-comparison", dependencies=[Depends(VerifyAdmin())])
async def get_device_comparison(token: str = Depends(JWTBearer())):
    """ADMIN: Aggregates user-created shipments for the device comparison visualization."""
    comparison_data = []
    
    # Filter: Only user-created shipments (is_kafka=false OR is_kafka not present)
    query = {"$or": [{"is_kafka": {"$exists": False}}, {"is_kafka": False}]}
    
    async for s in shipment_collection.find(query):
        comparison_data.append({
            "Shipment_Number": s.get("Shipment_Number", "N/A"),
            "Device": s.get("Device", "N/A"),
            "Temperature": s.get("Temperature", 0.0),
            "Number_of_Devices": s.get("Number_of_Devices", 1),
            "Status": s.get("Status", "In Transit")
        })

    # LOG ACTION
    email = decodeJWT(token).get("email")
    await log_admin_action(email, "DEVICE_COMPARISON_FETCH", f"Fetched {len(comparison_data)} registry entries for visualization.")
    
    return comparison_data
@router.get("/admin/analytics/status-distribution", dependencies=[Depends(VerifyAdmin())])
async def get_status_distribution():
    """Aggregates shipment counts by Status for Donut Chart."""
    # Use aggregation to case-insensitively group statuses
    # We'll normalize to common buckets: Transit, Delayed, Delivered, Cancelled
    pipeline = [
        {"$project": {
            "normalized_status": {
                "$cond": [
                    {"$regexMatch": {"input": "$Status", "regex": "Transit", "options": "i"}}, "In Transit",
                    {"$cond": [
                        {"$regexMatch": {"input": "$Status", "regex": "Delayed", "options": "i"}}, "Delayed",
                        {"$cond": [
                            {"$regexMatch": {"input": "$Status", "regex": "Delivered", "options": "i"}}, "Delivered",
                            {"$cond": [
                                {"$regexMatch": {"input": "$Status", "regex": "Cancelled", "options": "i"}}, "Cancelled",
                                "Other"
                            ]}
                        ]}
                    ]}
                ]
            }
        }},
        {"$group": {"_id": "$normalized_status", "count": {"$sum": 1}}}
    ]
    
    distribution = []
    async for item in shipment_collection.aggregate(pipeline):
        distribution.append({"status": item["_id"], "count": item["count"]})
    return distribution

@router.get("/admin/analytics/goods-distribution", dependencies=[Depends(VerifyAdmin())])
async def get_goods_distribution():
    """Aggregates shipment counts by Goods_Type for Bar Chart."""
    pipeline = [
        {"$group": {"_id": "$Goods_Type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]
    distribution = []
    async for item in shipment_collection.aggregate(pipeline):
        distribution.append({"type": item["_id"] or "Unknown", "count": item["count"]})
    return distribution

@router.get("/admin/analytics/telemetry-stats", dependencies=[Depends(VerifyAdmin())])
async def get_telemetry_stats():
    """Aggregates average temperature and battery from historical device stream."""
    # Get last 100 points for real-time trend line
    pipeline = [
        {"$sort": {"_id": -1}},
        {"$limit": 100},
        {"$project": {
            "timestamp": 1,
            "Temperature": 1,
            "Battery": {
                "$convert": {
                    "input": {"$substr": ["$Battery", 0, {"$subtract": [{"$strLenCP": "$Battery"}, 1]}]},
                    "to": "int",
                    "onError": 0,
                    "onNull": 0
                }
            }
        }},
        {"$sort": {"_id": 1}}
    ]
    
    stats = []
    async for item in device_stream_collection.aggregate(pipeline):
        stats.append({
            "time": item.get("timestamp"),
            "temp": item.get("Temperature", 0.0),
            "battery": item.get("Battery", 0)
        })
    return stats

@router.get("/admin/analytics/sla-performance", dependencies=[Depends(VerifyAdmin())])
async def get_sla_performance():
    """Calculates on-time vs overdue shipments based on Expected_Delivery_Date."""
    now = datetime.utcnow().isoformat()
    pipeline = [
        {"$project": {
            "is_overdue": {
                "$and": [
                    {"$lt": ["$Expected_Delivery_Date", now]},
                    {"$ne": ["$Status", "Delivered"]}
                ]
            }
        }},
        {"$group": {"_id": "$is_overdue", "count": {"$sum": 1}}}
    ]
    performance = {"ontime": 0, "overdue": 0}
    async for item in shipment_collection.aggregate(pipeline):
        if item["_id"] == True:
            performance["overdue"] = item["count"]
        else:
            performance["ontime"] = item["count"]
    return performance

@router.get("/admin/analytics/route-flow", dependencies=[Depends(VerifyAdmin())])
async def get_route_flow():
    """Aggregates shipment volume by Top 10 unique trade lanes."""
    pipeline = [
        {"$group": {"_id": "$Route_Details", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]
    flow = []
    async for item in shipment_collection.aggregate(pipeline):
        flow.append({"route": item["_id"] or "Unknown", "count": item["count"]})
    return flow
