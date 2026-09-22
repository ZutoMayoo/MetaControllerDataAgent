"""Bounded model observations inspired by DataAgent context projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class ProjectionPolicy:
    max_items: int = 40
    max_chars: int = 12000
    max_item_chars: int = 800

    def __post_init__(self) -> None:
        if min(self.max_items, self.max_chars, self.max_item_chars) < 1:
            raise ValueError("projection budgets must be positive")


def project_search_matches(
    matches: Iterable[Mapping[str, Any]], policy: ProjectionPolicy = ProjectionPolicy()
) -> dict[str, Any]:
    """Keep source identity while bounding broad grep/glob observations."""
    source = list(matches)
    projected: list[dict[str, Any]] = []
    used = 0
    for match in source[: policy.max_items]:
        item = dict(match)
        text = str(item.get("text", ""))
        if len(text) > policy.max_item_chars:
            item["text"] = text[: policy.max_item_chars]
            item["text_truncated"] = True
        size = len(str(item))
        if projected and used + size > policy.max_chars:
            break
        if not projected and size > policy.max_chars:
            item["text"] = str(item.get("text", ""))[: max(1, policy.max_chars // 2)]
            item["text_truncated"] = True
            size = len(str(item))
        projected.append(item)
        used += size
    omitted = len(source) - len(projected)
    return {
        "matches": projected,
        "truncation": {
            "truncated": omitted > 0 or any(item.get("text_truncated") for item in projected),
            "original_items": len(source),
            "returned_items": len(projected),
            "omitted_items": omitted,
            "budget": {
                "max_items": policy.max_items,
                "max_chars": policy.max_chars,
                "max_item_chars": policy.max_item_chars,
            },
        },
    }


def project_text(text: str, *, max_chars: int = 16000) -> dict[str, Any]:
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    value = text[:max_chars]
    return {
        "text": value,
        "truncation": {
            "truncated": len(value) < len(text),
            "original_chars": len(text),
            "returned_chars": len(value),
        },
    }

