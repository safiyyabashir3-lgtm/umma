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

def get_embedding(text: str) -> list:
    response = client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    return response.data[0].embedding

def retrieve(
    query: str,
    category: str,
    topic: str = None,
    subcategory: str = None,
    symptoms: list = None,
    top_k: int = 5
) -> str:
    embedding = get_embedding(query)

    params = {
        "query_embedding": embedding,
        "match_category": category,
        "match_count": top_k
    }

    if topic:
        params["match_topic"] = topic
    if subcategory:
        params["match_subcategory"] = subcategory

    try:
        result = supabase.rpc("match_documents", params).execute()
        chunks = result.data or []

        if not chunks:
            return ""

        if symptoms:
            filtered = []
            for chunk in chunks:
                chunk_symptoms = chunk.get("symptom_verification") or []
                if any(s.lower() in [cs.lower() for cs in chunk_symptoms] for s in symptoms):
                    filtered.append(chunk)
            chunks = filtered if filtered else chunks

        return "\n\n---\n\n".join([c["content"] for c in chunks])

    except Exception as e:
        print(f"RAG retrieval error: {e}")
        return ""


def retrieve_for_stage(
    stage: str,
    query: str,
    intent: str,
    topic: str = None,
    symptoms: list = None
) -> str:
    subcategory = None
    if "pregnancy" in intent:
        subcategory = "pregnancy"
    elif "child" in intent:
        subcategory = "child"

    if stage == "triage":
        return retrieve(
            query=query,
            category="symptoms",
            topic=topic,
            subcategory=subcategory,
            symptoms=symptoms,
            top_k=5
        )

    elif stage == "disease_reasoning":
        return retrieve(
            query=query,
            category="disease",
            topic=topic,
            subcategory=subcategory,
            symptoms=symptoms,
            top_k=5
        )

    elif stage == "management":
        disease_context = retrieve(
            query=query,
            category="disease",
            topic=topic,
            subcategory=subcategory,
            symptoms=symptoms,
            top_k=3
        )
        care_context = retrieve(
            query=query,
            category="symptom_care",
            topic=topic,
            subcategory=subcategory,
            symptoms=symptoms,
            top_k=3
        )
        return disease_context + "\n\n---\n\n" + care_context

    elif stage == "medication":
        return retrieve(
            query=query,
            category="medication",
            topic=topic,
            symptoms=symptoms,
            top_k=5
        )

    elif stage == "pregnancy_info":
        return retrieve(
            query=query,
            category="pregnancy_education",
            topic=topic,
            top_k=5
        )

    elif stage == "child_health_info":
        return retrieve(
            query=query,
            category="child_health_education",
            topic=topic,
            top_k=5
        )

    else:
        return retrieve(
            query=query,
            category="symptoms",
            topic=topic,
            subcategory=subcategory,
            top_k=5
        )
