import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from openai import AzureOpenAI
import json

load_dotenv("/workspaces/umma/umma-ai/.env")

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION")
)

DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

CATEGORY_CONFIG = {
    "symptoms": {"safety_level": "high"},
    "disease": {"safety_level": "high"},
    "symptom_care": {"safety_level": "medium"},
    "medication": {"safety_level": "high"},
    "pregnancy_education": {"safety_level": "medium"},
    "child_health_education": {"safety_level": "medium"},
    "first_aid": {"safety_level": "high"}
}

def read_file(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

def infer_metadata_with_ai(filename: str, content: str, category: str) -> dict:
    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": """You are a medical document metadata specialist for a Nigerian maternal and child health AI.
Given a filename, category, and content, extract metadata.
Respond with valid JSON only. No explanation. No markdown."""
            },
            {
                "role": "user",
                "content": f"""
Filename: {filename}
Category: {category}
Content preview: {content[:800]}

Return this exact JSON:
{{
  "topic": "main medical topic in one word e.g. malaria, headache, fever, anaemia",
  "subcategory": "one of: pregnancy, child, general",
  "nigerian_context": true or false,
  "symptom_verification": ["list", "of", "symptoms", "this", "file", "covers"]
}}
"""
            }
        ],
        temperature=0,
        max_tokens=200
    )

    raw = response.choices[0].message.content.strip()
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except:
        print(f"Metadata inference failed for {filename} — using fallback")
        return {
            "topic": Path(filename).stem.split("_")[0],
            "subcategory": "general",
            "nigerian_context": True,
            "symptom_verification": []
        }

def ingest_folder(folder_path: str, category_key: str):
    config = CATEGORY_CONFIG.get(category_key, {"safety_level": "medium"})
    files = list(Path(folder_path).glob("*.md")) + \
            list(Path(folder_path).glob("*.txt")) + \
            list(Path(folder_path).glob("*.pdf"))

    if not files:
        print(f"No files in {folder_path} — skipping")
        return

    for file_path in files:
        print(f"\nProcessing: {file_path.name}")

        try:
            content = read_file(str(file_path))
        except Exception as e:
            print(f"Could not read {file_path.name}: {e}")
            continue

        if not content.strip():
            print(f"Empty file: {file_path.name} — skipping")
            continue

        print(f"Inferring metadata...")
        metadata = infer_metadata_with_ai(file_path.name, content, category_key)
        print(f"Topic: {metadata['topic']} | Subcategory: {metadata['subcategory']}")

        try:
            supabase.table("documents").insert({
                "content": content,
                "category": category_key,
                "topic": metadata.get("topic", "general"),
                "subcategory": metadata.get("subcategory", "general"),
                "nigerian_context": metadata.get("nigerian_context", True),
                "symptom_verification": metadata.get("symptom_verification", []),
                "source": file_path.name,
                "file_name": file_path.name,
                "safety_level": config.get("safety_level", "medium")
            }).execute()
            print(f"Stored as single document: {file_path.name}")

        except Exception as e:
            print(f"Error storing {file_path.name}: {e}")

def main():
    base = "/workspaces/umma/umma-ai/knowledge_base"
    folders = {
        "symptoms": f"{base}/symptoms",
        "disease": f"{base}/disease",
        "symptom_care": f"{base}/symptom_care",
        "medication": f"{base}/medication",
        "pregnancy_education": f"{base}/pregnancy_education",
        "child_health_education": f"{base}/child_health_education",
        "first_aid": f"{base}/first_aid"
    }

    for category_key, folder_path in folders.items():
        print(f"\n{'='*40}")
        print(f"Ingesting category: {category_key}")
        print(f"{'='*40}")
        ingest_folder(folder_path, category_key)

    print("\nIngestion complete.")

if __name__ == "__main__":
    main()
