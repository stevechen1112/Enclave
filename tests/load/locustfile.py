"""Profile-driven P5 live load scenarios.

Run through ``scripts/run_p5_capacity.py`` so profile targets, output identity,
fixtures and evidence metadata are applied consistently.
"""

from __future__ import annotations

import os
import random
import sys
import uuid
from itertools import cycle
from pathlib import Path

from locust import HttpUser, between, events, tag, task
from locust.exception import StopUser

LOAD_DIR = Path(__file__).resolve().parent
if str(LOAD_DIR) not in sys.path:
    sys.path.insert(0, str(LOAD_DIR))

from capacity_config import (
    credential_pool,
    fixture_paths,
    selected_profile,
    spec_sha256,
    target_load,
    validate_full_scenario_environment,
)

PROFILE_NAME, PROFILE = selected_profile()
TARGET = target_load()
FIXTURES = fixture_paths()
GROUNDED_MARKER = os.getenv("P5_GROUNDED_MARKER", "P5-SOP-RESET-042")
FULL_SCENARIO = os.getenv("P5_FULL_SCENARIO", "false").lower() in {
    "1",
    "true",
    "yes",
}
CREDENTIALS = credential_pool()
_CREDENTIAL_CYCLE = cycle(CREDENTIALS) if CREDENTIALS else None

ENVIRONMENT_ERRORS = validate_full_scenario_environment()
if ENVIRONMENT_ERRORS:
    raise RuntimeError("; ".join(ENVIRONMENT_ERRORS))

USER_EMAIL = os.getenv("LOAD_TEST_USER_EMAIL", "user@example.com")
USER_PASSWORD = os.environ["LOAD_TEST_USER_PASSWORD"]
ADMIN_EMAIL = os.getenv("LOAD_TEST_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ["LOAD_TEST_ADMIN_PASSWORD"]
SUPERUSER_EMAIL = os.getenv("LOAD_TEST_SUPERUSER_EMAIL", ADMIN_EMAIL)
SUPERUSER_PASSWORD = os.environ["LOAD_TEST_SUPERUSER_PASSWORD"]


class AuthenticatedUser(HttpUser):
    abstract = True
    email = USER_EMAIL
    password = USER_PASSWORD

    def on_start(self) -> None:
        access_token = ""
        if _CREDENTIAL_CYCLE is not None:
            credential = next(_CREDENTIAL_CYCLE)
            self.email = credential["email"]
            self.password = credential["password"]
            access_token = credential.get("access_token", "")
        if access_token:
            self.token = access_token
            self.headers = {"Authorization": f"Bearer {self.token}"}
            return
        with self.client.post(
            "/api/v1/auth/login/access-token",
            data={"username": self.email, "password": self.password},
            name="auth_login",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"login failed: {response.status_code}")
                self.token = ""
                self.headers = {}
                raise StopUser()
            payload = response.json()
            self.token = payload.get("access_token", "")
            if not self.token:
                response.failure("login did not return a full access token")
                raise StopUser()
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def _live_login_probe(self) -> None:
        with self.client.post(
            "/api/v1/auth/login/access-token",
            data={"username": self.email, "password": self.password},
            name="auth_login",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"login probe failed: {response.status_code}")
                return
            if not response.json().get("access_token"):
                response.failure("login probe did not return a full access token")


class KnowledgeUser(AuthenticatedUser):
    """Read and query traffic: 82% of virtual users."""

    wait_time = between(0.5, 1.5)
    weight = 9

    @tag("asset_list")
    @task(3)
    def asset_list(self) -> None:
        self.client.get(
            "/api/v1/knowledge/assets", headers=self.headers, name="asset_list"
        )

    @tag("knowledge_search")
    @task(4)
    def knowledge_search(self) -> None:
        query = random.choice(
            (
                GROUNDED_MARKER,
                f"{GROUNDED_MARKER} 設備復歸",
                f"{GROUNDED_MARKER} 換線前確認",
                f"{GROUNDED_MARKER} 盤點差異",
            )
        )
        with self.client.post(
            "/api/v1/kb/search",
            json={"query": query, "top_k": 5, "granularity": "auto"},
            headers=self.headers,
            name="knowledge_search",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                return
            payload = response.json()
            results = payload.get("results") if isinstance(payload, dict) else None
            if not isinstance(results, list) or not results:
                response.failure("knowledge search returned no evidence")

    @tag("grounded_chat")
    @task(3)
    def grounded_chat(self) -> None:
        question = random.choice(
            (
                f"依據 {GROUNDED_MARKER}，設備復歸前要先確認什麼？",
                f"依據 {GROUNDED_MARKER}，盤點差異應如何處理？",
                f"依據 {GROUNDED_MARKER}，換線前要確認什麼？",
            )
        )
        with self.client.post(
            "/api/v1/chat/chat",
            json={"question": question, "top_k": 3},
            headers=self.headers,
            name="grounded_chat",
            timeout=30,
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                return
            payload = response.json()
            answer = payload.get("answer") if isinstance(payload, dict) else None
            sources = payload.get("sources") if isinstance(payload, dict) else None
            if not str(answer or "").strip() or not isinstance(sources, list) or not sources:
                response.failure("chat response was not grounded in evidence")


class IngestionUser(AuthenticatedUser):
    """Bounded write traffic for document, batch, audio and video queues."""

    email = ADMIN_EMAIL
    password = ADMIN_PASSWORD
    wait_time = between(120, 240)
    weight = 1

    def _upload(self, kind: str, request_name: str) -> None:
        path = FIXTURES[kind]
        if not FULL_SCENARIO:
            return
        with path.open("rb") as stream:
            self.client.post(
                "/api/v1/knowledge/assets",
                files={"file": (path.name, stream, _media_type(path))},
                data={
                    "title": f"p5-{kind}-{uuid.uuid4().hex[:10]}",
                    "idempotency_key": f"p5:{PROFILE_NAME}:{uuid.uuid4()}",
                },
                headers=self.headers,
                name=request_name,
                timeout=60,
            )

    @tag("document_upload")
    @task(3)
    def document_upload(self) -> None:
        self._upload("document", "document_upload")

    @tag("batch_ingestion")
    @task(1)
    def batch_ingestion(self) -> None:
        for _ in range(3):
            self._upload("document", "batch_ingestion")

    @tag("audio_queue")
    @task(1)
    def audio_queue(self) -> None:
        self._upload("audio", "audio_queue")

    @tag("video_queue")
    @task(1)
    def video_queue(self) -> None:
        self._upload("video", "video_queue")


class OperationsUser(AuthenticatedUser):
    """Low-rate operator visibility traffic."""

    email = SUPERUSER_EMAIL
    password = SUPERUSER_PASSWORD
    wait_time = between(10, 30)
    weight = 1

    @tag("operations")
    @task
    def health(self) -> None:
        self.client.get("/health", name="health_check")


class AuthProbeUser(AuthenticatedUser):
    """One rate-safe live auth client, independent of the pre-issued load tokens."""

    fixed_count = 1
    wait_time = between(4, 6)

    @tag("auth_login")
    @task
    def login(self) -> None:
        self._live_login_probe()


def _media_type(path: Path) -> str:
    return {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".pdf": "application/pdf",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
    }.get(path.suffix.lower(), "application/octet-stream")


@events.test_start.add_listener
def announce_capacity_contract(environment, **_kwargs) -> None:
    environment.runner.stats.log_request(
        "P5",
        f"profile={PROFILE_NAME};spec={spec_sha256()[:12]};users={TARGET['concurrent_users']}",
        0,
        0,
    )
