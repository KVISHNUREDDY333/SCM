from fastapi import APIRouter, Body, Depends, HTTPException
from typing import List
from datetime import datetime
from backend.models.shipment import ShipmentSchema
from backend.config.database import shipment_collection, user_collection, direct_messages_collection
from backend.middleware.security import JWTBearer
from backend.auth.jwt_handler import decodeJWT

router = APIRouter()

def get_current_email(token: str) -> str:
    decoded = decodeJWT(token)
    return decoded.get("email", "") if decoded else ""

@router.post("/shipments", dependencies=[Depends(JWTBearer())])
async def create_shipment(shipment: ShipmentSchema = Body(...), token: str = Depends(JWTBearer())):
    email = get_current_email(token)
    shipment_dict = shipment.dict()
    if shipment_dict.get("Expected_Delivery_Date"):
        shipment_dict["Expected_Delivery_Date"] = shipment_dict["Expected_Delivery_Date"].isoformat()
        
    if not shipment_dict.get("Status"):
        shipment_dict["Status"] = "In Transit"
        
    shipment_dict["created_by"] = email
        
    await shipment_collection.insert_one(shipment_dict)
    return {"message": "Shipment created successfully"}

@router.get("/shipments", dependencies=[Depends(JWTBearer())])
async def get_shipments(all: bool = False, token: str = Depends(JWTBearer())):
    email = get_current_email(token)
    
    # Identify if user is admin
    user = await user_collection.find_one({"email": email})
    is_admin = user.get("is_admin", False) if user else False
    
    shipments = []
    
    # RESTRICTED VIEW LOGIC:
    # If ?all=true and the user is an admin, show global registry.
    # Otherwise, strictly show only shipments created by the current user.
    if all and is_admin:
        query = {}
    else:
        query = {"created_by": email}
    
    async for shipment in shipment_collection.find(query):
        shipment["_id"] = str(shipment["_id"])
        shipments.append(shipment)
        
    return shipments

@router.delete("/shipments/{shipment_number}", dependencies=[Depends(JWTBearer())])
async def delete_shipment(shipment_number: str, token: str = Depends(JWTBearer())):
    # Verify Ownership or Admin Access
    shipment = await shipment_collection.find_one({"Shipment_Number": shipment_number})
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
        
    # Check if admin
    email = get_current_email(token)
    user = await user_collection.find_one({"email": email})
    is_admin = user.get("is_admin", False) if user else False
    
    if not is_admin and shipment.get("created_by") != email:
        raise HTTPException(status_code=403, detail="You do not have permission to delete this shipment")

    result = await shipment_collection.delete_one({"Shipment_Number": shipment_number})
    if result.deleted_count == 1:
        return {"message": f"Shipment {shipment_number} deleted successfully"}
    
    raise HTTPException(status_code=404, detail="Shipment not found")

@router.put("/shipments/{shipment_number}", dependencies=[Depends(JWTBearer())])
async def update_shipment(shipment_number: str, shipment: ShipmentSchema = Body(...), token: str = Depends(JWTBearer())):
    # Verify Ownership or Admin Access
    existing_shipment = await shipment_collection.find_one({"Shipment_Number": shipment_number})
    if not existing_shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
        
    # Check if admin
    email = get_current_email(token)
    user = await user_collection.find_one({"email": email})
    is_admin = user.get("is_admin", False) if user else False
    
    if not is_admin and existing_shipment.get("created_by") != email:
        raise HTTPException(status_code=403, detail="You do not have permission to modify this shipment")

    # Convert Pydantic model to dict
    update_data = shipment.dict()
    
    # --- SECURITY ENFORCEMENT ---
    # Only admins can modify the 'Status' field.
    if is_admin:
        # Admin explicitly sets status; fall back to existing only if truly absent
        if update_data.get("Status") is None:
            update_data["Status"] = existing_shipment.get("Status", "In Transit")
    else:
        # Regular users cannot change status, always preserve existing from DB
        update_data["Status"] = existing_shipment.get("Status", "In Transit")
    
    # Preservation of ownership (Users cannot 'steal' shipments via updates)
    update_data["created_by"] = existing_shipment.get("created_by")
    
    # Ensure date is formatted correctly if present
    if update_data.get("Expected_Delivery_Date"):
        update_data["Expected_Delivery_Date"] = update_data["Expected_Delivery_Date"].isoformat()

    # Update in MongoDB
    result = await shipment_collection.update_one(
        {"Shipment_Number": shipment_number},
        {"$set": update_data}
    )

    # --- AUTOMATED NOTIFICATION LOGIC ---
    # Trigger a personal notification to the shipment creator if explicitly requested by an administrator.
    if is_admin and update_data.get("Notify_User"):
        creator_email = existing_shipment.get("created_by")
        if creator_email:
            # Construct a professional administrative override alert
            system_notification = {
                "recipient_email": creator_email,
                "sender_email": "system@scmxpert.com",
                "title": f"⚠️ Admin Override: Shipment {shipment_number}",
                "message": (
                    f"Operational update detected. An administrator ({email}) has modified "
                    f"the parameters of shipment {shipment_number}. Please review the updated "
                    f"manifest and status in your control panel."
                ),
                "timestamp": datetime.now().isoformat(),
                "is_read": False
            }
            await direct_messages_collection.insert_one(system_notification)

    return {"message": "Shipment updated successfully"}