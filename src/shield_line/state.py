"""Conversation state, threat history, and dashboard snapshots."""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from .detection import ThreatAssessment, assess_message, combine_recent_escalation
from .responder import BotTurn, TimeSinkSession, demo_inbound_messages, generate_reply

Mode = Literal["passive", "shield"]


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


@dataclass
class ChatMessage:
    role: Literal["inbound", "bot", "system"]
    text: str
    at: datetime = field(default_factory=utc_now)
    assessment: ThreatAssessment | None = None
    bot_meta: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "role": self.role,
            "text": self.text,
            "at": iso_time(self.at),
        }
        if self.assessment is not None:
            payload["assessment"] = self.assessment.to_dict()
        if self.bot_meta is not None:
            payload["bot"] = self.bot_meta
        return payload


class ShieldState:
    def __init__(self, *, auto_shield: bool = True, max_messages: int = 500) -> None:
        self._lock = asyncio.Lock()
        self.auto_shield = auto_shield
        self.max_messages = max_messages
        self.mode: Mode = "shield" if auto_shield else "passive"
        self.session = TimeSinkSession(session_id=str(uuid.uuid4()))
        self.messages: deque[ChatMessage] = deque(maxlen=max_messages)
        self.threat_scores: deque[int] = deque(maxlen=24)
        self.events: deque[dict[str, Any]] = deque(maxlen=80)
        self._demo_index = 0
        self._version = 0

    async def add_system_event(self, kind: str, detail: str) -> None:
        async with self._lock:
            self.events.appendleft(
                {"kind": kind, "detail": detail, "at": iso_time(utc_now())}
            )
            self._version += 1

    async def set_mode(self, mode: Mode) -> dict[str, Any]:
        async with self._lock:
            previous = self.mode
            self.mode = mode
            event = {
                "kind": "mode-change",
                "detail": f"Mode: {previous} → {mode}",
                "at": iso_time(utc_now()),
            }
            self.events.appendleft(event)
            self._version += 1
            return event

    async def set_auto_shield(self, enabled: bool) -> None:
        async with self._lock:
            self.auto_shield = enabled
            self._version += 1

    async def reset_session(self) -> None:
        async with self._lock:
            self.session = TimeSinkSession(session_id=str(uuid.uuid4()))
            self.messages.clear()
            self.threat_scores.clear()
            self._demo_index = 0
            self.events.appendleft(
                {
                    "kind": "session-reset",
                    "detail": "New anonymous session started.",
                    "at": iso_time(utc_now()),
                }
            )
            self._version += 1

    async def ingest_inbound(self, text: str) -> dict[str, Any]:
        async with self._lock:
            prior = combine_recent_escalation(list(self.threat_scores))
            assessment = assess_message(text, prior_escalation=prior)
            self.threat_scores.append(assessment.score)

            inbound = ChatMessage(role="inbound", text=text, assessment=assessment)
            self.messages.append(inbound)

            if assessment.shield_recommended and self.auto_shield:
                self.mode = "shield"
            elif assessment.level in ("high", "critical"):
                self.events.appendleft(
                    {
                        "kind": "threat-alert",
                        "detail": f"Threat level {assessment.level} — shield engaged.",
                        "at": iso_time(utc_now()),
                    }
                )

            response: BotTurn | None = None
            if self.mode == "shield" and (assessment.shield_recommended or assessment.level != "none"):
                response = generate_reply(text, assessment, self.session)
                bot_msg = ChatMessage(
                    role="bot",
                    text=response.text,
                    bot_meta=response.to_dict(),
                )
                self.messages.append(bot_msg)
            elif self.mode == "shield" and self.session.threat_turns > 0:
                # Stay in shield once threat detected — keep wasting time on follow-ups
                response = generate_reply(text, assessment, self.session)
                bot_msg = ChatMessage(
                    role="bot",
                    text=response.text,
                    bot_meta=response.to_dict(),
                )
                self.messages.append(bot_msg)

            self._version += 1
            return self._build_turn_payload(assessment, response)

    def _build_turn_payload(self, assessment: ThreatAssessment, response: BotTurn | None) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "assessment": assessment.to_dict(),
            "bot": response.to_dict() if response else None,
            "stats": self._stats_unlocked(),
        }

    def _stats_unlocked(self) -> dict[str, Any]:
        s = self.session
        return {
            "turn_count": s.turn_count,
            "threat_turns": s.threat_turns,
            "estimated_wasted_seconds": round(s.estimated_wasted_seconds, 1),
            "persona": s.persona,
            "ticket": s.pending_ticket,
        }

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return {
                "mode": self.mode,
                "auto_shield": self.auto_shield,
                "session_id": self.session.session_id[:8] + "…",
                "messages": [m.to_dict() for m in self.messages],
                "stats": self._stats_unlocked(),
                "events": list(self.events),
                "version": self._version,
            }

    async def next_demo_message(self) -> str | None:
        samples = demo_inbound_messages()
        async with self._lock:
            if self._demo_index >= len(samples):
                return None
            msg = samples[self._demo_index]
            self._demo_index += 1
            return msg
