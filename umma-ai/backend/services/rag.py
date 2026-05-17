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

import threading

_local = threading.local()

def _get_log():
    if not hasattr(_local, "retrieval_log"):
        _local.retrieval_log = []
    return _local.retrieval_log

def get_retrieval_log():
    return _get_log().copy()

def clear_retrieval_log():
    _get_log().clear()


# ─── VALID TOPIC VOCABULARIES (sourced directly from DB) ──────────────────────

SYMPTOM_TOPICS_PREGNANCY = [
    "abdominalpain", "bleeding", "breathlessness", "fetal", "fever",
    "headache", "oedema", "postpartum_bleeding", "urinary", "vaginal_discharge", "vomiting"
]

SYMPTOM_TOPICS_CHILD = [
    "abdominal_pain", "abdominal_swelling", "breathing", "conjunctivitis",
    "convulsion", "cord", "cough", "diarrhoea", "ear_pain", "excessive_crying",
    "fever", "jaundice", "poor_feeding", "rash", "toothache", "urinary", "vomiting"
]

SYMPTOM_CARE_TOPICS_PREGNANCY = [
    "abdominal_pain", "bleeding", "breathlessness", "discharge", "fever",
    "headache", "oedema", "postpartum_bleeding", "urinary", "vomiting"
]

SYMPTOM_CARE_TOPICS_CHILD = [
    "abdominal_pain", "breathing", "convulsion", "cough", "crying",
    "diarrhoea", "ear", "eye", "feeding", "fever", "rash", "toothache", "urinary", "vomiting"
]

DISEASE_TOPICS_PREGNANCY = [
    "abruption", "anaemia", "asthma", "chorioamnionitis", "ectopic",
    "fetal_distress", "hyperemesis", "IUGR", "labour", "malaria",
    "miscarriage", "placenta praevia", "pneumonia", "preeclampsia",
    "STIs", "uti", "vaginosis"
]

DISEASE_TOPICS_CHILD = [
    "bronchiolitis", "chickenpox", "cholera", "colic", "conjunctivitis",
    "croup", "dental caries", "dysentery", "gastroenteritis", "helminthiasis",
    "intestinal_obstruction", "malaria", "malnutrition", "measles", "meningitis",
    "miliaria", "otitis", "pneumonia", "sicklecell", "skin infections",
    "thrush", "tuberculosis", "typhoid", "UTI"
]


def resolve_subcategory(intent: str, fallback: str = None) -> str:
    if "pregnancy" in intent:
        return "pregnancy"
    elif "child" in intent:
        return "child"
    return fallback


def map_symptoms_to_topics(
    reported_symptoms: list,
    subcategory: str,
    category: str,
    conversation: list = None,
    active_differentials: list = None
) -> list:
    if category == "symptoms":
        valid_topics = SYMPTOM_TOPICS_PREGNANCY if subcategory == "pregnancy" else SYMPTOM_TOPICS_CHILD
    elif category == "symptom_care":
        valid_topics = SYMPTOM_CARE_TOPICS_PREGNANCY if subcategory == "pregnancy" else SYMPTOM_CARE_TOPICS_CHILD
    else:
        return []

    extra_context = ""
    if active_differentials:
        extra_context += f"Active differentials being considered: {json.dumps(active_differentials)}\n"
    if conversation:
        extra_context += f"Recent conversation: {json.dumps(conversation[-4:])}\n"

    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You map clinical information to database topic keys.\n"
                        "You MUST only return topics from the valid list provided.\n"
                        "Consider reported symptoms AND active differentials when selecting topics.\n"
                        "For example: if malaria is a differential, include 'fever'. "
                        "If preeclampsia is a differential, include 'headache' and 'oedema'.\n"
                        "Do not invent or modify any topic.\n"
                        f"Valid topics: {json.dumps(valid_topics)}\n\n"
                        f"{extra_context}"
                        'Return JSON only: {"topics": ["topic1", "topic2"]}'
                    )
                },
                {
                    "role": "user",
                    "content": f"Reported symptoms: {json.dumps(reported_symptoms)}"
                }
            ],
            temperature=0,
            max_tokens=100
        )
        raw = response.choices[0].message.content.strip()
        print(f"DEBUG map_symptoms_to_topics ({category}/{subcategory}) raw: {raw}")
        clean = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
        topics = [t for t in result.get("topics", []) if t in valid_topics]
        return topics if topics else valid_topics
    except Exception as e:
        print(f"map_symptoms_to_topics error: {e}")
        return valid_topics


def select_disease_topics(
    reported_symptoms: list,
    subcategory: str,
    conversation: list = None,
    active_differentials: list = None,
    internal_diagnosis: str = None
) -> list:
    valid_topics = DISEASE_TOPICS_PREGNANCY if subcategory == "pregnancy" else DISEASE_TOPICS_CHILD

    extra_context = ""
    if active_differentials:
        extra_context += f"Active differentials: {json.dumps(active_differentials)}\n"
    if internal_diagnosis:
        extra_context += f"Most likely diagnosis: {internal_diagnosis}\n"
    if conversation:
        extra_context += f"Recent conversation: {json.dumps(conversation[-6:])}\n"

    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You select disease topics to retrieve for a Nigerian maternal/child health case.\n"
                        "You MUST only return topics from the valid list provided. Do not invent any topic.\n"
                        "Return 3 to 5 topics maximum — most clinically relevant first.\n"
                        f"Subcategory: {subcategory}\n"
                        f"Valid disease topics: {json.dumps(valid_topics)}\n"
                        f"{extra_context}"
                        'Return JSON only: {"topics": ["topic1", "topic2", "topic3"]}'
                    )
                },
                {
                    "role": "user",
                    "content": f"Reported symptoms: {json.dumps(reported_symptoms)}"
                }
            ],
            temperature=0,
            max_tokens=100
        )
        raw = response.choices[0].message.content.strip()
        print(f"DEBUG select_disease_topics ({subcategory}) raw: {raw}")
        clean = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
        topics = [t for t in result.get("topics", []) if t in valid_topics]
        return topics if topics else []
    except Exception as e:
        print(f"select_disease_topics error: {e}")
        return []


def select_topics(
    conversation: list,
    stage: str,
    intent: str,
    reported_symptoms: list
) -> list:
    subcategory = resolve_subcategory(intent, fallback="general")

    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a medical knowledge retrieval specialist for a Nigerian maternal and child health app.\n"
                        "Given a conversation and reported symptoms, decide which topics to retrieve.\n\n"
                        f"Intent: {intent}\n"
                        f"Subcategory: {subcategory}\n"
                        f"Reported symptoms: {reported_symptoms}\n\n"
                        "Return topics as single words or short phrases.\n"
                        'Return JSON only: {"topics": ["topic1", "topic2", "topic3"]}'
                    )
                },
                {
                    "role": "user",
                    "content": f"Conversation: {json.dumps(conversation[-6:])}"
                }
            ],
            temperature=0,
            max_tokens=100
        )
        raw = response.choices[0].message.content.strip()
        clean = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
        return result.get("topics", reported_symptoms or ["general"])
    except:
        return reported_symptoms or ["general"]


def fetch_disease_files_by_topic(
    topics: list,
    subcategory: str = None
) -> tuple:
    all_contents = []
    seen_files = set()
    files_retrieved = []

    for topic in topics:
        try:
            query = supabase.table("documents")\
                .select("content, file_name")\
                .eq("category", "disease")\
                .eq("topic", topic)
            if subcategory:
                query = query.eq("subcategory", subcategory)
            result = query.execute()
            print(f"DEBUG fetch_disease topic='{topic}' subcategory='{subcategory}': got {len(result.data or [])} rows")
            for doc in (result.data or []):
                fn = doc.get("file_name", "")
                if fn not in seen_files:
                    seen_files.add(fn)
                    files_retrieved.append(fn)
                    all_contents.append(f"### FILE: {fn}\n\n{doc['content']}")
        except Exception as e:
            print(f"fetch_disease_files_by_topic error for topic '{topic}': {e}")

    return "\n\n========\n\n".join(all_contents), files_retrieved


def fetch_files(
    category: str,
    topics: list,
    subcategory: str = None
) -> tuple:
    all_contents = []
    seen_files = set()
    files_retrieved = []

    for topic in topics:
        try:
            query = supabase.table("documents")\
                .select("content, file_name, topic")\
                .eq("category", category)\
                .eq("topic", topic)

            if subcategory:
                query = query.eq("subcategory", subcategory)

            result = query.execute()
            print(f"DEBUG fetch_files category='{category}' topic='{topic}' subcategory='{subcategory}': got {len(result.data or [])} rows")

            for doc in (result.data or []):
                fname = doc.get("file_name", "")
                if fname not in seen_files:
                    seen_files.add(fname)
                    files_retrieved.append(fname)
                    all_contents.append(
                        f"### FILE: {fname}\n\n{doc['content']}"
                    )

        except Exception as e:
            print(f"Fetch error for topic {topic}: {e}")

    if not all_contents and subcategory:
        print(f"WARNING: No results with subcategory='{subcategory}' for topics {topics} in {category} — retrying without subcategory")
        for topic in topics:
            try:
                result = supabase.table("documents")\
                    .select("content, file_name, topic")\
                    .eq("category", category)\
                    .eq("topic", topic)\
                    .execute()

                for doc in (result.data or []):
                    fname = doc.get("file_name", "")
                    if fname not in seen_files:
                        seen_files.add(fname)
                        files_retrieved.append(fname)
                        all_contents.append(
                            f"### FILE: {fname}\n\n{doc['content']}"
                        )
            except Exception as e:
                print(f"Fallback fetch error for topic {topic}: {e}")

    if not all_contents:
        print(f"WARNING: No files found for topics {topics} in {category}/{subcategory} — fetching entire category")
        try:
            query = supabase.table("documents")\
                .select("content, file_name")\
                .eq("category", category)
            if subcategory:
                query = query.eq("subcategory", subcategory)
            result = query.execute()
            for doc in (result.data or []):
                fname = doc.get("file_name", "")
                if fname not in seen_files:
                    seen_files.add(fname)
                    files_retrieved.append(fname)
                    all_contents.append(
                        f"### FILE: {fname}\n\n{doc['content']}"
                    )
        except Exception as e:
            print(f"Category fallback error: {e}")

    return "\n\n========\n\n".join(all_contents), files_retrieved


def retrieve_for_stage(
    stage: str,
    query: str,
    intent: str,
    topic: str = None,
    symptoms: list = None,
    conversation: list = None,
    extra_context: dict = None
) -> str:
    symptoms = symptoms or []
    conversation = conversation or [{"role": "user", "content": query}]

    subcategory = resolve_subcategory(intent)

    print(f"RAG: stage={stage} | subcategory={subcategory} | symptoms={symptoms}")

    if stage == "triage":
        topics = map_symptoms_to_topics(
            reported_symptoms=symptoms,
            subcategory=subcategory or "child",
            category="symptoms",
            conversation=conversation
        )
        print(f"RAG triage topics mapped: {topics}")
        content, files = fetch_files("symptoms", topics, subcategory)
        _get_log().append({"category": "symptoms", "files": files})
        return content

    elif stage == "disease_reasoning":
        disease_topics = select_disease_topics(
            reported_symptoms=symptoms,
            subcategory=subcategory or "child",
            conversation=conversation
        )
        print(f"RAG disease_reasoning topics: {disease_topics}")
        disease_content, disease_files = fetch_disease_files_by_topic(disease_topics, subcategory)

        symptom_topics = map_symptoms_to_topics(
            reported_symptoms=symptoms,
            subcategory=subcategory or "child",
            category="symptoms",
            conversation=conversation
        )
        symptom_content, symptom_files = fetch_files("symptoms", symptom_topics, subcategory)

        _get_log().append({"category": "disease (selected)", "files": disease_files})
        _get_log().append({"category": "symptoms", "files": symptom_files})
        return disease_content + "\n\n========\n\n" + symptom_content

    elif stage == "management":
        active_differentials = extra_context.get("active_differentials", []) if extra_context else []
        internal_diagnosis = extra_context.get("internal_diagnosis") if extra_context else None

        disease_topics = select_disease_topics(
            reported_symptoms=symptoms,
            subcategory=subcategory or "child",
            conversation=conversation,
            active_differentials=active_differentials,
            internal_diagnosis=internal_diagnosis
        )
        print(f"RAG management disease topics: {disease_topics}")
        disease_content, disease_files = fetch_disease_files_by_topic(disease_topics, subcategory)

        care_topics = map_symptoms_to_topics(
            reported_symptoms=symptoms,
            subcategory=subcategory or "child",
            category="symptom_care",
            conversation=conversation,
            active_differentials=active_differentials
        )
        print(f"RAG management care topics: {care_topics}")
        care_content, care_files = fetch_files("symptom_care", care_topics, subcategory)

        _get_log().append({"category": "disease (selected)", "files": disease_files})
        _get_log().append({"category": "symptom_care", "files": care_files})
        return disease_content + "\n\n========\n\n" + care_content

    elif stage == "medication":
        topics = select_topics(conversation, stage, intent, symptoms)
        content, files = fetch_files("medication", topics, None)
        _get_log().append({"category": "medication", "files": files})
        return content

    elif stage in ["pregnancy_info", "pregnancy_education"]:
        topics = select_topics(conversation, stage, intent, symptoms)
        content, files = fetch_files("pregnancy_education", topics, "pregnancy")
        _get_log().append({"category": "pregnancy_education", "files": files})
        return content

    elif stage in ["child_health_info", "child_health_education"]:
        topics = select_topics(conversation, stage, intent, symptoms)
        content, files = fetch_files("child_health_education", topics, "child")
        _get_log().append({"category": "child_health_education", "files": files})
        return content

    elif stage == "first_aid":
        topics = select_topics(conversation, stage, intent, symptoms)
        content, files = fetch_files("first_aid", topics, None)
        _get_log().append({"category": "first_aid", "files": files})
        return content

    else:
        topics = map_symptoms_to_topics(
            reported_symptoms=symptoms,
            subcategory=subcategory or "child",
            category="symptoms",
            conversation=conversation
        )
        content, files = fetch_files("symptoms", topics, subcategory)
        _get_log().append({"category": "symptoms", "files": files})
        return content
