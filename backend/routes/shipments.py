from fastapi import APIRouter, Body, Depends, HTTPException
from typing import List
from backend.models.shipment import ShipmentSchema
from backend.config.database import shipment_collection, user_collection
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
        
    shipment_dict["created_by"] = email
        
    await shipment_collection.insert_one(shipment_dict)
    return {"message": "Shipment created successfully"}

@router.get("/shipments", dependencies=[Depends(JWTBearer())])
async def get_shipments(token: str = Depends(JWTBearer())):
    email = get_current_email(token)
    
    # Identify if user is admin
    user = await user_collection.find_one({"email": email})
    is_admin = user.get("is_admin", False) if user else False
    
    shipments = []
    
    # Logic Update: Admins see everything. 
    # Regular users see their own shipments AND shipments created by any admin.
    if is_admin:
        query = {}
    else:
        # Find all admin emails
        admin_users_cursor = user_collection.find({"is_admin": True}, {"email": 1})
        admin_emails = [u["email"] async for u in admin_users_cursor]
        query = {"$or": [
            {"created_by": email},
            {"created_by": {"$in": admin_emails}}
        ]}
    
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
    
    # --- SECURITY: LOCK STATUS TO ADMINS ONLY ---
    # We ensure that the 'Status' field cannot be modified by standard users.
    # If not an admin, we ignore any status sent in the payload and stick to the original state.
    if not is_admin:
        update_data["Status"] = existing_shipment.get("Status", "In Transit")

    update_data["created_by"] = existing_shipment.get("created_by")
    
    # Ensure date is formatted correctly if present
    if update_data.get("Expected_Delivery_Date"):
        update_data["Expected_Delivery_Date"] = update_data["Expected_Delivery_Date"].isoformat()

    # Update in MongoDB
    result = await shipment_collection.update_one(
        {"Shipment_Number": shipment_number},
        {"$set": update_data}
    )

    return {"message": "Shipment updated successfully"}