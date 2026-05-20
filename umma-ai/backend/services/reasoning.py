import os
import json
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from openai import AzureOpenAI
from supabase import create_client
from prompts.system_prompt import UMMA_SYSTEM_PROMPT
from prompts.reasoning_prompts import DISEASE_REASONING_PROMPT, MANAGEMENT_PROMPT, TRIAGE_PROMPT
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

CONTENT_FILTER_FALLBACK = "__CONTENT_FILTER_BLOCKED__"


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


def call_llm(messages: list, temperature: float = 0.3, max_tokens: int = 1200) -> str:
    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens
    )
    return response.choices[0].message.content.strip()


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
        raw = call_llm(messages, temperature=0, max_tokens=1000)
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
        # Attempt JSON repair — truncated JSON from long Hausa text
        try:
            # Find the last complete field before truncation
            import re
            # Extract next_question if present even if JSON is malformed
            match = re.search(r'"next_question"\s*:\s*"((?:[^"\]|\.)*)"', raw)
            is_emergency = '"is_emergency": true' in raw.lower()
            needs_more = '"needs_more_info": true' in raw.lower()
            if match or is_emergency or needs_more:
                return {
                    "is_emergency": is_emergency,
                    "emergency_reason": None,
                    "needs_more_info": needs_more,
                    "next_question": match.group(1) if match else None,
                    "move_to_disease_reasoning": False,
                    "__repaired": True
                }
        except:
            pass
        return {"__parse_failed": True}


def triage_result_is_safe(result: dict) -> bool:
    if not result:
        return False
    if result.get("__content_filtered") or result.get("__parse_failed"):
        return False
    if "is_emergency" not in result:
        return False
    return True


def detect_subcategory(conversation: list) -> str:
    """
    Derives subcategory from conversation content directly,
    not from the intent string which can be misclassified.
    Returns 'pregnancy', 'child', or None.
    """
    try:
        result = call_llm_json([
            {
                "role": "system",
                "content": (
                    "You determine whether a health conversation is about a pregnant woman or a child under 5.\n"
                    "Return JSON only: {\"subcategory\": \"pregnancy\"} or {\"subcategory\": \"child\"} or {\"subcategory\": null}\n"
                    "Return 'pregnancy' if the conversation is clearly about a pregnant or postpartum woman.\n"
                    "Return 'child' if the conversation is clearly about a child or infant.\n"
                    "Return null only if genuinely unclear."
                )
            },
            {
                "role": "user",
                "content": f"Conversation: {json.dumps(conversation[-4:])}"
            }
        ])
        subcategory = result.get("subcategory")
        if subcategory in ["pregnancy", "child"]:
            print(f"DEBUG detect_subcategory: {subcategory}")
            return subcategory
    except Exception as e:
        print(f"detect_subcategory error: {e}")
    return None


def process_message(
    user_id: str,
    session_id: str,
    message: str,
    intent: str
) -> tuple:
    rag_debug = {"category": "—", "topic": "—", "chunks": []}

    def do_retrieve(stage, query, intent, conversation, topic=None, symptoms=None, extra_context=None):
        clear_retrieval_log()
        context = retrieve_for_stage(
            stage=stage,
            conversation=conversation,
            query=query,
            intent=intent,
            topic=topic,
            symptoms=symptoms,
            extra_context=extra_context
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
            # Genuinely cannot detect language — show welcome screen
            return lang_response, rag_debug
        language = chosen_language
        # Language detected from message — fall through and handle message normally in detected language

    # Always check for language switch on every message
    # detect_message_language detects both explicit switches and which language user is writing in
    detected_language = detect_language_choice(message)
    if detected_language and detected_language != language:
        save_user_language(user_id, detected_language)
        language = detected_language

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
        if intent == "general_health":
            pregnancy_context = retrieve_for_stage(
                stage="pregnancy_education",
                query=message,
                intent=intent,
                conversation=full_conversation
            )
            child_context = retrieve_for_stage(
                stage="child_health_education",
                query=message,
                intent=intent,
                conversation=full_conversation
            )
            rag_context = pregnancy_context + "\n\n========\n\n" + child_context
        else:
            rag_context = do_retrieve(intent, message, intent, full_conversation)
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
            {"role": "system", "content": UMMA_SYSTEM_PROMPT + f"\n\n{lang_instruction}"},
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

    # Detect subcategory from conversation, not just intent string
    if not state or not state.get("subcategory"):
        detected_subcategory = detect_subcategory(full_conversation)
        if not detected_subcategory:
            if "pregnancy" in intent:
                detected_subcategory = "pregnancy"
            elif "child" in intent:
                detected_subcategory = "child"
    else:
        detected_subcategory = state.get("subcategory")

    # Build reliable intent string for RAG subcategory resolution
    if detected_subcategory == "pregnancy":
        effective_intent = "pregnancy_symptom"
    elif detected_subcategory == "child":
        effective_intent = "child_symptom"
    else:
        effective_intent = intent

    if not state:
        state = {
            "stage": "triage",
            "intent": intent,
            "subcategory": detected_subcategory,
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
    else:
        if detected_subcategory and not state.get("subcategory"):
            state["subcategory"] = detected_subcategory

    # Step 6 — Extract all symptoms from full conversation
    symptoms_result = call_llm_json([
        {
            "role": "system",
            "content": """Extract ALL symptoms mentioned across the entire conversation.
Return JSON only: {"symptoms": ["symptom1", "symptom2"], "main_topic": "primary symptom in one word"}
Rules:
- Be thorough — include every symptom mentioned in any message
- Symptoms can be in English or Hausa — extract them regardless of language
- If the message is vague (e.g. "my child is not okay", "something is wrong") — return empty symptoms list
- If the message is nonsensical or unclear — return empty symptoms list
- Only extract genuine medical symptoms or complaints"""
        },
        *full_conversation
    ])

    reported_symptoms = symptoms_result.get("symptoms", []) if not symptoms_result.get("__parse_failed") else state.get("reported_symptoms", [])
    symptom_topic = symptoms_result.get("main_topic") or state.get("symptom_topic")
    state["reported_symptoms"] = reported_symptoms
    state["symptom_topic"] = symptom_topic

    # Clarification check — only on first message of a new session
    # If no symptoms extracted and this is the first user message, ask for clarification
    if state["stage"] == "triage" and state["questions_asked"] == 0 and not reported_symptoms:
        clarification = call_llm_safe([
            {"role": "system", "content": UMMA_SYSTEM_PROMPT + "\n\n" + lang_instruction}, 


            {"role": "user", "content": f"""
The user sent this message: {message}

You could not identify a clear symptom or health concern from this message.
Ask one warm, simple clarifying question to understand what health problem they need help with.
Do not assume any symptom. Do not start clinical questioning.
Do not name any condition.
Just ask what is wrong or what help they need.
Keep it to one sentence.
{lang_instruction}
"""}
        ])
        if clarification and clarification != CONTENT_FILTER_FALLBACK:
            save_message(session_id, "assistant", clarification)
            return clarification, rag_debug

    def safe_save_state(s):
        try:
            save_clinical_state(session_id, s)
        except RuntimeError:
            save_message(session_id, "assistant", TRIAGE_SAFE_FALLBACK)
            return False
        return True

    # Step 7 — TRIAGE
    if state["stage"] == "triage":
        rag_context = do_retrieve("triage", message, effective_intent, full_conversation, symptom_topic, reported_symptoms)

        triage_result = call_llm_json([
            {"role": "system", "content": UMMA_SYSTEM_PROMPT},
            {"role": "user", "content": TRIAGE_PROMPT.format(
                full_conversation=json.dumps(full_conversation),
                reported_symptoms=reported_symptoms,
                rag_context=rag_context,
                questions_asked=state["questions_asked"],
                max_triage_questions=MAX_TRIAGE_QUESTIONS,
                lang_instruction=lang_instruction
            )}
        ])

        if not triage_result_is_safe(triage_result):
            save_message(session_id, "assistant", TRIAGE_SAFE_FALLBACK)
            return TRIAGE_SAFE_FALLBACK, rag_debug

        if triage_result.get("is_emergency"):
            state["stage"] = "concluded"
            state["action_tier"] = "emergency"
            state["concluded"] = True
            if not safe_save_state(state): return TRIAGE_SAFE_FALLBACK, rag_debug
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
            query=message,
            intent=effective_intent,
            topic=symptom_topic,
            symptoms=reported_symptoms,
            conversation=full_conversation
        )
        rag_context = do_retrieve(
            "disease_reasoning", message, effective_intent, full_conversation,
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
                max_questions=MAX_REASONING_QUESTIONS,
                previous_differentials=json.dumps(state.get("active_differentials", [])),
                lang_instruction=lang_instruction
            )}
        ])

        if reasoning_result.get("__content_filtered") or reasoning_result.get("__parse_failed"):
            save_message(session_id, "assistant", REASONING_SAFE_FALLBACK)
            return REASONING_SAFE_FALLBACK, rag_debug

        questions_so_far = state["questions_asked"]
        needs_more = reasoning_result.get("needs_more_info", False)
        # If model says it's done but confidence is low or uncertain — override and keep asking
        if reasoning_result.get("confidence_level") in ["low", "uncertain"]:
            needs_more = True
        next_question = reasoning_result.get("next_question")

        # If under minimum and LLM returned no question, force one
        if (
            questions_so_far < MIN_REASONING_QUESTIONS
            and not next_question
            and questions_so_far < MAX_REASONING_QUESTIONS
        ):
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

        # Hard block — never proceed to management under minimum questions
        if questions_so_far < MIN_REASONING_QUESTIONS and not next_question:
            print(f"WARNING: Under minimum questions ({questions_so_far}/{MIN_REASONING_QUESTIONS}) and no question available — using safe fallback question")
            next_question = (
                "That is helpful to know. "
                "I want to make sure I understand your situation fully before giving you guidance. "
                "Can you tell me how long you have had these symptoms, and whether they have been getting better or worse?"
            )
            should_ask = True

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
            "management", message, effective_intent, full_conversation,
            state.get("symptom_topic"),
            state.get("reported_symptoms", []),
            extra_context={
                "active_differentials": state.get("active_differentials", []),
                "internal_diagnosis": state.get("internal_diagnosis")
            }
        )

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
    fallback = call_llm_safe([
        {"role": "system", "content": UMMA_SYSTEM_PROMPT},
        {"role": "user", "content": f"{message}\n\n{lang_instruction}"}
    ])
    if fallback == CONTENT_FILTER_FALLBACK:
        fallback = REASONING_SAFE_FALLBACK
    save_message(session_id, "assistant", fallback)
    return fallback, rag_debug
