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


def select_disease_files(
    conversation: list,
    stage: str,
    intent: str,
    reported_symptoms: list,
    subcategory: str,
    active_differentials: list = None,
    internal_diagnosis: str = None
) -> list:
    """
    GPT-4.1 selects which specific disease files to retrieve.
    Returns a list of file names matching what is stored in the database.
    Limits to 4-6 most relevant files — prevents context overload.
    """
    differentials_context = ""
    if active_differentials:
        differentials_context = f"Active differentials being considered: {active_differentials}"
    if internal_diagnosis:
        differentials_context += f"
Most likely diagnosis: {internal_diagnosis}"

    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": f"""You are a medical knowledge retrieval specialist for a Nigerian maternal and child health app.
Given a clinical conversation, select which disease knowledge files to retrieve.

Stage: {stage}
Subcategory: {subcategory}
Reported symptoms: {reported_symptoms}
{differentials_context}

Available file naming convention examples:
- malaria_child.md, severe_malaria_child.md, pneumonia_child.md
- malaria_pregnancy.md, preeclampsia.md, anaemia_pregnancy.md
- Files follow pattern: condition_subcategory.md or condition.md

Rules:
- Return 4 to 6 file names maximum — most clinically relevant only
- Always include the file for the most likely diagnosis first
- Include files for other active differentials
- Only include files relevant to Nigerian maternal and child health
- Use exact file naming convention — condition name in lowercase with underscores
- Subcategory suffix: _child for child conditions, _pregnancy for pregnancy conditions
- Some files have no suffix if they apply generally e.g. preeclampsia.md

Return JSON only:
{{"files": ["filename1.md", "filename2.md", "filename3.md"]}}"""
            },
            {
                "role": "user",
                "content": f"Conversation: {json.dumps(conversation[-8:])}"
            }
        ],
        temperature=0,
        max_tokens=150
    )

    raw = response.choices[0].message.content.strip()
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
        return result.get("files", [])
    except:
        return []


def fetch_disease_files_by_name(
    file_names: list,
    subcategory: str = None
) -> tuple:
    """
    Fetches specific disease files by name.
    Falls back to topic-based fetch if named files not found.
    Returns (content_string, list_of_filenames_retrieved)
    """
    all_contents = []
    seen_files = set()
    files_retrieved = []

    for fname in file_names:
        try:
            query = supabase.table("documents")                .select("content, file_name")                .eq("category", "disease")                .eq("file_name", fname)
            result = query.execute()

            for doc in (result.data or []):
                fn = doc.get("file_name", "")
                if fn not in seen_files:
                    seen_files.add(fn)
                    files_retrieved.append(fn)
                    all_contents.append(
                        f"### FILE: {fn}

{doc['content']}"
                    )
        except Exception as e:
            print(f"Fetch error for file {fname}: {e}")

    # Fallback — if nothing found by name, fetch all for subcategory
    if not all_contents:
        print("Named file fetch failed — falling back to subcategory fetch")
        try:
            q = supabase.table("documents").select("content, file_name").eq("category", "disease")
            if subcategory:
                q = q.eq("subcategory", subcategory)
            result = q.execute()
            for doc in (result.data or []):
                fn = doc.get("file_name", "")
                if fn not in seen_files:
                    seen_files.add(fn)
                    files_retrieved.append(fn)
                    all_contents.append(
                        f"### FILE: {fn}

{doc['content']}"
                    )
        except Exception as e:
            print(f"Fallback fetch error: {e}")

    return "

========

".join(all_contents), files_retrieved


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
    conversation: list = None,
    extra_context: dict = None
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
        # GPT-4.1 selects the 4-6 most relevant disease files based on conversation
        disease_file_names = select_disease_files(
            conversation=conversation,
            stage=stage,
            intent=intent,
            reported_symptoms=symptoms,
            subcategory=subcategory
        )
        disease_content, disease_files = fetch_disease_files_by_name(disease_file_names, subcategory)
        symptom_content, symptom_files = fetch_files("symptoms", topics, subcategory)
        _get_log().append({"category": "disease (selected)", "files": disease_files})
        _get_log().append({"category": "symptoms", "files": symptom_files})
        return disease_content + "\n\n========\n\n" + symptom_content

    elif stage == "management":
        # Use active_differentials and internal_diagnosis to select most relevant disease files
        active_differentials = extra_context.get("active_differentials", []) if extra_context else []
        internal_diagnosis = extra_context.get("internal_diagnosis") if extra_context else None
        disease_file_names = select_disease_files(
            conversation=conversation,
            stage=stage,
            intent=intent,
            reported_symptoms=symptoms,
            subcategory=subcategory,
            active_differentials=active_differentials,
            internal_diagnosis=internal_diagnosis
        )
        disease_content, disease_files = fetch_disease_files_by_name(disease_file_names, subcategory)
        care_content, care_files = fetch_files("symptom_care", topics, subcategory)
        _get_log().append({"category": "disease (selected)", "files": disease_files})
        _get_log().append({"category": "symptom_care", "files": care_files})
        return disease_content + "\n\n========\n\n" + care_content

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

    elif stage == "first_aid":
        content, files = fetch_files("first_aid", topics, None)
        _get_log().append({"category": "first_aid", "files": files})
        return content

    else:
        content, files = fetch_files("symptoms", topics, subcategory)
        _get_log().append({"category": "symptoms", "files": files})
        return content
