import os
import json
from dotenv import load_dotenv
from openai import AzureOpenAI
from supabase import create_client

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

WELCOME_MESSAGE = (
    "Welcome to UMMA! / Barka da zuwa UMMA!\n\n"
    "I am your trusted health companion for pregnancy and child health.\n"
    "Ni ce abokin lafiyar ku na lokacin juna biyu da lafiyar yara.\n\n"
    "Please choose your language / Don Allah zaɓi yaren ku:\n\n"
    "Type **English** or **Hausa**"
)

def get_user_language(user_id: str) -> str:
    try:
        result = supabase.table("user_preferences")\
            .select("language")\
            .eq("user_id", user_id)\
            .execute()
        if result.data:
            return result.data[0]["language"]
    except:
        pass
    return None

def save_user_language(user_id: str, language: str):
    try:
        existing = get_user_language(user_id)
        if existing:
            supabase.table("user_preferences")\
                .update({"language": language})\
                .eq("user_id", user_id)\
                .execute()
        else:
            supabase.table("user_preferences")\
                .insert({"user_id": user_id, "language": language})\
                .execute()
    except Exception as e:
        print(f"Error saving language: {e}")

def detect_message_language(message: str) -> str:
    """
    Detects which language a message is written in OR if user is explicitly choosing a language.
    Returns 'en', 'ha', or None if genuinely unclear.
    This handles both:
    - Explicit selections: "English", "Hausa", "speak Hausa to me"
    - Implicit detection: user writes in Hausa or English
    """
    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT,
            messages=[
                {
                    "role": "system",
                    "content": """You detect the language of a user message for a Nigerian health app that supports English and Hausa.

Return JSON only: {"language": "en"} or {"language": "ha"} or {"language": null}

Return "en" if:
- The message is written in English
- The user is explicitly choosing English e.g. "English", "speak English"

Return "ha" if:
- The message is written in Hausa
- The user is explicitly choosing Hausa e.g. "Hausa", "Hausa ne", "da Hausa"

Return null only if:
- The message is so short or ambiguous that language cannot be determined e.g. "ok", "yes", "no", numbers only

Important: Even short health messages have enough signal. "I have fever" = en. "Ina da zazzabi" = ha."""
                },
                {"role": "user", "content": message}
            ],
            temperature=0,
            max_tokens=20
        )
        raw = response.choices[0].message.content.strip()
        clean = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
        lang = result.get("language")
        return lang if lang in ["en", "ha"] else None
    except:
        return None

def detect_language_choice(message: str) -> str:
    """
    Wrapper kept for compatibility.
    Now uses full language detection instead of explicit-only detection.
    """
    return detect_message_language(message)

def language_instruction(language: str) -> str:
    if language == "ha":
        return (
            "Respond entirely in Hausa language. "
            "Be warm and culturally appropriate for northern Nigeria. "
            "Use simple everyday Hausa that uneducated women can understand."
        )
    return (
        "Respond in clear simple English. "
        "Avoid medical jargon. "
        "Use short sentences."
    )

def handle_first_message(user_id: str, message: str) -> tuple:
    """
    Called when user has no language preference yet.
    Detects language from the message itself — both explicit selections and natural language.
    Returns (language, None) if language detected — caller proceeds normally with that language.
    Returns (None, welcome_message) only if language genuinely cannot be determined.
    """
    detected = detect_message_language(message)

    if detected == "en":
        save_user_language(user_id, "en")
        return "en", None  # Return None so caller handles the message normally

    if detected == "ha":
        save_user_language(user_id, "ha")
        return "ha", None  # Return None so caller handles the message normally

    # Genuinely unclear — show welcome screen
    return None, WELCOME_MESSAGE
