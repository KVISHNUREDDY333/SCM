from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from backend.config.database import user_collection, shipment_collection, database, audit_collection, broadcast_collection, settings_collection
from backend.middleware.security import VerifyAdmin, JWTBearer
from backend.models.admin_models import UserUpdateSchema, AuditLogSchema, BroadcastSchema, MaintenanceSchema
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
    """Returns global system statistics."""
    total_users = await user_collection.count_documents({})
    total_shipments = await shipment_collection.count_documents({})
    
    # Get unique devices from all shipments
    pipeline = [{"$group": {"_id": "$Device"}}]
    unique_devices_cursor = shipment_collection.aggregate(pipeline)
    unique_devices = 0
    async for _ in unique_devices_cursor:
        unique_devices += 1

    return {
        "total_users": total_users,
        "total_shipments": total_shipments,
        "active_devices": unique_devices
    }

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
async def get_broadcasts(limit: int = Query(50, ge=1, le=200)):
    """Retrieves all historical broadcast messages."""
    broadcasts = []
    async for b in broadcast_collection.find().sort("timestamp", -1).limit(limit):
        b["_id"] = str(b["_id"])
        broadcasts.append(b)
    return broadcasts

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
