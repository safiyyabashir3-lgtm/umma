import os
import json
from pathlib import Path
from dotenv import load_dotenv
from openai import AzureOpenAI
from supabase import create_client
from langchain.text_splitter import RecursiveCharacterTextSplitter
from pypdf import PdfReader

load_dotenv("/workspaces/umma/umma-ai/.env")

# Clients
openai_client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION")
)

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# Text splitter
splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=50,
    separators=["\n\n", "\n", ".", " "]
)

CATEGORY_CONFIG = {
    "triage": {"safety_level": "high"},
    "clinical_reasoning_guide": {"safety_level": "high"},
    "disease": {"safety_level": "high"},
    "symptom_care": {"safety_level": "medium"},
    "medication": {"safety_level": "high"},
    "pregnancy_education": {"safety_level": "medium"},
    "child_health_education": {"safety_level": "medium"}
}

def extract_text_from_pdf(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text

def extract_text_from_file(file_path: str) -> str:
    if file_path.endswith(".pdf"):
        return extract_text_from_pdf(file_path)
    elif file_path.endswith(".txt") or file_path.endswith(".md"):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    else:
        print(f"Skipping unsupported file: {file_path}")
        return ""

def get_embedding(text: str) -> list:
    response = openai_client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    return response.data[0].embedding

def infer_metadata_with_ai(filename: str, content_preview: str, category: str) -> dict:
    """
    Uses GPT-4.1 to intelligently infer metadata from filename and content.
    No hardcoded logic — works for any document added in future.
    """
    response = openai_client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": """You are a medical document metadata specialist for a Nigerian maternal and child health AI system.
Given a document filename, category, and content preview, extract metadata.
Always respond with valid JSON only. No explanation. No markdown."""
            },
            {
                "role": "user",
                "content": f"""
Filename: {filename}
Category: {category}
Content preview: {content_preview[:500]}

Return this exact JSON structure:
{{
  "topic": "the main medical topic (e.g. malaria, anaemia, headache, danger_signs)",
  "subcategory": "one of: pregnancy, child, general",
  "nigerian_context": true or false,
  "symptom_verification": ["list", "of", "symptoms", "this", "document", "covers"],
  "summary": "one sentence describing what this document covers"
}}
"""
            }
        ],
        temperature=0,
        max_tokens=300
    )

    raw = response.choices[0].message.content.strip()

    try:
        # Strip markdown fences if present
        clean = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception as e:
        print(f"Metadata inference failed for {filename}: {e}")
        # Safe fallback — never crashes ingestion
        return {
            "topic": "general",
            "subcategory": "general",
            "nigerian_context": True,
            "symptom_verification": [],
            "summary": filename
        }

def ingest_folder(folder_path: str, category_key: str):
    config = CATEGORY_CONFIG.get(category_key, {"safety_level": "medium"})
    files = list(Path(folder_path).glob("*"))

    if not files:
        print(f"No files found in {folder_path} — skipping")
        return

    for file_path in files:
        print(f"\nProcessing: {file_path.name}")
        text = extract_text_from_file(str(file_path))

        if not text.strip():
            print(f"Empty or unreadable: {file_path.name} — skipping")
            continue

        # Infer metadata once per document using AI
        print(f"Inferring metadata for: {file_path.name}")
        metadata = infer_metadata_with_ai(
            filename=file_path.name,
            content_preview=text,
            category=category_key
        )
        print(f"Metadata: {json.dumps(metadata, indent=2)}")

        chunks = splitter.split_text(text)
        print(f"Split into {len(chunks)} chunks")

        for i, chunk in enumerate(chunks):
            if not chunk.strip():
                continue

            try:
                embedding = get_embedding(chunk)

                supabase.table("documents").insert({
                    "content": chunk,
                    "embedding": embedding,
                    "category": category_key,
                    "topic": metadata.get("topic", "general"),
                    "subcategory": metadata.get("subcategory", "general"),
                    "nigerian_context": metadata.get("nigerian_context", True),
                    "symptom_verification": metadata.get("symptom_verification", []),
                    "source": file_path.name,
                    "safety_level": config.get("safety_level", "medium")
                }).execute()

                print(f"  Chunk {i+1}/{len(chunks)} ingested")

            except Exception as e:
                print(f"  Error on chunk {i+1}: {e}")
                continue

def main():
    base = "/workspaces/umma/umma-ai/knowledge_base"

    folders = {
        "triage": f"{base}/triage",
        "clinical_reasoning_guide": f"{base}/clinical_reasoning_guide",
        "disease": f"{base}/disease",
        "symptom_care": f"{base}/symptom_care",
        "medication": f"{base}/medication",
        "pregnancy_education": f"{base}/pregnancy_education",
        "child_health_education": f"{base}/child_health_education"
    }

    for category_key, folder_path in folders.items():
        print(f"\n{'='*40}")
        print(f"Ingesting category: {category_key}")
        print(f"{'='*40}")
        ingest_folder(folder_path, category_key)

    print("\nIngestion complete.")

if __name__ == "__main__":
    main()
