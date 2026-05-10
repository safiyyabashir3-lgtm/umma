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

def detect_explicit_language_choice(message: str) -> str:
    """
    Only returns a language if user explicitly chose one.
    Does not infer from general messages.
    """
    msg = message.strip().lower()

    # Explicit English choices
    if msg in ["english", "en", "inglish", "inglis"]:
        return "en"

    # Explicit Hausa choices
    if msg in ["hausa", "ha", "hause"]:
        return "ha"

    # Check for switch requests mid-conversation
    if any(phrase in msg for phrase in [
        "switch to hausa", "change to hausa", "speak hausa",
        "in hausa", "da hausa"
    ]):
        return "ha"

    if any(phrase in msg for phrase in [
        "switch to english", "change to english", "speak english",
        "in english"
    ]):
        return "en"

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
    chosen = detect_explicit_language_choice(message)

    if chosen == "en":
        save_user_language(user_id, "en")
        return "en", (
            "Thank you! I will speak with you in English.\n\n"
            "I am UMMA, your trusted health companion for pregnancy "
            "and child health. How can I help you today?"
        )

    if chosen == "ha":
        save_user_language(user_id, "ha")
        return "ha", (
            "Nagode! Zan yi magana da ke cikin Hausa.\n\n"
            "Ni UMMA ce, abokin lafiyar ku na lokacin juna biyu "
            "da lafiyar yara. Yaya zan iya taimaka muku yau?"
        )

    # No explicit choice — show welcome and ask again
    return None, WELCOME_MESSAGE
