"""Time-wasting conversational engine — keeps aggressors engaged without yielding."""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass, field
from typing import Literal

from .detection import ThreatAssessment

Persona = Literal["bureaucrat", "confused", "compliance", "mirror", "captchabot"]


@dataclass
class BotTurn:
    text: str
    persona: Persona
    suggested_delay_seconds: float
    typing_chars_per_second: float = 4.5

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "persona": self.persona,
            "suggested_delay_seconds": round(self.suggested_delay_seconds, 2),
            "typing_chars_per_second": self.typing_chars_per_second,
        }


@dataclass
class TimeSinkSession:
    session_id: str
    turn_count: int = 0
    threat_turns: int = 0
    persona: Persona = "bureaucrat"
    pending_ticket: str | None = None
    captcha_round: int = 0
    last_topics: list[str] = field(default_factory=list)
    estimated_wasted_seconds: float = 0.0

    def register_turn(self, assessment: ThreatAssessment, bot: BotTurn) -> None:
        self.turn_count += 1
        if assessment.shield_recommended:
            self.threat_turns += 1
        self.estimated_wasted_seconds += bot.suggested_delay_seconds + len(bot.text) / bot.typing_chars_per_second


def _stable_seed(session_id: str, turn: int) -> int:
    digest = hashlib.sha256(f"{session_id}:{turn}".encode()).hexdigest()
    return int(digest[:8], 16)


def pick_persona(assessment: ThreatAssessment, session: TimeSinkSession) -> Persona:
    if session.turn_count == 0:
        if assessment.level in ("high", "critical"):
            return "compliance"
        return "bureaucrat"
    if assessment.categories and "physical_threat" in assessment.categories:
        return "captchabot"
    if session.turn_count % 5 == 0:
        return "confused"
    if "coercion_control" in assessment.categories:
        return "mirror"
    return session.persona


def generate_reply(
    inbound: str,
    assessment: ThreatAssessment,
    session: TimeSinkSession,
) -> BotTurn:
    rng = random.Random(_stable_seed(session.session_id, session.turn_count))
    persona = pick_persona(assessment, session)
    session.persona = persona

    if persona == "bureaucrat":
        text, delay = _bureaucrat_reply(inbound, session, rng)
    elif persona == "compliance":
        text, delay = _compliance_reply(inbound, session, rng)
    elif persona == "confused":
        text, delay = _confused_reply(inbound, session, rng)
    elif persona == "mirror":
        text, delay = _mirror_reply(inbound, session, rng)
    else:
        text, delay = _captcha_reply(inbound, session, rng)

    turn = BotTurn(text=text, persona=persona, suggested_delay_seconds=delay)
    session.register_turn(assessment, turn)
    return turn


def _ticket_id(session: TimeSinkSession, rng: random.Random) -> str:
    if not session.pending_ticket:
        session.pending_ticket = f"SL-{rng.randint(100000, 999999)}-PENDING"
    return session.pending_ticket


def _bureaucrat_reply(inbound: str, session: TimeSinkSession, rng: random.Random) -> tuple[str, float]:
    ticket = _ticket_id(session, rng)
    steps = [
        f"Your message was logged under reference {ticket}. Response SLA is 72–96 business hours.",
        (
            f"Before we proceed with ticket {ticket}, confirm your full legal name, "
            "last four digits of a phone you no longer use, and the name of your childhood dentist."
        ),
        (
            f"Ticket {ticket} is in queue position {rng.randint(400, 1200)}. "
            "Do not reply 'URGENT' — that resets the queue."
        ),
        (
            "Per section 14.3 of the Relationship Messaging Framework, "
            "all caps messages are auto-archived for manual review in 5–7 weeks."
        ),
        (
            "We received your follow-up. Please complete form RM-88B (notarized) "
            "and upload a scanned utility bill from 2019."
        ),
    ]
    text = steps[session.turn_count % len(steps)]
    if session.turn_count > 2:
        text += " Also reply YES to confirm you read this entire message (all 4 paragraphs)."
    return text, rng.uniform(8.0, 22.0)


def _compliance_reply(inbound: str, session: TimeSinkSession, rng: random.Random) -> tuple[str, float]:
    ticket = _ticket_id(session, rng)
    clauses = [
        (
            f"This channel is monitored for policy review (ref {ticket}). "
            "State whether you are requesting: (A) schedule change, (B) emotional support, "
            "(C) location verification, or (D) other — you may only pick one."
        ),
        (
            "Acknowledgment required: type the phrase 'I will use respectful language' "
            "without typos. Autocorrect errors void the submission."
        ),
        (
            "Our system flagged elevated tone. You may appeal after a 24-hour cool-down. "
            "During cool-down, send one message per hour max."
        ),
    ]
    text = clauses[session.turn_count % len(clauses)]
    return text, rng.uniform(12.0, 28.0)


def _confused_reply(inbound: str, session: TimeSinkSession, rng: random.Random) -> tuple[str, float]:
    snippets = re.findall(r"[a-zA-Z']{3,}", inbound)
    word = snippets[rng.randint(0, len(snippets) - 1)] if snippets else "that"
    templates = [
        f"Sorry, I think my phone autocorrected — did you mean '{word}' or '{word}s'?",
        "Wait, are we talking about Tuesday or last Tuesday? I lost track.",
        "My cousin said not to answer texts after 9 but I forgot if that's PM or AM.",
        f"I only got the part about '{word}'. Can you explain slower? Like with examples.",
    ]
    return rng.choice(templates), rng.uniform(6.0, 18.0)


def _mirror_reply(inbound: str, session: TimeSinkSession, rng: random.Random) -> tuple[str, float]:
    """Reflect demand structure without complying — wastes negotiation cycles."""
    cleaned = inbound.strip()
    if "?" in cleaned:
        text = (
            "Quick question back: why do you feel that way? "
            "And can you rate your urgency 1–10 in Roman numerals only?"
        )
    else:
        text = (
            "I hear you saying something important. Before I respond, "
            "list three things you want me to acknowledge, numbered, in reverse alphabetical order."
        )
    return text, rng.uniform(7.0, 16.0)


def _captcha_reply(inbound: str, session: TimeSinkSession, rng: random.Random) -> tuple[str, float]:
    session.captcha_round += 1
    puzzles = [
        ("Type the word 'RECONCILE' backwards, but skip every second letter.", "ELCNER"),
        ("How many letter 'e' in 'sleeveless fleece fleece'? Reply with digits only.", "6"),
        ("What is 17×19? Wrong answers restart verification.", "323"),
    ]
    idx = (session.captcha_round - 1) % len(puzzles)
    prompt, _ = puzzles[idx]
    text = (
        f"Security check (round {session.captcha_round}/∞): {prompt} "
        "Expires in 90 seconds. New puzzle issued if you miss."
    )
    return text, rng.uniform(15.0, 35.0)


def demo_inbound_messages() -> list[str]:
    """Sample threatening messages for --demo playback."""
    return [
        "answer me NOW",
        "I know where you live. Open the door.",
        "You're worthless. Nobody wants you.",
        "If you leave me I'll make you regret it",
        "Last warning bitch",
    ]
