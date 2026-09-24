#!/usr/bin/env python3
"""Backfill Semantic Layer vectors through its public entity API.

The script is namespace-scoped, defaults to a read-only dry run, and never
writes vector columns directly.  It replays safe source text through the
service so the configured embedding listener remains the sole vector writer.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ENTITY_TYPES = ("data_table", "data_column", "data_column_value")


@dataclass(frozen=True)
class BackfillPolicy:
    source_fields: tuple[str, ...]
    update_fields: tuple[str, ...]
    vector_fields: tuple[str, ...]


POLICIES = {
    "data_table": BackfillPolicy(
        source_fields=("table_description", "table_name", "name"),
        update_fields=("tableDescription",),
        vector_fields=("table_description_vector",),
    ),
    "data_column": BackfillPolicy(
        source_fields=(
            "column_description_short",
            "column_description",
            "column_name_desc",
            "column_name_en",
            "name",
        ),
        update_fields=("columnDescriptionShort", "columnDescription"),
        vector_fields=("column_description_short_vector",),
    ),
    "data_column_value": BackfillPolicy(
        source_fields=("description", "value"),
        update_fields=("description", "value"),
        vector_fields=("description_vector", "value_vector"),
    ),
}


def _usable(value: Any) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict) and value.get("null") is True:
        return False
    return True


def build_update(type_name: str, attributes: dict[str, Any]) -> tuple[dict[str, Any], str, bool]:
    """Return safe update payload, selected source field, and fallback flag."""
    policy = POLICIES[type_name]
    source_field = next((field for field in policy.source_fields if _usable(attributes.get(field))), None)
    if source_field is None:
        raise ValueError(f"{type_name} has no usable embedding source")
    source_value = attributes[source_field]
    fallback = source_field != policy.source_fields[0]

    if type_name == "data_column_value":
        value = attributes.get("value")
        if not _usable(value):
            raise ValueError("data_column_value has no usable value")
        description = attributes.get("description")
        if not _usable(description):
            description = value
        return {"description": description, "value": value}, source_field, fallback

    return {field: source_value for field in policy.update_fields}, source_field, fallback


class SemanticApi:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/") + "/api/semantic/v1"
        self.timeout = timeout

    def _json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}/{path.lstrip('/')}",
            data=body,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"semantic API {method} {path} failed: HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"semantic API {method} {path} failed: {exc.reason}") from exc

    def entities(self, type_name: str) -> list[dict[str, Any]]:
        payload = self._json("POST", "search/basic", {"typeName": type_name, "limit": 1000, "offset": 0})
        entities = payload.get("entities") if isinstance(payload, dict) else None
        if not isinstance(entities, list):
            raise RuntimeError(f"unexpected search response for {type_name}")
        return entities

    def update(self, type_name: str, guid: str, payload: dict[str, Any]) -> None:
        self._json("PUT", f"entity/{type_name}/guid/{guid}", payload)


def _in_namespace(entity: dict[str, Any], namespace: str) -> bool:
    attributes = entity.get("attributes") or {}
    qualified_name = str(attributes.get("qualified_name") or "")
    return qualified_name == namespace or qualified_name.startswith(namespace + ".")


def _snapshot(api: SemanticApi, namespace: str) -> dict[str, list[dict[str, Any]]]:
    return {
        type_name: [entity for entity in api.entities(type_name) if _in_namespace(entity, namespace)]
        for type_name in ENTITY_TYPES
    }


def _counts(snapshot: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for type_name, entities in snapshot.items():
        policy = POLICIES[type_name]
        counts = {"total": len(entities)}
        for vector_field in policy.vector_fields:
            counts[vector_field] = sum(
                _present((entity.get("attributes") or {}).get(vector_field)) for entity in entities
            )
        result[type_name] = counts
    return result


def run(api: SemanticApi, namespace: str, apply: bool) -> dict[str, Any]:
    if not namespace.strip() or namespace.strip() != namespace:
        raise ValueError("namespace must be a non-empty exact identifier")
    before = _snapshot(api, namespace)
    actions: list[dict[str, Any]] = []
    for type_name in ENTITY_TYPES:
        for entity in before[type_name]:
            attributes = entity.get("attributes") or {}
            qualified_name = str(attributes.get("qualified_name") or "")
            payload, source_field, fallback = build_update(type_name, attributes)
            action = {
                "type_name": type_name,
                "guid": entity.get("guid"),
                "qualified_name": qualified_name,
                "source_field": source_field,
                "fallback_applied": fallback,
                "updated": False,
            }
            if apply:
                api.update(type_name, str(entity["guid"]), payload)
                action["updated"] = True
            actions.append(action)

    after = _snapshot(api, namespace) if apply else before
    return {
        "namespace": namespace,
        "mode": "apply" if apply else "dry-run",
        "sql_few_shot_used": False,
        "gold_data_used": False,
        "before": _counts(before),
        "after": _counts(after),
        "actions": actions,
        "complete": all(
            counts[field] == counts["total"]
            for type_name, counts in _counts(after).items()
            for field in POLICIES[type_name].vector_fields
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:32000")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--apply", action="store_true", help="perform updates; otherwise dry-run")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    started = time.time()
    report = run(SemanticApi(args.base_url, args.timeout), args.namespace, args.apply)
    report["elapsed_seconds"] = round(time.time() - started, 3)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if args.apply and not report["complete"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
