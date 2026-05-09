from openai import AzureOpenAI
import os
from dotenv import load_dotenv

load_dotenv()

client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION")
)

DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

INTENTS = [
    "pregnancy_symptom",
    "child_symptom",
    "medication_safety",
    "pregnancy_info",
    "child_health_info",
    "general_health",
    "emergency"
]

def classify_intent(message: str) -> str:
    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": f"""You are an intent classifier for a maternal health app.
Classify the user message into exactly one of these intents:
{', '.join(INTENTS)}

Rules:
- If the message describes a symptom in a pregnant woman, return: pregnancy_symptom
- If the message describes a symptom in a child, return: child_symptom
- If the message asks about medicine safety, return: medication_safety
- If it sounds like an emergency, return: emergency
- Otherwise classify as best fits

Respond with ONLY the intent label. Nothing else."""
            },
            {"role": "user", "content": message}
        ],
        temperature=0,
        max_tokens=20
    )
    intent = response.choices[0].message.content.strip().lower()
    return intent if intent in INTENTS else "general_health"
