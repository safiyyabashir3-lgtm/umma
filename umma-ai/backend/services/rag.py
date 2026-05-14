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

# FIX: use thread-local storage instead of a module-level mutable list.
# In an async FastAPI environment with concurrent requests, a shared global list
# causes one request's retrieval log to bleed into another's debug output.
# threading.local() gives each thread its own isolated log.
_local = threading.local()

def _get_log():
    if not hasattr(_local, "retrieval_log"):
        _local.retrieval_log = []
    return _local.retrieval_log

def get_retrieval_log():
    return _get_log().copy()

def clear_retrieval_log():
    _get_log().clear()


def select_topics(
    conversation: list,
    stage: str,
    intent: str,
    reported_symptoms: list
) -> list:
    subcategory = "pregnancy" if "pregnancy" in intent else "child" if "child" in intent else "general"

    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": f"""You are a medical knowledge retrieval specialist for a Nigerian maternal and child health app.
Given a conversation, clinical stage, and reported symptoms, decide which medical topics to retrieve.

Current stage: {stage}
Intent: {intent}
Subcategory: {subcategory}
Reported symptoms: {reported_symptoms}

Rules:
- For triage: return topics matching all reported symptoms
- For disease_reasoning: return topics for all reported symptoms AND all plausible differential diagnoses given the Nigerian context and conversation — be comprehensive, do not miss conditions
- For management: return topics for the most likely conditions and all reported symptoms
- Only suggest conditions relevant to Nigerian maternal and child health context
- Do not suggest conditions extremely rare in Nigeria such as dengue, chikungunya, COVID-19, influenza
- Focus on: malaria, typhoid, UTI, anaemia, preeclampsia, pneumonia, sepsis, malnutrition and other common Nigerian conditions
- Return as many genuinely relevant topics as needed
- Topics should be single words or short phrases matching medical condition names

Return JSON only:
{{"topics": ["topic1", "topic2", "topic3"]}}"""
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
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
        return result.get("topics", reported_symptoms or ["general"])
    except:
        return reported_symptoms or ["general"]


def fetch_files(
    category: str,
    topics: list,
    subcategory: str = None
) -> tuple:
    """
    Returns (content_string, list_of_filenames_retrieved)
    """
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

    # Fallback without subcategory
    if not all_contents and subcategory:
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

    # Fallback — fetch all in category
    if not all_contents:
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
    conversation: list = None
) -> str:
    symptoms = symptoms or []
    conversation = conversation or [{"role": "user", "content": query}]

    subcategory = None
    if "pregnancy" in intent:
        subcategory = "pregnancy"
    elif "child" in intent:
        subcategory = "child"

    topics = select_topics(
        conversation=conversation,
        stage=stage,
        intent=intent,
        reported_symptoms=symptoms
    )

    print(f"RAG: stage={stage} | topics={topics} | subcategory={subcategory}")

    if stage == "triage":
        content, files = fetch_files("symptoms", topics, subcategory)
        _get_log().append({"category": "symptoms", "files": files})
        return content

    elif stage == "disease_reasoning":
        # Retrieve ALL disease files for subcategory at once
        try:
            q = supabase.table("documents").select("content, file_name").eq("category", "disease")
            if subcategory:
                q = q.eq("subcategory", subcategory)
            all_disease = q.execute()
            all_disease_names = [d["file_name"] for d in (all_disease.data or [])]
            all_disease_content = "\n\n========\n\n".join([
                f"### FILE: {d['file_name']}\n\n{d['content']}"
                for d in (all_disease.data or [])
            ])
        except Exception as e:
            print(f"All disease fetch error: {e}")
            all_disease_content, all_disease_names = "", []
        symptom_content, symptom_files = fetch_files("symptoms", topics, subcategory)
        _get_log().append({"category": "disease (all)", "files": all_disease_names})
        _get_log().append({"category": "symptoms", "files": symptom_files[1] if isinstance(symptom_files, tuple) else symptom_files})
        return all_disease_content + "\n\n========\n\n" + symptom_content

    elif stage == "management":
        # Retrieve ALL disease files for subcategory — same as disease_reasoning
        # Management needs full disease context including severity and management sections
        try:
            q = supabase.table("documents").select("content, file_name").eq("category", "disease")
            if subcategory:
                q = q.eq("subcategory", subcategory)
            all_disease = q.execute()
            all_disease_names = [d["file_name"] for d in (all_disease.data or [])]
            all_disease_content = "\n\n========\n\n".join([
                f"### FILE: {d['file_name']}\n\n{d['content']}"
                for d in (all_disease.data or [])
            ])
        except Exception as e:
            print(f"Management disease fetch error: {e}")
            all_disease_content, all_disease_names = "", []
        care_content, care_files = fetch_files("symptom_care", topics, subcategory)
        _get_log().append({"category": "disease (all)", "files": all_disease_names})
        _get_log().append({"category": "symptom_care", "files": care_files})
        return all_disease_content + "\n\n========\n\n" + care_content

    elif stage == "medication":
        content, files = fetch_files("medication", topics, None)
        _get_log().append({"category": "medication", "files": files})
        return content

    elif stage in ["pregnancy_info", "pregnancy_education"]:
        content, files = fetch_files("pregnancy_education", topics, "pregnancy")
        _get_log().append({"category": "pregnancy_education", "files": files})
        return content

    elif stage in ["child_health_info", "child_health_education"]:
        content, files = fetch_files("child_health_education", topics, "child")
        _get_log().append({"category": "child_health_education", "files": files})
        return content

    else:
        content, files = fetch_files("symptoms", topics, subcategory)
        _get_log().append({"category": "symptoms", "files": files})
        return content
