"""Benchmark-to-capability routing for DataLoom."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class RoutingError(ValueError):
    pass


@dataclass(frozen=True)
class BenchmarkRoute:
    benchmark: str
    capability: str
    role: str
    adapter: str
    requires_ready_evidence: bool


DEFAULT_ROUTES = {
    "code-aware": BenchmarkRoute(
        "code-aware", "project-understanding", "project-understanding", "dataloom-native-qwen", False
    ),
    "spider2-dbt": BenchmarkRoute(
        "spider2-dbt", "dbt-project-understanding", "project-understanding", "signalpilot-dbt", False
    ),
    "bird": BenchmarkRoute("bird", "nl2sql", "sql-generation", "dataagent-bird", False),
}


class BenchmarkRouter:
    def __init__(self, routes: Mapping[str, BenchmarkRoute] = DEFAULT_ROUTES) -> None:
        self.routes = dict(routes)

    def select(self, benchmark: str) -> BenchmarkRoute:
        normalized = benchmark.strip().casefold()
        aliases = {"spider-2.0-dbt": "spider2-dbt", "spider2.0-dbt": "spider2-dbt", "codeaware": "code-aware"}
        normalized = aliases.get(normalized, normalized)
        route = self.routes.get(normalized)
        if route is None:
            raise RoutingError(f"unsupported benchmark: {benchmark}")
        return route

    def catalog(self) -> list[dict[str, Any]]:
        return [vars(self.routes[name]) for name in sorted(self.routes)]

