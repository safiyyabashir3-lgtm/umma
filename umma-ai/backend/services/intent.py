import os
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv("/workspaces/umma/umma-ai/.env")

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
    "emergency",
    "first_aid"
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
- If the message describes a symptom, pain, discomfort, or illness in a pregnant woman: pregnancy_symptom
- If the message describes a symptom, pain, discomfort, or illness in a child: child_symptom
- If the message asks whether a medicine or treatment is safe, or about drug interactions: medication_safety
- If the message describes poisoning, choking, burns, foreign body in eye/ear/nose, animal bite, head injury, drowning, or any acute injury: first_aid
- If it sounds like an immediate life-threatening emergency: emergency
- If asking for information about pregnancy, antenatal care, nutrition in pregnancy, breastfeeding, danger signs in pregnancy, or general pregnancy guidance (not a symptom): pregnancy_info
- If asking for information about child health, vaccines, child nutrition, newborn care, developmental milestones, or general child health guidance (not a symptom): child_health_info
- If the message is a greeting, general question, or does not fit any above category: general_health

Respond with ONLY the intent label. Nothing else."""
            },
            {"role": "user", "content": message}
        ],
        temperature=0,
        max_tokens=20
    )
    intent = response.choices[0].message.content.strip().lower()
    return intent if intent in INTENTS else "general_health"
