"""Dependency-light capability registry and guarded action router.

This ports the reusable architectural boundary from DataAgent, not its
TypeScript implementation. Capabilities declare actions and dependencies;
the router adds authorization, guards, idempotency, and bounded observations.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping


class CapabilityError(ValueError):
    pass


ActionHandler = Callable[[Mapping[str, Any]], Any]
Guard = Callable[[Mapping[str, Any]], None]
Projector = Callable[[Any], Any]


@dataclass(frozen=True)
class Action:
    name: str
    handler: ActionHandler
    guards: tuple[Guard, ...] = ()
    required_scopes: frozenset[str] = frozenset()
    projector: Projector | None = None


@dataclass(frozen=True)
class CapabilityManifest:
    name: str
    version: str
    actions: tuple[Action, ...]
    dependencies: tuple[str, ...] = ()
    benchmarks: frozenset[str] = frozenset()
    roles: frozenset[str] = frozenset()
    metadata: Mapping[str, Any] = field(default_factory=dict)


class CapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[str, CapabilityManifest] = {}
        self._action_owners: dict[str, str] = {}

    def register(self, manifest: CapabilityManifest) -> None:
        if manifest.name in self._capabilities:
            raise CapabilityError(f"duplicate capability: {manifest.name}")
        action_names = [action.name for action in manifest.actions]
        if len(action_names) != len(set(action_names)):
            raise CapabilityError(f"duplicate action inside capability: {manifest.name}")
        collisions = sorted(set(action_names) & self._action_owners.keys())
        if collisions:
            raise CapabilityError(f"actions already registered: {', '.join(collisions)}")
        self._capabilities[manifest.name] = manifest
        self._action_owners.update({name: manifest.name for name in action_names})

    def resolve(self, selected: Iterable[str]) -> list[CapabilityManifest]:
        ordered: list[CapabilityManifest] = []
        permanent: set[str] = set()
        active: set[str] = set()

        def visit(name: str) -> None:
            if name in permanent:
                return
            if name in active:
                raise CapabilityError(f"capability dependency cycle at: {name}")
            manifest = self._capabilities.get(name)
            if manifest is None:
                raise CapabilityError(f"missing capability dependency: {name}")
            active.add(name)
            for dependency in manifest.dependencies:
                visit(dependency)
            active.remove(name)
            permanent.add(name)
            ordered.append(manifest)

        for name in selected:
            visit(name)
        return ordered

    def action(self, name: str) -> Action:
        owner = self._action_owners.get(name)
        if owner is None:
            raise CapabilityError(f"unknown action: {name}")
        return next(action for action in self._capabilities[owner].actions if action.name == name)

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "name": item.name,
                "version": item.version,
                "dependencies": list(item.dependencies),
                "actions": [action.name for action in item.actions],
                "benchmarks": sorted(item.benchmarks),
                "roles": sorted(item.roles),
            }
            for item in sorted(self._capabilities.values(), key=lambda value: value.name)
        ]


class ActionRouter:
    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry
        self._idempotency: dict[tuple[str, str], dict[str, Any]] = {}

    def dispatch(
        self,
        action_name: str,
        payload: Mapping[str, Any],
        *,
        scopes: Iterable[str] = (),
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        action = self.registry.action(action_name)
        missing = action.required_scopes - frozenset(scopes)
        if missing:
            raise CapabilityError(f"missing scopes for {action_name}: {', '.join(sorted(missing))}")
        payload_digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        cache_key = (action_name, idempotency_key) if idempotency_key else None
        if cache_key and cache_key in self._idempotency:
            previous = self._idempotency[cache_key]
            if previous["payload_sha256"] != payload_digest:
                raise CapabilityError("idempotency key was reused with a different payload")
            return {**previous, "replayed": True}
        for guard in action.guards:
            guard(payload)
        raw = action.handler(payload)
        observation = action.projector(raw) if action.projector else raw
        result = {
            "action": action_name,
            "payload_sha256": payload_digest,
            "observation": observation,
            "replayed": False,
        }
        if cache_key:
            self._idempotency[cache_key] = result
        return result

