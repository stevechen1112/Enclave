"""Deterministic row-bound lookup and aggregate resolver."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class Record:
    row_id: str
    identity: Dict[str, str]
    fields: Dict[str, Any]
    source_ref: Dict[str, Any]


@dataclass(frozen=True)
class Resolution:
    status: str
    records: List[Record] = field(default_factory=list)
    values: List[Dict[str, Any]] = field(default_factory=list)
    missing_fields: List[str] = field(default_factory=list)
    reason: str = ""
    calculation: Optional[Dict[str, Any]] = None


class StructuredRecordResolver:
    def resolve(self, records: Iterable[Record], *, identity: Dict[str, str], fields: List[str]) -> Resolution:
        rows = [r for r in records if all(str(r.identity.get(k, "")).casefold() == str(v).casefold() for k, v in identity.items())]
        if not rows:
            return Resolution("not_found", reason="no row matches every identity field")
        if len(rows) > 1:
            return Resolution("ambiguous", records=rows, reason="identity fields do not select one row")
        row = rows[0]
        missing = [f for f in fields if f not in row.fields or row.fields[f] in (None, "")]
        values = [{"field": f, "value": row.fields[f], "row_id": row.row_id, "source_ref": row.source_ref} for f in fields if f not in missing]
        return Resolution("complete" if not missing else "partial", [row], values, missing)

    def aggregate(self, records: Iterable[Record], *, field: str, operation: str) -> Resolution:
        rows = list(records)
        if operation == "count":
            return Resolution("complete", rows, calculation={"operation": "count", "input_row_ids": [r.row_id for r in rows], "result": len(rows)})
        numbers: List[tuple[str, Decimal]] = []
        for row in rows:
            try:
                numbers.append((row.row_id, Decimal(str(row.fields[field]).replace(",", ""))))
            except (KeyError, InvalidOperation, TypeError):
                return Resolution("partial", rows, missing_fields=[field], reason=f"row {row.row_id} has no exact numeric value")
        if not numbers:
            return Resolution("not_found", reason="no input rows")
        values = [v for _, v in numbers]
        operations = {"sum": sum(values), "min": min(values), "max": max(values)}
        if operation not in operations:
            return Resolution("invalid", reason="operation must be count, sum, min or max")
        result = operations[operation]
        return Resolution("complete", rows, calculation={"operation": operation, "field": field,
            "input_row_ids": [rid for rid, _ in numbers], "input_values": [str(v) for _, v in numbers], "result": str(result)})

