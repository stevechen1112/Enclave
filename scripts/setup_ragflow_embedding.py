"""Setup RAGFlow Ollama embedding model (v0.26+ provider API)."""
import json
import os
import pymysql
import httpx
from pathlib import Path

TENANT_ID = "8969c9e08d0011f18a66c5254d90938b"
OLLAMA_BASE = "http://host.docker.internal:11434"
INSTANCE_NAME = "ollama-local"
EMBED_MODEL = "bge-m3"


def _load_env() -> dict:
    env = {}
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def _fix_mysql_extra() -> None:
    conn = pymysql.connect(
        host="localhost", port=3307,
        user="root", password="infini_rag_flow",
        database="rag_flow", charset="utf8mb4",
    )
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO llm_factories (name, logo, tags, `rank`, status)
            VALUES ('Ollama', 'ollama', 'LLM,Embedding,Image2Text,Rerank,ASR', 1, '1')
        """)
        print("Added Ollama factory")
    except pymysql.err.IntegrityError:
        print("Ollama factory already exists")

    cur.execute("""
        INSERT INTO tenant_llm (tenant_id, llm_factory, model_type, llm_name, api_key, api_base, max_tokens, used_tokens, status)
        VALUES (%s, 'Ollama', 'embedding', %s, '', %s, 8192, 0, '1')
        ON DUPLICATE KEY UPDATE api_base=%s, status='1'
    """, (TENANT_ID, EMBED_MODEL, OLLAMA_BASE, OLLAMA_BASE))
    print("Added/updated tenant_llm embedding")

    extra = json.dumps({"base_url": OLLAMA_BASE, "region": "default"})
    cur.execute(
        "UPDATE tenant_model_instance SET extra=%s WHERE instance_name=%s",
        (extra, INSTANCE_NAME),
    )
    conn.commit()
    cur.close()
    conn.close()


def _configure_via_api(env: dict) -> None:
    base = env.get("RAGFLOW_BASE_URL", "http://localhost:9380")
    key = env.get("RAGFLOW_API_KEY", "")
    ds = env.get("RAGFLOW_DATASET_ID", "")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    with httpx.Client(timeout=60) as client:
        r = client.post(
            f"{base}/api/v1/providers/Ollama/instances",
            headers=headers,
            json={
                "instance_name": INSTANCE_NAME,
                "api_key": "",
                "region": "default",
                "base_url": OLLAMA_BASE,
            },
        )
        print("create instance:", r.status_code, r.text[:200])

        r2 = client.post(
            f"{base}/api/v1/providers/Ollama/instances/{INSTANCE_NAME}/models",
            headers=headers,
            json={"model_name": EMBED_MODEL, "model_type": "embedding"},
        )
        print("add embedding model:", r2.status_code, r2.text[:200])

        if ds:
            model = f"{EMBED_MODEL}@{INSTANCE_NAME}@Ollama"
            r3 = client.put(
                f"{base}/api/v1/datasets/{ds}",
                headers=headers,
                json={"embedding_model": model},
            )
            print("dataset embedding:", r3.status_code, r3.text[:200])


if __name__ == "__main__":
    env = _load_env()
    _fix_mysql_extra()
    _configure_via_api(env)
    print("Done!")
