from fastapi import APIRouter, Body, Depends, HTTPException
from typing import List
from backend.models.shipment import ShipmentSchema
from backend.config.database import shipment_collection
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
async def get_shipments():
    shipments = []
    # Fetch all shipments
    async for shipment in shipment_collection.find():
        # IMPORTANT: Convert ObjectId to string to prevent JSON errors
        shipment["_id"] = str(shipment["_id"])
        shipments.append(shipment)
    return shipments

@router.delete("/shipments/{shipment_number}", dependencies=[Depends(JWTBearer())])
async def delete_shipment(shipment_number: str, token: str = Depends(JWTBearer())):
    email = get_current_email(token)
    
    # Verify Ownership
    shipment = await shipment_collection.find_one({"Shipment_Number": shipment_number})
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
        
    if shipment.get("created_by") != email:
        raise HTTPException(status_code=403, detail="You do not have permission to delete this shipment")

    result = await shipment_collection.delete_one({"Shipment_Number": shipment_number})
    if result.deleted_count == 1:
        return {"message": f"Shipment {shipment_number} deleted successfully"}
    
    raise HTTPException(status_code=404, detail="Shipment not found")

@router.put("/shipments/{shipment_number}", dependencies=[Depends(JWTBearer())])
async def update_shipment(shipment_number: str, shipment: ShipmentSchema = Body(...), token: str = Depends(JWTBearer())):
    email = get_current_email(token)
    
    # Verify Ownership
    existing_shipment = await shipment_collection.find_one({"Shipment_Number": shipment_number})
    if not existing_shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
        
    if existing_shipment.get("created_by") != email:
        raise HTTPException(status_code=403, detail="You do not have permission to modify this shipment")

    # Convert Pydantic model to dict
    update_data = shipment.dict()
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