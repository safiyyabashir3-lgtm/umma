import sys
sys.path.insert(0, ".")
from logger import get_logger
logger = get_logger(__name__)

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, Any, Dict
from services.intent import classify_intent
from services.reasoning import process_message
from services.rag import get_retrieval_log
import uuid
import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv("/workspaces/umma/umma-ai/.env")

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    user_id: str = "anonymous"
    session_id: str = None

class ChatResponse(BaseModel):
    intent: str
    response: str
    session_id: str
    debug: Optional[Dict[str, Any]] = None

def get_active_intent(session_id: str) -> str:
    try:
        result = supabase.table("clinical_state")\
            .select("intent, concluded")\
            .eq("session_id", session_id)\
            .execute()
        if result.data:
            state = result.data[0]
            if not state.get("concluded") and state.get("intent"):
                return state.get("intent")
    except Exception as e:
        logger.error(f"Error getting active intent: {e}")
    return None

def get_debug_info(session_id: str) -> dict:
    try:
        result = supabase.table("clinical_state")\
            .select("*")\
            .eq("session_id", session_id)\
            .execute()
        if result.data:
            state = result.data[0]
            return {
                "stage": state.get("stage"),
                "questions_asked": state.get("questions_asked"),
                "internal_diagnosis": state.get("internal_diagnosis"),
                "secondary_diagnosis": state.get("secondary_diagnosis"),
                "active_differentials": state.get("active_differentials", []),
                "confidence_level": state.get("confidence_level"),
                "action_tier": state.get("action_tier"),
                "reported_symptoms": state.get("reported_symptoms", []),
                "symptom_topic": state.get("symptom_topic"),
                "concluded": state.get("concluded"),
                "question_rationale": state.get("question_rationale")
            }
    except:
        pass
    return {}

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())

    try:
        supabase.table("sessions").upsert({
            "id": session_id,
            "user_id": request.user_id
        }, on_conflict="id").execute()
    except Exception as e:
        logger.error(f"Session upsert error: {e}")

    active_intent = get_active_intent(session_id)
    if active_intent:
        intent = active_intent
    else:
        try:
            intent = classify_intent(request.message)
        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
            intent = "general_health"
            if any(w in request.message.lower() for w in ["bleeding", "convuls", "fit", "seiz", "breath", "movement", "baby not moving"]):
                intent = "emergency"

    response, rag_debug = process_message(
        user_id=request.user_id,
        session_id=session_id,
        message=request.message,
        intent=intent
    )

    debug_info = get_debug_info(session_id)
    retrieval_log = get_retrieval_log()
    debug_info["retrieval_log"] = retrieval_log

    return ChatResponse(
        intent=intent,
        response=response,
        session_id=session_id,
        debug=debug_info
    )
