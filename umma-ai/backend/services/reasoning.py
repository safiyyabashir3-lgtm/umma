import os
import json
from dotenv import load_dotenv
from openai import AzureOpenAI
from supabase import create_client
from prompts.system_prompt import UMMA_SYSTEM_PROMPT
from prompts.reasoning_prompts import DISEASE_REASONING_PROMPT, MANAGEMENT_PROMPT
from services.rag import retrieve_for_stage, clear_retrieval_log
from services.language import (
    get_user_language,
    save_user_language,
    detect_language_choice,
    language_instruction,
    handle_first_message
)

load_dotenv("/workspaces/umma/umma-ai/.env")

client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION")
)

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

MAX_TRIAGE_QUESTIONS = 3
MIN_REASONING_QUESTIONS = 2
MAX_REASONING_QUESTIONS = 5


def get_clinical_state(session_id: str) -> dict:
    try:
        result = supabase.table("clinical_state")\
            .select("*")\
            .eq("session_id", session_id)\
            .execute()
        if result.data:
            return result.data[0]
    except:
        pass
    return None


def save_clinical_state(session_id: str, state: dict):
    try:
        existing = get_clinical_state(session_id)
        state["updated_at"] = "now()"
        if existing:
            supabase.table("clinical_state")\
                .update(state)\
                .eq("session_id", session_id)\
                .execute()
        else:
            state["session_id"] = session_id
            supabase.table("clinical_state")\
                .insert(state)\
                .execute()
    except Exception as e:
        print(f"Error saving clinical state: {e}")


def get_conversation_history(session_id: str) -> list:
    try:
        result = supabase.table("messages")\
            .select("role, content")\
            .eq("session_id", session_id)\
            .order("created_at")\
            .execute()
        return result.data or []
    except:
        return []


def save_message(session_id: str, role: str, content: str):
    try:
        supabase.table("messages").insert({
            "session_id": session_id,
            "role": role,
            "content": content
        }).execute()
    except Exception as e:
        print(f"Error saving message: {e}")


def call_llm(messages: list, temperature: float = 0.3, max_tokens: int = 700) -> str:
    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens
    )
    return response.choices[0].message.content.strip()


CONTENT_FILTER_FALLBACK = "__CONTENT_FILTER_BLOCKED__"

def call_llm_safe(messages: list, temperature: float = 0.3, max_tokens: int = 700) -> str:
    try:
        return call_llm(messages, temperature=temperature, max_tokens=max_tokens)
    except Exception as e:
        if "content_filter" in str(e) or "ResponsibleAI" in str(e) or "400" in str(e):
            print(f"Content filter triggered on LLM call: {e}")
            return CONTENT_FILTER_FALLBACK
        raise

def call_llm_json(messages: list) -> dict:
    try:
        raw = call_llm(messages, temperature=0, max_tokens=600)
    except Exception as e:
        if "content_filter" in str(e) or "ResponsibleAI" in str(e) or "400" in str(e):
            print(f"Content filter triggered on JSON call: {e}")
            return {"__content_filtered": True}
        raise
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception as e:
        print(f"call_llm_json parse failed. Error: {e}. Raw response: {raw[:300]}")
        return {}


def process_message(
    user_id: str,
    session_id: str,
    message: str,
    intent: str
) -> tuple:
    rag_debug = {"category": "—", "topic": "—", "chunks": []}

    def do_retrieve(stage, query, intent, topic=None, symptoms=None):
        clear_retrieval_log()
        context = retrieve_for_stage(
            stage=stage,
            conversation=full_conversation,
            query=query,
            intent=intent,
            topic=topic,
            symptoms=symptoms
        )
        rag_debug["category"] = stage
        rag_debug["topic"] = topic or "—"
        if context:
            chunks = context.split("\n\n---\n\n")
            rag_debug["chunks"] = [c[:150] for c in chunks[:8]]
        return context

    # Step 1 — Language
    language = get_user_language(user_id)
    if not language:
        chosen_language, lang_response = handle_first_message(user_id, message)
        if not chosen_language:
            return lang_response, rag_debug
        language = chosen_language

    # Check if user is switching language mid-conversation
    language_switch = detect_language_choice(message)
    if language_switch and language_switch != language:
        save_user_language(user_id, language_switch)
        language = language_switch

    lang_instruction = language_instruction(language)

    # Step 2 — Save user message
    save_message(session_id, "user", message)

    # Step 3 — History
    history = get_conversation_history(session_id)
    history_messages = [
        {"role": h["role"], "content": h["content"]}
        for h in history[:-1]
    ]
    full_conversation = history_messages + [{"role": "user", "content": message}]

    # Step 4 — Non-symptom intents
    if intent in ["pregnancy_info", "child_health_info", "general_health"]:
        rag_context = do_retrieve(intent, message, intent)
        response = call_llm([
            {"role": "system", "content": UMMA_SYSTEM_PROMPT + f"\n\n{lang_instruction}"},
            *history_messages,
            {"role": "user", "content": f"User message: {message}\nRelevant knowledge: {rag_context}\n{lang_instruction}"}
        ])
        save_message(session_id, "assistant", response)
        return response, rag_debug

    if intent == "medication_safety":
        rag_context = do_retrieve("medication", message, intent)
        response = call_llm([
            {"role": "system", "content": UMMA_SYSTEM_PROMPT + f"\n\n{lang_instruction}"},
            *history_messages,
            {"role": "user", "content": f"User message: {message}\nMedication knowledge: {rag_context}\nNever give dosages. Always advise doctor or pharmacist.\n{lang_instruction}"}
        ])
        save_message(session_id, "assistant", response)
        return response, rag_debug

    # Step 5 — Symptom flow
    state = get_clinical_state(session_id)
    if not state:
        state = {
            "stage": "triage",
            "intent": intent,
            "symptom_topic": None,
            "reported_symptoms": [],
            "internal_diagnosis": None,
            "secondary_diagnosis": None,
            "active_differentials": [],
            "confidence_level": None,
            "action_tier": None,
            "questions_asked": 0,
            "concluded": False
        }

    # Step 6 — Extract all symptoms from full conversation
    symptoms_result = call_llm_json([
        {
            "role": "system",
            "content": """Extract ALL symptoms mentioned across the entire conversation.
Return JSON only: {"symptoms": ["symptom1", "symptom2"], "main_topic": "primary symptom in one word"}
Be thorough — include every symptom mentioned in any message."""
        },
        *full_conversation
    ])

    reported_symptoms = symptoms_result.get("symptoms", [])
    symptom_topic = symptoms_result.get("main_topic") or state.get("symptom_topic")
    state["reported_symptoms"] = reported_symptoms
    state["symptom_topic"] = symptom_topic

    # Step 7 — TRIAGE
    if state["stage"] == "triage":
        rag_context = do_retrieve("triage", message, intent, symptom_topic, reported_symptoms)

        triage_result = call_llm_json([
            {"role": "system", "content": UMMA_SYSTEM_PROMPT},
            {"role": "user", "content": f"""
You are UMMA in TRIAGE stage for a Nigerian maternal/child health app.
Full conversation: {json.dumps(full_conversation)}
Reported symptoms: {reported_symptoms}
Clinical knowledge: {rag_context}
Triage questions asked: {state['questions_asked']}
Maximum triage questions: {MAX_TRIAGE_QUESTIONS}

Your job: Check for emergency red flags ONLY. Do NOT give management advice. Do NOT start disease reasoning.

EMERGENCY RED FLAGS — escalate immediately if any are present:
- Heavy vaginal bleeding
- Severe headache with blurred vision or spots
- No fetal movement
- Seizures or convulsions
- Difficulty breathing at rest
- High fever in child under 3 months
- Child unresponsive or unable to drink
- Severe vomiting unable to keep any fluid down

QUESTION RULES:
- Ask ONE question at a time only
- Never ask about something already answered in the conversation
- If ANY red flag already confirmed in conversation — is_emergency: true immediately
- If no red flags confirmed and under question limit — ask the single highest-yield red flag question remaining
- If no red flags and at question limit — move_to_disease_reasoning: true

HOW TO FORMAT next_question — MANDATORY 3-PART STRUCTURE:
Part 1: One sentence that responds to what she just said — not repeating or summarising her symptoms back to her, but showing you understood. A brief human reaction. Example: Headache and fever together in pregnancy always deserve careful attention.
Part 2: One sentence explaining what you are checking for in plain language.
Part 3: One question only.

Return JSON only:
{{
  "is_emergency": true or false,
  "emergency_reason": "plain language reason if emergency, null otherwise",
  "needs_more_info": true or false,
  "next_question": "structured 3-part question if needed, null otherwise",
  "move_to_disease_reasoning": true or false
}}
"""}
        ])

        if triage_result.get("__content_filtered"):
            fallback = (
                "I am sorry, I was not able to process your message properly just now. "
                "Please try describing your symptoms again, or go to your nearest clinic if you are worried. "
                "If you have heavy bleeding, fits, difficulty breathing, or your baby has stopped moving, "
                "go to hospital immediately."
            )
            save_message(session_id, "assistant", fallback)
            return fallback, rag_debug

        if triage_result.get("is_emergency"):
            state["stage"] = "concluded"
            state["action_tier"] = "emergency"
            state["concluded"] = True
            save_clinical_state(session_id, state)
            response = call_llm([
                {"role": "system", "content": UMMA_SYSTEM_PROMPT},
                {"role": "user", "content": f"""
A woman has a medical emergency.
Emergency reason: {triage_result.get('emergency_reason')}
Symptoms: {reported_symptoms}

YOUR RESPONSE MUST:
1. In one sentence — acknowledge what she is experiencing. Name her specific symptom. Do not be generic.
2. In one sentence — tell her plainly that what she is describing is serious and needs immediate hospital care.
3. Give ONE clear instruction: go to hospital now. Tell her there is no safe home management for this.
4. Tell her what to do in the next 5 minutes — call someone, do not go alone, go to the nearest facility with maternity or emergency care.
5. End with the single most important warning sign to watch for on the way.

DO NOT give home management advice.
DO NOT name any diagnosis.
DO NOT use hollow reassuring phrases.
DO NOT make it longer than it needs to be — she needs to act, not read.
{lang_instruction}
"""}
            ])
            save_message(session_id, "assistant", response)
            return response, rag_debug

        if triage_result.get("needs_more_info") and state["questions_asked"] < MAX_TRIAGE_QUESTIONS:
            next_question = triage_result.get("next_question", "")
            state["questions_asked"] += 1
            save_clinical_state(session_id, state)
            save_message(session_id, "assistant", next_question)
            return next_question, rag_debug

        state["stage"] = "disease_reasoning"
        state["questions_asked"] = 0
        save_clinical_state(session_id, state)

    # Step 8 — DISEASE REASONING
    if state["stage"] == "disease_reasoning":
        # Retrieve symptom files first (triage stage = symptoms category)
        # Then retrieve disease files — do_retrieve must be called last to set correct debug info
        symptom_context = retrieve_for_stage(
            stage="triage",
            conversation=full_conversation,
            query=message,
            intent=intent,
            topic=symptom_topic,
            symptoms=reported_symptoms
        )
        rag_context = do_retrieve(
            "disease_reasoning", message, intent,
            symptom_topic, reported_symptoms
        )

        reasoning_result = call_llm_json([
            {"role": "system", "content": UMMA_SYSTEM_PROMPT},
            {"role": "user", "content": DISEASE_REASONING_PROMPT.format(
                full_conversation=json.dumps(full_conversation),
                reported_symptoms=reported_symptoms,
                symptom_topic=symptom_topic,
                intent=intent,
                rag_context=rag_context,
                symptom_context=symptom_context,
                questions_asked=state["questions_asked"],
                min_questions=MIN_REASONING_QUESTIONS,
                max_questions=MAX_REASONING_QUESTIONS
            )}
        ])

        if reasoning_result.get("__content_filtered"):
            fallback = (
                "I am sorry, I was not able to process your message properly just now. "
                "Please try describing your symptoms again in different words, or visit your nearest clinic if you are worried. "
                "If anything feels very serious or suddenly worse, please go to hospital immediately."
            )
            save_message(session_id, "assistant", fallback)
            return fallback, rag_debug

        questions_so_far = state["questions_asked"]
        needs_more = reasoning_result.get("needs_more_info", False)
        next_question = reasoning_result.get("next_question")

        should_ask = (
            (needs_more or questions_so_far < MIN_REASONING_QUESTIONS)
            and questions_so_far < MAX_REASONING_QUESTIONS
            and next_question
        )

        if should_ask:
            state["questions_asked"] += 1
            state["question_rationale"] = reasoning_result.get("question_rationale") or reasoning_result.get("question_rationale", "")
            state["active_differentials"] = reasoning_result.get("active_differentials", [])
            state["internal_diagnosis"] = reasoning_result.get("primary_diagnosis")
            state["secondary_diagnosis"] = reasoning_result.get("secondary_diagnosis")
            state["confidence_level"] = reasoning_result.get("confidence_level")
            state["action_tier"] = reasoning_result.get("action_tier")
            save_clinical_state(session_id, state)
            save_message(session_id, "assistant", next_question)
            return next_question, rag_debug

        # Save conclusion
        state["stage"] = "management"
        state["internal_diagnosis"] = reasoning_result.get("primary_diagnosis")
        state["secondary_diagnosis"] = reasoning_result.get("secondary_diagnosis")
        state["active_differentials"] = reasoning_result.get("active_differentials", [])
        state["confidence_level"] = reasoning_result.get("confidence_level")
        state["action_tier"] = reasoning_result.get("action_tier")
        state["question_rationale"] = reasoning_result.get("question_rationale")
        state["concluded"] = True
        save_clinical_state(session_id, state)

    # Step 9 — MANAGEMENT
    if state["stage"] in ["management", "concluded"]:
        rag_context = do_retrieve(
            "management", message, intent,
            state.get("symptom_topic"),
            state.get("reported_symptoms", [])
        )

        response = call_llm([
            {"role": "system", "content": UMMA_SYSTEM_PROMPT},
            {"role": "user", "content": MANAGEMENT_PROMPT.format(
                full_conversation=json.dumps(full_conversation),
                reported_symptoms=state.get("reported_symptoms"),
                internal_diagnosis=state.get("internal_diagnosis"),
                secondary_diagnosis=state.get("secondary_diagnosis"),
                active_differentials=state.get("active_differentials", []),
                confidence_level=state.get("confidence_level"),
                action_tier=state.get("action_tier"),
                rag_context=rag_context,
                lang_instruction=lang_instruction
            )}
        ])

        save_message(session_id, "assistant", response)
        return response, rag_debug

    # Fallback
    fallback = call_llm([
        {"role": "system", "content": UMMA_SYSTEM_PROMPT},
        {"role": "user", "content": f"{message}\n\n{lang_instruction}"}
    ])
    save_message(session_id, "assistant", fallback)
    return fallback, rag_debug
