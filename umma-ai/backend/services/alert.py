import sys
sys.path.insert(0, ".")
from logger import get_logger
logger = get_logger(__name__)

"""
services/alert.py
Generates clinical summaries and sends WhatsApp alerts via Twilio.
All alerts are user-initiated — nothing fires automatically.
"""

import os
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
from openai import AzureOpenAI
from supabase import create_client
from twilio.rest import Client as TwilioClient

load_dotenv("/workspaces/umma/umma-ai/.env")

openai_client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION")
)

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

twilio_client = TwilioClient(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN")
)

DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")


def generate_clinical_summary(reported_symptoms, internal_diagnosis, active_differentials, action_tier, language):
    try:
        response = openai_client.chat.completions.create(
            model=DEPLOYMENT,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write brief clinical summaries for Nigerian healthcare workers "
                        "receiving an alert from UMMA, a maternal and child health AI.\n"
                        "Write in clear clinical English. 3-4 sentences maximum.\n"
                        "Include: main presenting symptoms, most likely diagnosis, "
                        "urgency level, and one key thing the worker should watch for.\n"
                        "Never use hollow phrases. Be direct and factual.\n"
                        "Do not address the patient — this is for the health worker."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"Reported symptoms: {json.dumps(reported_symptoms)}\n"
                        f"Most likely diagnosis: {internal_diagnosis}\n"
                        f"Active differentials: {json.dumps(active_differentials)}\n"
                        f"Action tier: {action_tier}\n"
                        f"Patient language: {language}"
                    )
                }
            ],
            temperature=0.2,
            max_tokens=200
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Clinical summary generation failed: {e}")
        return (
            f"UMMA alert. Symptoms: {', '.join(reported_symptoms)}. "
            f"Action tier: {action_tier}. Please assess on arrival."
        )


def format_emergency_message(clinical_summary, symptoms, language):
    time_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
    return (
        f"🚨 *UMMA EMERGENCY ALERT* — {time_str}\n\n"
        f"*Clinical Summary:*\n{clinical_summary}\n\n"
        f"*Reported Symptoms:* {', '.join(symptoms)}\n"
        f"*Patient Language:* {'English' if language == 'en' else 'Hausa'}\n\n"
        f"Patient has been advised to come to AKTH immediately.\n"
        f"_Sent by UMMA Maternal Health AI_"
    )


def format_urgent_clinic_message(clinical_summary, symptoms, language):
    time_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
    return (
        f"📋 *UMMA APPOINTMENT REQUEST* — {time_str}\n\n"
        f"*Clinical Summary:*\n{clinical_summary}\n\n"
        f"*Symptom Category:* {', '.join(symptoms)}\n"
        f"*Urgency:* Same day or next day\n"
        f"*Patient Language:* {'English' if language == 'en' else 'Hausa'}\n\n"
        f"Patient has been advised to visit AKTH today or tomorrow. "
        f"Please call to confirm appointment.\n"
        f"_Sent by UMMA Maternal Health AI_"
    )


def format_chw_message(clinical_summary, symptoms, worker_role, language):
    role_label = {"chew": "CHEW", "nurse": "Nurse", "midwife": "Midwife"}.get(worker_role, "Health Worker")
    time_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
    return (
        f"👋 *UMMA FOLLOW-UP REQUEST* — {time_str}\n\n"
        f"*For:* {role_label}\n\n"
        f"*Clinical Summary:*\n{clinical_summary}\n\n"
        f"*Reported Symptoms:* {', '.join(symptoms)}\n"
        f"*Patient Language:* {'English' if language == 'en' else 'Hausa'}\n\n"
        f"A patient has requested a follow-up. Please reach out to check in.\n"
        f"_Sent by UMMA Maternal Health AI_"
    )


def send_whatsapp(to_number, message):
    try:
        msg = twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=f"whatsapp:{to_number}",
            body=message
        )
        return True, msg.sid, None
    except Exception as e:
        print(f"Twilio send failed to {to_number}: {e}")
        return False, None, str(e)


def get_facility(short_code="akth"):
    try:
        result = supabase.table("facilities")\
            .select("*")\
            .eq("short_code", short_code)\
            .eq("active", True)\
            .execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"get_facility error: {e}")
        return None


def get_first_available_worker(role):
    try:
        result = supabase.table("healthcare_workers")\
            .select("*")\
            .eq("role", role)\
            .eq("active", True)\
            .limit(1)\
            .execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"get_first_available_worker error: {e}")
        return None


def log_alert(session_id, user_id, alert_type, action_tier, recipient_type,
              recipient_whatsapp, recipient_name, clinical_summary, reported_symptoms,
              internal_diagnosis, active_differentials, language, facility_id=None,
              worker_id=None, message_sid=None, status="sent", error_message=None):
    try:
        supabase.table("alerts").insert({
            "session_id": session_id,
            "user_id": user_id,
            "alert_type": alert_type,
            "action_tier": action_tier,
            "recipient_type": recipient_type,
            "recipient_whatsapp": recipient_whatsapp,
            "recipient_name": recipient_name,
            "facility_id": facility_id,
            "worker_id": worker_id,
            "clinical_summary": clinical_summary,
            "reported_symptoms": reported_symptoms,
            "internal_diagnosis": internal_diagnosis,
            "active_differentials": active_differentials,
            "language": language,
            "whatsapp_message_sid": message_sid,
            "status": status,
            "error_message": error_message
        }).execute()
    except Exception as e:
        print(f"Alert logging failed: {e}")


def generate_umma_ref():
    import random, string
    return 'UMMA-' + ''.join(random.choices(string.digits, k=6))

def send_alert(alert_type, session_id, user_id, action_tier, reported_symptoms,
               internal_diagnosis, active_differentials, language, worker_role=None):

    clinical_summary = generate_clinical_summary(
        reported_symptoms, internal_diagnosis, active_differentials, action_tier, language
    )

    results = []

    if alert_type == "emergency":
        facility = get_facility("akth")
        if not facility:
            return {"success": False, "message": "AKTH facility not found", "recipients": []}
        contacts = facility.get("emergency_contacts", [])
        message = format_emergency_message(clinical_summary, reported_symptoms, language)
        for contact in contacts:
            number = contact.get("whatsapp")
            name = contact.get("name", "Doctor")
            success, sid, error = send_whatsapp(number, message)
            log_alert(session_id, user_id, "emergency", action_tier, "doctor",
                      number, name, clinical_summary, reported_symptoms,
                      internal_diagnosis, active_differentials, language,
                      facility_id=facility["id"], message_sid=sid,
                      status="sent" if success else "failed", error_message=error)
            results.append({"name": name, "success": success})

    elif alert_type == "urgent_clinic":
        facility = get_facility("akth")
        if not facility or not facility.get("records_contact"):
            return {"success": False, "message": "Records contact not configured", "recipients": []}
        number = facility["records_contact"]
        message = format_urgent_clinic_message(clinical_summary, reported_symptoms, language)
        success, sid, error = send_whatsapp(number, message)
        log_alert(session_id, user_id, "urgent_clinic", action_tier, "records",
                  number, "Records Officer", clinical_summary, reported_symptoms,
                  internal_diagnosis, active_differentials, language,
                  facility_id=facility["id"], message_sid=sid,
                  status="sent" if success else "failed", error_message=error)
        results.append({"name": "Records Officer", "success": success})

    elif alert_type == "chw":
        if not worker_role:
            return {"success": False, "message": "worker_role required for CHW alert", "recipients": []}
        worker = get_first_available_worker(worker_role)
        if not worker:
            return {"success": False, "message": f"No active {worker_role} available", "recipients": []}
        message = format_chw_message(clinical_summary, reported_symptoms, worker_role, language)
        success, sid, error = send_whatsapp(worker["whatsapp"], message)
        log_alert(session_id, user_id, "chw", action_tier, worker_role,
                  worker["whatsapp"], worker["name"], clinical_summary, reported_symptoms,
                  internal_diagnosis, active_differentials, language,
                  worker_id=worker["id"], message_sid=sid,
                  status="sent" if success else "failed", error_message=error)
        results.append({"name": worker["name"], "success": success})

    any_success = any(r["success"] for r in results)
    return {
        "success": any_success,
        "message": "Alert sent" if any_success else "All sends failed",
        "recipients": results
    }

def send_alert_with_patient(alert_type, session_id, user_id, action_tier, reported_symptoms,
               internal_diagnosis, active_differentials, language, worker_role=None,
               patient_name=None, patient_age=None):
    umma_ref = generate_umma_ref()

    clinical_summary = generate_clinical_summary(
        reported_symptoms, internal_diagnosis, active_differentials, action_tier, language
    )

    patient_info = f"\n\n*Patient Name:* {patient_name or 'Not provided'}\n*Patient Age:* {patient_age or 'Not provided'}\n*UMMA Reference:* {umma_ref}"

    results = []

    if alert_type == "emergency":
        facility = get_facility("akth")
        if not facility:
            return {"success": False, "message": "AKTH facility not found", "recipients": [], "umma_ref": None}
        contacts = facility.get("emergency_contacts", [])
        message = format_emergency_message(clinical_summary, reported_symptoms, language) + patient_info
        for contact in contacts:
            number = contact.get("whatsapp")
            name = contact.get("name", "Doctor")
            success, sid, error = send_whatsapp(number, message)
            log_alert(session_id, user_id, "emergency", action_tier, "doctor",
                      number, name, clinical_summary, reported_symptoms,
                      internal_diagnosis, active_differentials, language,
                      facility_id=facility["id"], message_sid=sid,
                      status="sent" if success else "failed", error_message=error)
            results.append({"name": name, "success": success})

    elif alert_type == "urgent_clinic":
        facility = get_facility("akth")
        if not facility or not facility.get("records_contact"):
            return {"success": False, "message": "Records contact not configured", "recipients": [], "umma_ref": None}
        number = facility["records_contact"]
        message = format_urgent_clinic_message(clinical_summary, reported_symptoms, language) + patient_info
        success, sid, error = send_whatsapp(number, message)
        log_alert(session_id, user_id, "urgent_clinic", action_tier, "records",
                  number, "Records Officer", clinical_summary, reported_symptoms,
                  internal_diagnosis, active_differentials, language,
                  facility_id=facility["id"], message_sid=sid,
                  status="sent" if success else "failed", error_message=error)
        results.append({"name": "Records Officer", "success": success})

    elif alert_type == "chw":
        if not worker_role:
            return {"success": False, "message": "worker_role required for CHW alert", "recipients": [], "umma_ref": None}
        worker = get_first_available_worker(worker_role)
        if not worker:
            return {"success": False, "message": f"No active {worker_role} available", "recipients": [], "umma_ref": None}
        message = format_chw_message(clinical_summary, reported_symptoms, worker_role, language) + patient_info
        success, sid, error = send_whatsapp(worker["whatsapp"], message)
        log_alert(session_id, user_id, "chw", action_tier, worker_role,
                  worker["whatsapp"], worker["name"], clinical_summary, reported_symptoms,
                  internal_diagnosis, active_differentials, language,
                  worker_id=worker["id"], message_sid=sid,
                  status="sent" if success else "failed", error_message=error)
        results.append({"name": worker["name"], "success": success})

    any_success = any(r["success"] for r in results)
    return {
        "success": any_success,
        "message": "Alert sent" if any_success else "All sends failed",
        "recipients": results,
        "umma_ref": umma_ref if any_success else None
    }
