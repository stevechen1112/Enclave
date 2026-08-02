"""Insert OpenAI provider + default instance + model rows into RAGFlow MySQL.

This RAGFlow build resolves task-executor models via tenant_model_provider /
tenant_model_instance / tenant_model (not the legacy tenant_llm table), so
add_llm alone leaves RAPTOR/GraphRAG failing with "Provider OpenAI not found".
Idempotent: checks before each insert.
"""
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TENANT = os.getenv("RAGFLOW_TENANT_ID", "8969c9e08d0011f18a66c5254d90938b")
MODEL = os.getenv("RAGFLOW_OPENAI_CHAT_MODEL", "gpt-5.6-luna")


def _load_env():
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def sql(stmt: str) -> str:
    out = subprocess.check_output(
        ["docker", "exec", "-i", "docker-mysql-1",
         "mysql", "-uroot", "-pinfini_rag_flow", "rag_flow", "-e", stmt],
        text=True, stderr=subprocess.DEVNULL,
    )
    return out


def main() -> int:
    _load_env()
    key = os.environ["OPENAI_API_KEY"]

    existing = sql(f"SELECT id FROM tenant_model_provider WHERE provider_name='OpenAI' AND tenant_id='{TENANT}';")
    if "OpenAI" not in existing and len(existing.strip().splitlines()) < 2:
        pid = uuid.uuid4().hex
        sql(f"INSERT INTO tenant_model_provider (id, provider_name, tenant_id) VALUES ('{pid}', 'OpenAI', '{TENANT}');")
        print("provider inserted:", pid)
    else:
        pid = existing.strip().splitlines()[1].strip()
        print("provider exists:", pid)

    inst = sql(f"SELECT id FROM tenant_model_instance WHERE provider_id='{pid}' AND instance_name='default';")
    if len(inst.strip().splitlines()) < 2:
        iid = uuid.uuid4().hex
        extra = '{"base_url": "https://api.openai.com/v1", "region": "default"}'
        sql(f"INSERT INTO tenant_model_instance (id, instance_name, provider_id, api_key, status, extra) "
            f"VALUES ('{iid}', 'default', '{pid}', '{key}', '1', '{extra}');")
        print("instance inserted:", iid)
    else:
        iid = inst.strip().splitlines()[1].strip()
        print("instance exists:", iid)

    mdl = sql(f"SELECT id FROM tenant_model WHERE provider_id='{pid}' AND model_name='{MODEL}';")
    if len(mdl.strip().splitlines()) < 2:
        mid = uuid.uuid4().hex
        sql(f"INSERT INTO tenant_model (id, model_name, provider_id, instance_id, model_type, status, extra) "
            f"VALUES ('{mid}', '{MODEL}', '{pid}', '{iid}', 'chat', '1', '{{}}');")
        print("model inserted:", mid)
    else:
        print("model exists")

    print(sql("SELECT p.provider_name, i.instance_name, m.model_name, m.model_type "
              "FROM tenant_model m JOIN tenant_model_instance i ON m.instance_id=i.id "
              "JOIN tenant_model_provider p ON m.provider_id=p.id;"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
