from openai import AzureOpenAI
import os
from dotenv import load_dotenv
from prompts.system_prompt import UMMA_SYSTEM_PROMPT

load_dotenv()

client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION")
)

DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

def reason_symptom(message: str, rag_context: str, intent: str) -> dict:
    triage_response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {"role": "system", "content": UMMA_SYSTEM_PROMPT},
            {"role": "user", "content": f"""
STEP 1 - TRIAGE ONLY.
User message: {message}
Relevant medical context: {rag_context}

Is this a red flag emergency requiring immediate hospital visit?
Respond in JSON: {{"is_emergency": true/false, "reason": "brief reason"}}
Only JSON. Nothing else.
"""}
        ],
        temperature=0,
        max_tokens=100
    )

    import json
    triage_text = triage_response.choices[0].message.content.strip()
    try:
        triage = json.loads(triage_text)
    except:
        triage = {"is_emergency": False, "reason": "unclear"}

    if triage.get("is_emergency"):
        return {
            "triage": triage,
            "clinical_reasoning": None,
            "advice": f"⚠️ This sounds serious. {triage['reason']}. Please go to the nearest hospital or clinic immediately. Do not wait."
        }

    clinical_response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {"role": "system", "content": UMMA_SYSTEM_PROMPT},
            {"role": "user", "content": f"""
STEP 2 - CLINICAL REASONING.
User message: {message}
Intent: {intent}
Relevant medical context: {rag_context}

What are the 2-3 most likely causes of these symptoms in a Nigerian context?
Consider common Nigerian conditions (malaria, anaemia, pre-eclampsia, typhoid, malnutrition etc.)
Respond in JSON: {{"likely_causes": ["cause1", "cause2"], "reasoning": "brief explanation"}}
Only JSON. Nothing else.
"""}
        ],
        temperature=0.2,
        max_tokens=200
    )

    clinical_text = clinical_response.choices[0].message.content.strip()
    try:
        clinical = json.loads(clinical_text)
    except:
        clinical = {"likely_causes": [], "reasoning": "unclear"}

    advice_response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {"role": "system", "content": UMMA_SYSTEM_PROMPT},
            {"role": "user", "content": f"""
STEP 3 - ADVICE.
User message: {message}
Intent: {intent}
Likely causes: {clinical.get('likely_causes')}
Relevant medical context: {rag_context}

Give warm, clear, safe advice to this Nigerian mother.
Include: what to do now, any safe home care, and when to go to hospital.
Speak simply. Be reassuring but honest. End with a reminder to see a doctor if symptoms worsen.
"""}
        ],
        temperature=0.4,
        max_tokens=400
    )

    advice = advice_response.choices[0].message.content.strip()

    return {
        "triage": triage,
        "clinical_reasoning": clinical,
        "advice": advice
    }


def respond_general(message: str, rag_context: str, intent: str) -> str:
    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {"role": "system", "content": UMMA_SYSTEM_PROMPT},
            {"role": "user", "content": f"""
User message: {message}
Intent: {intent}
Relevant context from medical knowledge base: {rag_context}

Respond warmly and clearly as UMMA. Ground your answer in the provided context.
If the context is insufficient, say so honestly and advise seeing a doctor.
"""}
        ],
        temperature=0.4,
        max_tokens=400
    )
    return response.choices[0].message.content.strip()
