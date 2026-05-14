import os
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

def detect_language_choice(message: str) -> str:
    """
    Uses GPT-4.1 to detect explicit language selection.
    Handles English, Hausa, and mixed expressions naturally.
    Returns 'en', 'ha', or None if no explicit choice made.
    """
    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT,
            messages=[
                {
                    "role": "system",
                    "content": """You detect whether a user is explicitly choosing a language.
The app supports English and Hausa.
Return JSON only: {"language": "en"} or {"language": "ha"} or {"language": null}

Return "en" if the user is choosing English in any way — e.g. "English", "I want English", "speak English to me", "English please"
Return "ha" if the user is choosing Hausa in any way — e.g. "Hausa", "Hausa ne", "da Hausa", "in Hausa", "Ina son Hausa"
Return null if the message is not a language selection — e.g. "I have a fever", "hello", "what is malaria"
Also return "en" or "ha" if user wants to switch language mid-conversation."""
                },
                {"role": "user", "content": message}
            ],
            temperature=0,
            max_tokens=20
        )
        import json
        raw = response.choices[0].message.content.strip()
        clean = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
        lang = result.get("language")
        return lang if lang in ["en", "ha"] else None
    except:
        return None

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
    Returns (language, response) or (None, welcome_message)
    """
    chosen = detect_language_choice(message)

    if chosen == "en":
        save_user_language(user_id, "en")
        return "en", (
            "I will speak with you in English.\n\n"
            "I am UMMA, your trusted health companion for pregnancy "
            "and child health. How can I help you today?"
        )

    if chosen == "ha":
        save_user_language(user_id, "ha")
        return "ha", (
            "Zan yi magana da ke cikin Hausa.\n\n"
            "Ni UMMA ce, abokin lafiyar ku na lokacin juna biyu "
            "da lafiyar yara. Yaya zan iya taimaka muku yau?"
        )

    return None, WELCOME_MESSAGE
