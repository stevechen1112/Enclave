"""Authenticated OpenAI Realtime voice sessions for task workspaces.

The browser sends only SDP to this endpoint.  The permanent OpenAI key and the
session/tool policy stay on the Enclave backend.  Realtime function calls are
executed through the tenant-scoped tool endpoint below; the model never gets
database credentials and cannot submit or export a quote.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
from datetime import date
from typing import Any, Dict
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.config import settings
from app.models.workflow import TaskRun
from app.models.user import User
from app.services.fixed_form import FieldType, FixedFormCalculator, get_form_registry
from app.services.task_engine import get_task_engine

router = APIRouter(prefix="/voice/realtime", tags=["voice-realtime"])


class QuoteToolCall(BaseModel):
    run_id: UUID
    call_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=80)
    arguments: Dict[str, Any] = Field(default_factory=dict)


def _own_quote_run(db: Session, user: User, run_id: UUID) -> TaskRun:
    accessible = get_task_engine(db).list_accessible_definitions(user)
    if not any(definition.task_key == "quote" for definition in accessible):
        raise HTTPException(status_code=403, detail="quote task access denied")
    run = (
        db.query(TaskRun)
        .filter(
            TaskRun.id == run_id,
            TaskRun.tenant_id == user.tenant_id,
            TaskRun.user_id == user.id,
            TaskRun.task_key == "quote",
        )
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="quote task run not found")
    return run


def _quote_schema():
    schema = get_form_registry().get("quote")
    if schema is None:
        raise HTTPException(status_code=503, detail="quote form schema unavailable")
    return schema


def _calculated_values(values: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(values)
    for field in _quote_schema().fields:
        if not field.calculated:
            continue
        value = FixedFormCalculator.calculate(field, result)
        if value is not None:
            result[field.name] = value
    return result


def _quote_state(run: TaskRun) -> Dict[str, Any]:
    values = dict((run.input_snapshot or {}).get("values") or {})
    values = _calculated_values(values)
    required = [
        field.name
        for field in _quote_schema().fields
        if field.required and not field.calculated
    ]
    missing = [name for name in required if values.get(name) in (None, "")]
    return {
        "run_id": str(run.id),
        "status": run.status,
        "values": values,
        "missing_fields": missing,
        "ready_for_user_review": not missing,
        "next_action": (
            "請使用者逐欄核對畫面，確認無誤後由使用者親自按送審。"
            if not missing
            else "一次詢問一個缺少的欄位。"
        ),
    }


def _tool_parameters() -> Dict[str, Any]:
    properties: Dict[str, Any] = {}
    for field in _quote_schema().fields:
        if field.calculated:
            continue
        spec: Dict[str, Any] = {"description": field.label or field.name}
        if field.type in {FieldType.NUMBER, FieldType.AMOUNT}:
            spec["type"] = "number"
            if field.min_value is not None:
                spec["minimum"] = field.min_value
            if field.max_value is not None:
                spec["maximum"] = field.max_value
        else:
            spec["type"] = "string"
            if field.type == FieldType.DATE:
                spec["format"] = "date"
            if field.options:
                spec["enum"] = list(field.options)
        properties[field.name] = spec
    return {"type": "object", "properties": properties, "additionalProperties": False}


def _instructions(run: TaskRun) -> str:
    state = _quote_state(run)
    return (
        "你是 Enclave 的繁體中文報價語音助理。語氣簡潔、自然、一次只問一個問題。"
        "你的工作是協助填妥報價草稿，不是替使用者核准、送審或匯出文件。"
        "聽到任何報價資料後，立即呼叫 update_quote_draft 寫入可確定的欄位；"
        "不要猜測客戶、料號、日期、價格或付款條件。數字不清楚時要複誦確認。"
        "每次工具回傳後，依 missing_fields 詢問下一個欄位。資料齊全時逐項簡短複誦，"
        "並請使用者在畫面核對後親自按送審。絕對不要聲稱已完成送審或已產生正式文件。"
        f"目前草稿狀態：{json.dumps(state, ensure_ascii=False, default=str)}"
    )


@router.post("/quote/session")
async def create_quote_realtime_session(
    request: Request,
    run_id: UUID = Query(...),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Response:
    if not settings.VOICE_REALTIME_ENABLED:
        raise HTTPException(status_code=503, detail="realtime voice assistant is disabled")
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="realtime voice provider is not configured")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type != "application/sdp":
        raise HTTPException(status_code=415, detail="application/sdp is required")
    offer = (await request.body()).decode("utf-8", errors="strict")
    if not offer.startswith("v=0") or len(offer) > 256_000:
        raise HTTPException(status_code=400, detail="invalid SDP offer")

    run = _own_quote_run(db, current_user, run_id)
    if run.status not in {"draft", "in_progress"}:
        raise HTTPException(status_code=409, detail=f"quote task is {run.status}")

    session_config = {
        "type": "realtime",
        "model": settings.VOICE_REALTIME_MODEL,
        "instructions": _instructions(run),
        "audio": {
            "input": {
                "transcription": {"model": "gpt-realtime-whisper", "language": "zh"},
                "turn_detection": {"type": "semantic_vad"},
            },
            "output": {"voice": settings.VOICE_REALTIME_VOICE},
        },
        "tools": [
            {
                "type": "function",
                "name": "update_quote_draft",
                "description": "將使用者明確提供的報價欄位寫入目前草稿，並回傳尚缺欄位。",
                "parameters": _tool_parameters(),
            },
            {
                "type": "function",
                "name": "review_quote_draft",
                "description": "讀取目前報價草稿、計算值與尚缺欄位；不會送審或匯出。",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        ],
        "tool_choice": "auto",
    }
    safety_id = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        str(current_user.id).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    try:
        timeout = httpx.Timeout(settings.VOICE_REALTIME_CONNECT_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout) as client:
            upstream = await client.post(
                "https://api.openai.com/v1/realtime/calls",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "OpenAI-Safety-Identifier": safety_id,
                },
                files={
                    "sdp": (None, offer),
                    "session": (None, json.dumps(session_config, ensure_ascii=False)),
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="unable to connect realtime voice provider") from exc
    if upstream.status_code >= 400:
        # Do not relay provider internals or credentials to the browser.
        raise HTTPException(status_code=502, detail="realtime voice provider rejected the session")
    return Response(content=upstream.text, media_type="application/sdp")


def _coerce_quote_value(field: Any, value: Any) -> Any:
    if value is None or value == "":
        return None
    if field.type in {FieldType.NUMBER, FieldType.AMOUNT}:
        if isinstance(value, bool):
            raise ValueError("boolean is not a number")
        number = float(str(value).replace(",", ""))
        if not math.isfinite(number):
            raise ValueError("value must be a finite number")
        if field.type == FieldType.NUMBER and number.is_integer():
            number = int(number)
        if field.min_value is not None and number < field.min_value:
            raise ValueError("value is below minimum")
        if field.max_value is not None and number > field.max_value:
            raise ValueError("value is above maximum")
        return number
    text = str(value).strip()
    if len(text) > 500:
        raise ValueError("value is too long")
    if field.type == FieldType.DATE:
        date.fromisoformat(text)
    if field.options and text not in field.options:
        raise ValueError("value is not an allowed option")
    return text


@router.post("/quote/tools")
def call_quote_realtime_tool(
    body: QuoteToolCall,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_verified_user),
) -> Dict[str, Any]:
    if not settings.VOICE_REALTIME_ENABLED:
        raise HTTPException(status_code=503, detail="realtime voice assistant is disabled")
    run = _own_quote_run(db, current_user, body.run_id)
    if run.status not in {"draft", "in_progress"}:
        raise HTTPException(status_code=409, detail=f"quote task is {run.status}")
    if body.name == "review_quote_draft":
        return _quote_state(run)
    if body.name != "update_quote_draft":
        raise HTTPException(status_code=400, detail="tool is not allowed")

    provenance = dict(run.provenance or {})
    completed_calls = list(provenance.get("realtime_tool_call_ids") or [])
    if body.call_id in completed_calls:
        return {**_quote_state(run), "idempotent": True}

    schema = _quote_schema()
    allowed = {field.name: field for field in schema.fields if not field.calculated}
    unknown = sorted(set(body.arguments) - set(allowed))
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown quote fields: {', '.join(unknown)}")
    values: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    for name, raw in body.arguments.items():
        try:
            coerced = _coerce_quote_value(allowed[name], raw)
            if coerced is not None:
                values[name] = coerced
        except (TypeError, ValueError) as exc:
            errors[name] = str(exc)
    if errors:
        raise HTTPException(status_code=422, detail={"invalid_fields": errors})
    if not values:
        return {**_quote_state(run), "updated_fields": []}

    snapshot = dict(run.input_snapshot or {})
    current_values = dict(snapshot.get("values") or {})
    current_values.update(values)
    snapshot["values"] = current_values
    run.input_snapshot = snapshot
    engine = get_task_engine(db)
    engine.record_field_sources(
        run,
        {name: {"source": "voice", "ref": body.call_id} for name in values},
    )
    provenance = dict(run.provenance or {})
    completed_calls = list(provenance.get("realtime_tool_call_ids") or [])
    completed_calls.append(body.call_id)
    provenance["realtime_tool_call_ids"] = completed_calls[-100:]
    run.provenance = provenance
    db.commit()
    db.refresh(run)
    return {**_quote_state(run), "updated_fields": sorted(values)}
