"""Project native CSV/XLSX markdown tables into revisioned rows and fields."""
from __future__ import annotations

import hashlib
import re
from typing import Optional

from app.models.knowledge_engine import StructuredField, StructuredRow, StructuredTable

SHEET = re.compile(r"(?m)^##\s*工作表[：:]\s*(.+?)\s*$")
IDENTITY_HINTS = ("id", "編號", "代號", "料號", "設備", "客戶", "姓名", "名稱", "單號")
DATE_VALUE = re.compile(r"^(?:19|20)\d{2}[-/.年]\d{1,2}(?:[-/.月]\d{1,2}日?)?$")
NUMBER_VALUE = re.compile(r"^([-+]?\d[\d,]*(?:\.\d+)?)\s*([^\d\s]+)?$")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _normalized_field(header: str, value: str) -> tuple[dict, str, Optional[str]]:
    raw = (value or "").strip()
    lowered = header.casefold()
    if DATE_VALUE.fullmatch(raw):
        return {"value": raw}, "date", None
    match = NUMBER_VALUE.fullmatch(raw)
    if match:
        number_text = match.group(1).replace(",", "")
        number: int | float = float(number_text) if "." in number_text else int(number_text)
        unit = match.group(2)
        if any(token in lowered for token in ("單價", "總價", "金額", "費用", "price", "amount", "total")):
            value_type = "money"
        elif any(token in lowered for token in ("數量", "quantity", "qty")):
            value_type = "quantity"
        elif unit in {"%", "％"}:
            value_type = "ratio"
        else:
            value_type = "number"
        return {"value": number, "raw": raw}, value_type, unit
    return {"value": raw}, "text", None


def _tables(text: str):
    matches = list(SHEET.finditer(text or ""))
    if not matches:
        yield None, text or ""
        return
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        yield match.group(1).strip(), text[match.end():end]


def _parse_rows(body: str) -> tuple[list[str], list[list[str]]]:
    lines = [line.strip().strip("|") for line in (body or "").splitlines() if "|" in line]
    if len(lines) < 2:
        return [], []
    parsed = [[cell.strip() for cell in line.split("|")] for line in lines]
    parsed = [row for row in parsed if not all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in row)]
    if len(parsed) < 2:
        return [], []
    headers = parsed[0]
    if not headers or any(not header for header in headers) or len(set(headers)) != len(headers):
        return [], []
    width = len(headers)
    return headers, [(row + [""] * width)[:width] for row in parsed[1:] if any(cell.strip() for cell in row)]


def upsert_structured_projection(db, document, text: str) -> int:
    revision = int(document.version or 1)
    if db.query(StructuredTable.id).filter(
        StructuredTable.document_id == document.id,
        StructuredTable.document_revision == revision,
    ).first():
        return 0
    row_count = 0
    for table_index, (worksheet, body) in enumerate(_tables(text), 1):
        headers, rows = _parse_rows(body)
        if not headers or not rows:
            continue
        table = StructuredTable(
            tenant_id=document.tenant_id,
            document_id=document.id,
            document_revision=revision,
            worksheet=worksheet,
            table_key=f"{worksheet or 'table'}:{table_index}",
            headers=headers,
            content_hash=_hash(body),
        )
        db.add(table); db.flush()
        identity_indexes = [i for i, header in enumerate(headers) if any(hint in header.casefold() for hint in IDENTITY_HINTS)] or [0]
        for number, values in enumerate(rows, 1):
            identity = {headers[i]: values[i] for i in identity_indexes if values[i]}
            row = StructuredRow(
                tenant_id=document.tenant_id,
                table_id=table.id,
                row_key=_hash(f"{worksheet}:{number}:{'|'.join(values)}")[:32],
                row_number=number,
                identity_json=identity,
                row_hash=_hash("|".join(values)),
            )
            db.add(row); db.flush()
            projected_fields = []
            for header, value in zip(headers, values):
                normalized, value_type, unit = _normalized_field(header, value)
                projected_fields.append(StructuredField(
                    tenant_id=document.tenant_id,
                    row_id=row.id,
                    field_name=header,
                    raw_value=value,
                    normalized_value=normalized,
                    value_type=value_type,
                    unit=unit,
                    confidence=1.0,
                ))
            db.add_all(projected_fields)
            row_count += 1
    db.flush()
    return row_count
