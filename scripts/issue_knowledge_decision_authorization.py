#!/usr/bin/env python3
"""Issue one append-only, signed tenant Owner authorization record."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.knowledge_release_control import (  # noqa: E402
    AuthorizationStore,
    KnowledgeReleaseIdentity,
    TenantDecisionAuthorization,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--record", required=True, help="Unsigned owner-approved JSON record"
    )
    parser.add_argument(
        "--release-identity", required=True, help="Frozen release identity JSON"
    )
    parser.add_argument("--store", required=True)
    args = parser.parse_args()
    key = os.environ.get("KNOWLEDGE_DECISION_AUTHORIZATION_KEY", "")
    if not key:
        raise SystemExit("KNOWLEDGE_DECISION_AUTHORIZATION_KEY is required")
    identity = KnowledgeReleaseIdentity(
        **json.loads(Path(args.release_identity).read_text(encoding="utf-8"))
    )
    payload = json.loads(Path(args.record).read_text(encoding="utf-8"))
    payload["release_identity"] = identity.__dict__
    payload["release_identity_hash"] = identity.identity_hash
    payload.setdefault("issued_at", datetime.now(timezone.utc).isoformat())
    record = TenantDecisionAuthorization(**payload)
    errors = record.validation_errors(
        tenant_id=record.tenant_id,
        requested_mode=record.mode,
        release_identity=identity,
    )
    if errors:
        raise SystemExit("authorization invalid: " + ", ".join(errors))
    path = AuthorizationStore(args.store, key=key).append(record)
    print(
        json.dumps(
            {
                "authorization_id": record.authorization_id,
                "path": str(path),
                "release_identity_hash": identity.identity_hash,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
