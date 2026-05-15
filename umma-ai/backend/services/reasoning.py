import os
import json
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from openai import AzureOpenAI
from supabase import create_client
from prompts.system_prompt import UMMA_SYSTEM_PROMPT
from prompts.reasoning_prompts import DISEASE_REASONING_PROMPT, MANAGEMENT_PROMPT, TRIAGE_PROMPT  # FIX: import TRIAGE_PROMPT
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

# Safe fallback messages — used when LLM calls fail or return unusable output
TRIAGE_SAFE_FALLBACK = (
    "I am sorry, I was not able to process your message properly just now. "
    "Please try describing your symptoms again, or go to your nearest clinic if you are worried. "
    "If you have heavy bleeding, fits, difficulty breathing, or your baby has stopped moving, "
    "go to hospital immediately."
)

REASONING_SAFE_FALLBACK = (
    "I am sorry, I was not able to process your message properly just now. "
    "Please try describing your symptoms again in different words, or visit your nearest clinic if you are worried. "
    "If anything feels very serious or suddenly worse, please go to hospital immediately."
)


def get_clinical_state(session_id: str) -> dict:
    try:
        result = supabase.table("clinical_state")\
            .select("*")\
            .eq("session_id", session_id)\
            .execute()
        if result.data:
            return result.data[0]
    except Exception as e:
        print(f"Error reading clinical state for session {session_id}: {e}")
    return None


def save_clinical_state(session_id: str, state: dict):
    try:
        existing = get_clinical_state(session_id)
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
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
        # Clinical state loss is a patient safety risk — log clearly and re-raise
        # so the caller returns a safe fallback rather than continuing with stale state.
        print(f"CRITICAL: Failed to save clinical state for session {session_id}: {e}")
        raise RuntimeError(f"Clinical state save failed for session {session_id}") from e


def get_conversation_history(session_id: str) -> list:
    try:
        result = supabase.table("messages")\
            .select("role, content")\
            .eq("session_id", session_id)\
            .order("created_at")\
            .execute()
        return result.data or []
    except Exception as e:
        print(f"Error reading conversation history for session {session_id}: {e}")
        return []


def save_message(session_id: str, role: str, content: str):
    try:
        supabase.table("messages").insert({
            "session_id": session_id,
            "role": role,
            "content": content
        }).execute()
    except Exception as e:
        print(f"Error saving message for session {session_id}: {e}")


def call_llm(messages: list, temperature: float = 0.3, max_tokens: int = 700) -> str:
    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens
    )
    return response.choices[0].message.content.strip()


CONTENT_FILTER_FALLBACK = "__CONTENT_FILTER_BLOCKED__"


# FIX: call_llm_safe is now the function used for ALL clinical text responses
# Previously it was defined but never called — every clinical call used call_llm directly,
# meaning content filter errors crashed the request with no fallback response.
def call_llm_safe(messages: list, temperature: float = 0.3, max_tokens: int = 700) -> str:
    try:
        return call_llm(messages, temperature=temperature, max_tokens=max_tokens)
    except Exception as e:
        err = str(e)
        if "content_filter" in err or "ResponsibleAI" in err or "400" in err:
            print(f"Content filter triggered on LLM call: {e}")
            return CONTENT_FILTER_FALLBACK
        raise


def call_llm_json(messages: list) -> dict:
    try:
        raw = call_llm(messages, temperature=0, max_tokens=600)
    except Exception as e:
        err = str(e)
        if "content_filter" in err or "ResponsibleAI" in err or "400" in err:
            print(f"Content filter triggered on JSON call: {e}")
            return {"__content_filtered": True}
        raise
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception as e:
        print(f"call_llm_json parse failed. Error: {e}. Raw response: {raw[:300]}")
        # FIX: return a sentinel so callers can detect parse failure explicitly,
        # rather than an empty dict that silently passes all .get() safety checks
        return {"__parse_failed": True}


# FIX: triage_result_is_safe checks that the result is actionable before use.
# Previously, an empty dict from a parse failure would pass all .get() checks
# with falsy values, causing triage to be silently skipped and the user to fall
# through to disease reasoning with no emergency check performed.
def triage_result_is_safe(result: dict) -> bool:
    if not result:
        return False
    if result.get("__content_filtered") or result.get("__parse_failed"):
        return False
    # Must have at least is_emergency as an explicit key
    if "is_emergency" not in result:
        return False
    return True


def process_message(
    user_id: str,
    session_id: str,
    message: str,
    intent: str
) -> tuple:
    rag_debug = {"category": "—", "topic": "—", "chunks": []}

    # FIX: full_conversation is now passed explicitly into do_retrieve as a parameter.
    # Previously do_retrieve was a closure that referenced full_conversation from the
    # outer scope — defined before full_conversation was assigned, which worked due to
    # Python late binding but was fragile and would silently break if code was reordered.
    def do_retrieve(stage, query, intent, conversation, topic=None, symptoms=None):
        clear_retrieval_log()
        context = retrieve_for_stage(
            stage=stage,
            conversation=conversation,
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
    # Only check short messages to avoid unnecessary LLM calls during clinical conversations
    if len(message.split()) <= 8:
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
        rag_context = do_retrieve(intent, message, intent, full_conversation)
        # FIX: use call_llm_safe so content filter errors return a fallback, not a crash
        response = call_llm_safe([
            {"role": "system", "content": UMMA_SYSTEM_PROMPT + f"\n\n{lang_instruction}"},
            *history_messages,
            {"role": "user", "content": f"User message: {message}\nRelevant knowledge: {rag_context}\n{lang_instruction}"}
        ])
        if response == CONTENT_FILTER_FALLBACK:
            response = REASONING_SAFE_FALLBACK
        save_message(session_id, "assistant", response)
        return response, rag_debug

    if intent == "first_aid":
        rag_context = do_retrieve("first_aid", message, intent, conversation=full_conversation)
        response = call_llm_safe([
            {"role": "system", "content": UMMA_SYSTEM_PROMPT + f"

{lang_instruction}"},
            *history_messages,
            {"role": "user", "content": f"""
User message: {message}
First aid knowledge: {rag_context}

Give clear, calm, immediate first aid guidance.
Number every step. Keep each step short.
Tell the user what to do RIGHT NOW.
Tell them what NOT to do — common mistakes in Nigerian context.
Tell them clearly when to go to hospital.
End with a safety net.
Never replace emergency services.
{lang_instruction}
"""}
        ])
        if response == CONTENT_FILTER_FALLBACK:
            response = REASONING_SAFE_FALLBACK
        save_message(session_id, "assistant", response)
        return response, rag_debug

    if intent == "medication_safety":
        rag_context = do_retrieve("medication", message, intent, full_conversation)
        # FIX: use call_llm_safe
        response = call_llm_safe([
            {"role": "system", "content": UMMA_SYSTEM_PROMPT + f"\n\n{lang_instruction}"},
            *history_messages,
            {"role": "user", "content": f"User message: {message}\nMedication knowledge: {rag_context}\nNever give dosages. Always advise doctor or pharmacist.\n{lang_instruction}"}
        ])
        if response == CONTENT_FILTER_FALLBACK:
            response = REASONING_SAFE_FALLBACK
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

    reported_symptoms = symptoms_result.get("symptoms", []) if not symptoms_result.get("__parse_failed") else state.get("reported_symptoms", [])
    symptom_topic = symptoms_result.get("main_topic") or state.get("symptom_topic")
    state["reported_symptoms"] = reported_symptoms
    state["symptom_topic"] = symptom_topic

    # Helper defined at function scope so it is available in all stages,
    # not just triage. A DB failure during any state save returns a safe
    # fallback response rather than crashing with an UnboundLocalError.
    def safe_save_state(s):
        try:
            save_clinical_state(session_id, s)
        except RuntimeError:
            save_message(session_id, "assistant", TRIAGE_SAFE_FALLBACK)
            return False
        return True

    # Step 7 — TRIAGE
    if state["stage"] == "triage":
        rag_context = do_retrieve("triage", message, intent, full_conversation, symptom_topic, reported_symptoms)

        triage_result = call_llm_json([
            {"role": "system", "content": UMMA_SYSTEM_PROMPT},
            {"role": "user", "content": TRIAGE_PROMPT.format(  # FIX: use named constant from reasoning_prompts.py
                full_conversation=json.dumps(full_conversation),
                reported_symptoms=reported_symptoms,
                rag_context=rag_context,
                questions_asked=state["questions_asked"],
                max_triage_questions=MAX_TRIAGE_QUESTIONS
            )}
        ])

        # FIX: explicitly validate the triage result before acting on it.
        # An empty dict or parse failure previously fell through all checks silently,
        # skipping the emergency gate and sending the user into disease reasoning
        # without any red flag check having been performed.
        if not triage_result_is_safe(triage_result):
            save_message(session_id, "assistant", TRIAGE_SAFE_FALLBACK)
            return TRIAGE_SAFE_FALLBACK, rag_debug


        if triage_result.get("is_emergency"):
            state["stage"] = "concluded"
            state["action_tier"] = "emergency"
            state["concluded"] = True
            if not safe_save_state(state): return TRIAGE_SAFE_FALLBACK, rag_debug
            # use call_llm_safe for the emergency response
            response = call_llm_safe([
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
            if response == CONTENT_FILTER_FALLBACK:
                response = TRIAGE_SAFE_FALLBACK
            save_message(session_id, "assistant", response)
            return response, rag_debug

        if triage_result.get("needs_more_info") and state["questions_asked"] < MAX_TRIAGE_QUESTIONS:
            next_question = triage_result.get("next_question", "")
            state["questions_asked"] += 1
            if not safe_save_state(state): return TRIAGE_SAFE_FALLBACK, rag_debug
            save_message(session_id, "assistant", next_question)
            return next_question, rag_debug

        state["stage"] = "disease_reasoning"
        state["questions_asked"] = 0
        if not safe_save_state(state): return TRIAGE_SAFE_FALLBACK, rag_debug

    # Step 8 — DISEASE REASONING
    if state["stage"] == "disease_reasoning":
        symptom_context = retrieve_for_stage(
            stage="triage",
            conversation=full_conversation,
            query=message,
            intent=intent,
            topic=symptom_topic,
            symptoms=reported_symptoms
        )
        rag_context = do_retrieve(
            "disease_reasoning", message, intent, full_conversation,
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

        if reasoning_result.get("__content_filtered") or reasoning_result.get("__parse_failed"):
            save_message(session_id, "assistant", REASONING_SAFE_FALLBACK)
            return REASONING_SAFE_FALLBACK, rag_debug

        questions_so_far = state["questions_asked"]
        needs_more = reasoning_result.get("needs_more_info", False)
        next_question = reasoning_result.get("next_question")

        # Floor enforcement: if under minimum, generate a fallback question
        # rather than allowing the LLM to skip ahead with next_question=null.
        if (
            questions_so_far < MIN_REASONING_QUESTIONS
            and not next_question
            and questions_so_far < MAX_REASONING_QUESTIONS
        ):
            # LLM tried to conclude too early — ask it for a question explicitly
            followup = call_llm_json([
                {"role": "system", "content": UMMA_SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"You are mid-way through clinical reasoning for: {reported_symptoms}. "
                    f"You have only asked {questions_so_far} questions but the minimum is {MIN_REASONING_QUESTIONS}. "
                    f"Active differentials: {reasoning_result.get('active_differentials', [])}. "
                    "You MUST ask one more clarifying question following the 3-part format. "
                    'Return JSON only: {"next_question": "your 3-part question here", "question_rationale": "why"}'
                )}
            ])
            if not followup.get("__parse_failed") and not followup.get("__content_filtered"):
                next_question = followup.get("next_question")

        should_ask = (
            (needs_more or questions_so_far < MIN_REASONING_QUESTIONS)
            and questions_so_far < MAX_REASONING_QUESTIONS
            and next_question
        )

        if should_ask:
            state["questions_asked"] += 1
            state["question_rationale"] = reasoning_result.get("question_rationale", "")
            state["active_differentials"] = reasoning_result.get("active_differentials", [])
            state["internal_diagnosis"] = reasoning_result.get("primary_diagnosis")
            state["secondary_diagnosis"] = reasoning_result.get("secondary_diagnosis")
            state["confidence_level"] = reasoning_result.get("confidence_level")
            state["action_tier"] = reasoning_result.get("action_tier")
            if not safe_save_state(state): return REASONING_SAFE_FALLBACK, rag_debug
            save_message(session_id, "assistant", next_question)
            return next_question, rag_debug

        # Conclude reasoning
        state["stage"] = "management"
        state["internal_diagnosis"] = reasoning_result.get("primary_diagnosis")
        state["secondary_diagnosis"] = reasoning_result.get("secondary_diagnosis")
        state["active_differentials"] = reasoning_result.get("active_differentials", [])
        state["confidence_level"] = reasoning_result.get("confidence_level")
        state["action_tier"] = reasoning_result.get("action_tier")
        state["question_rationale"] = reasoning_result.get("question_rationale")
        state["concluded"] = True
        if not safe_save_state(state): return REASONING_SAFE_FALLBACK, rag_debug

    # Step 9 — MANAGEMENT
    if state["stage"] in ["management", "concluded"]:
        rag_context = do_retrieve(
            "management", message, intent, full_conversation,
            state.get("symptom_topic"),
            state.get("reported_symptoms", [])
        )

        # FIX: use call_llm_safe for the management response
        response = call_llm_safe([
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
        if response == CONTENT_FILTER_FALLBACK:
            response = REASONING_SAFE_FALLBACK
        save_message(session_id, "assistant", response)
        return response, rag_debug

    # Fallback
    # FIX: use call_llm_safe
    fallback = call_llm_safe([
        {"role": "system", "content": UMMA_SYSTEM_PROMPT},
        {"role": "user", "content": f"{message}\n\n{lang_instruction}"}
    ])
    if fallback == CONTENT_FILTER_FALLBACK:
        fallback = REASONING_SAFE_FALLBACK
    save_message(session_id, "assistant", fallback)
    return fallback, rag_debug
