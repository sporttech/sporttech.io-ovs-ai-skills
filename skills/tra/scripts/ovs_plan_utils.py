#!/usr/bin/env python3
"""Shared helpers for declarative OVS plan executors."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class ApiError(RuntimeError):
    pass


def api_url(base_url: str, path: str) -> str:
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def request_json(
    base_url: str,
    path: str,
    token: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, str]]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"token {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        api_url(base_url, path), data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            response_headers = dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise ApiError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"{method} {path} failed: {exc.reason}") from exc
    if not raw:
        return None, response_headers
    try:
        return json.loads(raw.decode("utf-8")), response_headers
    except json.JSONDecodeError:
        return raw.decode("utf-8", "replace"), response_headers


def extract_created_id(location: str | None) -> int:
    if not location:
        raise ApiError("Create request did not return a Location header.")
    try:
        return int(location.rstrip("/").split("/")[-1])
    except ValueError as exc:
        raise ApiError(f"Could not extract resource ID from Location: {location}") from exc


def model_section(api_ai: dict[str, Any], name: str) -> Any:
    if name in api_ai:
        return api_ai[name]
    model = api_ai.get("model")
    if isinstance(model, dict):
        return model.get(name)
    return None


def writable_field_docs(api_ai: dict[str, Any], entity_name: str) -> dict[str, dict[str, Any]]:
    docs = model_section(api_ai, "fieldDocs") or []
    result: dict[str, dict[str, Any]] = {}
    for doc in docs:
        if str(doc.get("entity", "")).lower() != entity_name.lower():
            continue
        field = str(doc.get("field", "")).strip()
        if not field or doc.get("writable") is False or doc.get("readOnly") is True:
            continue
        write_format = str(doc.get("writeFormat", "")).strip()
        normalized = write_format.lower()
        if not write_format and doc.get("writable") is not True:
            continue
        if normalized.startswith("do not ") or "use session actions" in normalized:
            continue
        result[field] = doc
    return result


def validate_field_value(
    entity_name: str, field: str, value: Any, doc: dict[str, Any]
) -> None:
    expected = str(doc.get("writeType") or doc.get("type") or "").lower()
    write_format = str(doc.get("writeFormat", "")).lower()
    if not expected:
        if "integer" in write_format:
            expected = "integer"
        elif "string" in write_format:
            expected = "string"
        elif "boolean" in write_format:
            expected = "boolean"
        elif "array" in write_format or "list" in write_format:
            expected = "array"
    if expected in {"integer", "int"} and (not isinstance(value, int) or isinstance(value, bool)):
        raise SystemExit(f"{entity_name}.{field} must be an integer.")
    if expected in {"string", "str"} and not isinstance(value, str):
        raise SystemExit(f"{entity_name}.{field} must be a string.")
    if expected in {"boolean", "bool"} and not isinstance(value, bool):
        raise SystemExit(f"{entity_name}.{field} must be a boolean.")
    if expected in {"array", "list"} and not isinstance(value, list):
        raise SystemExit(f"{entity_name}.{field} must be an array.")
    if field == "Number" and (not isinstance(value, int) or value <= 0):
        raise SystemExit("Session.Number must be a positive integer.")
    if field == "RotationView" and (
        not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 7
    ):
        raise SystemExit("Session.RotationView must be an integer from 0 to 7.")
    if field in {"Time", "SessionTitle"} and (not isinstance(value, str) or not value.strip()):
        raise SystemExit(f"Session.{field} must be a non-empty string.")


def validate_fields(
    entity_name: str,
    fields: Any,
    writable: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(fields, dict) or not fields:
        raise SystemExit(f"{entity_name} fields must be a non-empty object.")
    unknown = sorted(set(fields) - set(writable))
    if unknown:
        raise SystemExit(
            f"Unknown or non-writable {entity_name} field(s): {', '.join(unknown)}"
        )
    for field, value in fields.items():
        validate_field_value(entity_name, field, value, writable[field])
    return dict(fields)


def collection_map(document: Any, name: str) -> dict[str, dict[str, Any]]:
    if not isinstance(document, dict):
        return {}
    candidates = [document]
    event = document.get("Event")
    if isinstance(event, dict):
        candidates.append(event)
    for candidate in candidates:
        value = candidate.get(name)
        if isinstance(value, dict):
            return {str(key): item for key, item in value.items() if isinstance(item, dict)}
        if isinstance(value, list):
            result: dict[str, dict[str, Any]] = {}
            for item in value:
                if isinstance(item, dict):
                    item_id = item.get("ID", item.get("id"))
                    if item_id is not None:
                        result[str(item_id)] = item
                elif isinstance(item, int):
                    result[str(item)] = {"ID": item}
            return result
    return {}


def refs_for_session(session: dict[str, Any]) -> list[tuple[int, int]]:
    groups = session.get("Groups") or []
    frames = session.get("GroupFrame") or []
    return [(int(group), int(frame)) for group, frame in zip(groups, frames)]
