from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from services.alert import send_alert_with_patient

router = APIRouter()

class AlertRequest(BaseModel):
    alert_type: str
    session_id: str
    user_id: str
    action_tier: str
    reported_symptoms: list
    internal_diagnosis: Optional[str] = None
    active_differentials: Optional[list] = []
    language: str = "en"
    worker_role: Optional[str] = None
    patient_name: Optional[str] = None
    patient_age: Optional[str] = None

class AlertResponse(BaseModel):
    success: bool
    message: str
    recipients: list
    umma_ref: Optional[str] = None

@router.post("/alert", response_model=AlertResponse)
async def send_alert_endpoint(request: AlertRequest):
    result = send_alert_with_patient(
        alert_type=request.alert_type,
        session_id=request.session_id,
        user_id=request.user_id,
        action_tier=request.action_tier,
        reported_symptoms=request.reported_symptoms,
        internal_diagnosis=request.internal_diagnosis,
        active_differentials=request.active_differentials or [],
        language=request.language,
        worker_role=request.worker_role,
        patient_name=request.patient_name,
        patient_age=request.patient_age
    )
    return AlertResponse(**result)
