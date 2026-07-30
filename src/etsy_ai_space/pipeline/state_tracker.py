"""Central JSON state + log feed for the swarm dashboard."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from ..models import iso_time

DEFAULT_AGENTS = ("Scraper", "Manager", "Copywriter", "Designer", "SEO")


def default_pipeline_dir() -> Path:
    return Path.cwd() / "etsy_ai_space" / "pipeline"


def default_state_path() -> Path:
    return default_pipeline_dir() / "state.json"


def default_log_path() -> Path:
    return default_pipeline_dir() / "system.log"


def _default_agent(name: str) -> dict[str, Any]:
    now = iso_time()
    return {
        "name": name,
        "status": "Idle",
        "last_active": now,
        "health": "idle",
        "success_count": 0,
        "error_count": 0,
    }


def default_state() -> dict[str, Any]:
    now = iso_time()
    return {
        "updated_at": now,
        "metrics": {
            "listings_generated": 0,
            "successful_uploads": 0,
            "compute_cost_usd": 0.0,
            "revenue_usd": 0.0,
            "scrape_runs": 0,
            "successes": 0,
            "errors": 0,
        },
        "agents": [_default_agent(name) for name in DEFAULT_AGENTS],
        "logs": [
            {
                "timestamp": now,
                "level": "INFO",
                "message": "Swarm state tracker initialized — all agents idle.",
            }
        ],
    }


def _health_from_counts(success_count: int, error_count: int, *, status: str) -> str:
    if status.lower() == "error":
        return "error"
    total = success_count + error_count
    if total == 0:
        return "idle"
    rate = success_count / total
    if rate >= 0.85:
        return "healthy"
    if rate >= 0.5:
        return "warning"
    return "error"


@dataclass
class SwarmStateTracker:
    """Read/write pipeline/state.json and append to system.log."""

    state_path: Path | None = None
    log_path: Path | None = None

    def __post_init__(self) -> None:
        self.state_path = self.state_path or default_state_path()
        self.log_path = self.log_path or default_log_path()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.state_path.exists():
            self.save(default_state())

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return default_state()
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def save(self, state: dict[str, Any]) -> None:
        state["updated_at"] = iso_time()
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def log(self, message: str, *, level: str = "INFO") -> None:
        state = self.load()
        entry = {"timestamp": iso_time(), "level": level.upper(), "message": message}
        logs = list(state.get("logs") or [])
        logs.append(entry)
        state["logs"] = logs[-200:]
        self.save(state)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{entry['timestamp']}] {entry['level']}: {message}\n")

    def tail_log_file(self, *, lines: int = 80) -> str:
        if not self.log_path.exists():
            return "No system logs yet."
        content = self.log_path.read_text(encoding="utf-8").splitlines()
        return "\n".join(content[-lines:])

    def set_agent(self, name: str, status: str, *, health: str | None = None) -> None:
        state = self.load()
        agents = state.get("agents") or []
        found = False
        for agent in agents:
            if agent["name"] == name:
                agent["status"] = status
                agent["last_active"] = iso_time()
                if health is not None:
                    agent["health"] = health
                else:
                    agent["health"] = _health_from_counts(
                        int(agent.get("success_count") or 0),
                        int(agent.get("error_count") or 0),
                        status=status,
                    )
                found = True
                break
        if not found:
            agents.append(_default_agent(name))
            agents[-1]["status"] = status
            if health is not None:
                agents[-1]["health"] = health
        state["agents"] = agents
        self.save(state)

    def record_success(self, name: str) -> None:
        state = self.load()
        metrics = state.setdefault("metrics", default_state()["metrics"])
        metrics["successes"] = int(metrics.get("successes") or 0) + 1
        for agent in state.get("agents") or []:
            if agent["name"] == name:
                agent["success_count"] = int(agent.get("success_count") or 0) + 1
                agent["status"] = "Idle"
                agent["last_active"] = iso_time()
                agent["health"] = _health_from_counts(
                    agent["success_count"],
                    int(agent.get("error_count") or 0),
                    status="Idle",
                )
                break
        self.save(state)

    def record_error(self, name: str, message: str) -> None:
        state = self.load()
        metrics = state.setdefault("metrics", default_state()["metrics"])
        metrics["errors"] = int(metrics.get("errors") or 0) + 1
        for agent in state.get("agents") or []:
            if agent["name"] == name:
                agent["error_count"] = int(agent.get("error_count") or 0) + 1
                agent["status"] = "Error"
                agent["last_active"] = iso_time()
                agent["health"] = "error"
                break
        self.save(state)
        self.log(f"{name} error: {message}", level="ERROR")

    def bump_metric(self, key: str, amount: float = 1.0) -> None:
        state = self.load()
        metrics = state.setdefault("metrics", default_state()["metrics"])
        metrics[key] = float(metrics.get(key) or 0) + amount
        self.save(state)

    def sync_metrics_from_db(self, db_stats: dict[str, Any]) -> None:
        state = self.load()
        metrics = state.setdefault("metrics", default_state()["metrics"])
        metrics["listings_generated"] = int(db_stats.get("listing_drafts") or 0)
        metrics["scrape_runs"] = int(db_stats.get("scrape_runs") or 0)
        metrics["scraped_listings"] = int(db_stats.get("listings") or 0)
        self.save(state)

    @contextmanager
    def agent_activity(self, name: str, active_status: str) -> Iterator[None]:
        self.set_agent(name, active_status, health="healthy")
        self.log(f"{name} → {active_status}")
        try:
            yield
            self.record_success(name)
            self.log(f"{name} completed {active_status}")
        except Exception as exc:
            self.record_error(name, str(exc))
            raise

    @staticmethod
    def global_instance() -> SwarmStateTracker:
        if not hasattr(SwarmStateTracker, "_singleton"):
            SwarmStateTracker._singleton = SwarmStateTracker()  # type: ignore[attr-defined]
        return SwarmStateTracker._singleton  # type: ignore[attr-defined]
