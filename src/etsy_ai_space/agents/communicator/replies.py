"""Communicator agent — future: draft Etsy/TikTok replies (human send required)."""

from __future__ import annotations


def draft_reply(message: str, *, tone: str = "helpful") -> str:
    """Template reply drafts until OAuth messaging is wired."""
    return (
        f"Thanks for reaching out! ({tone}) "
        f"We'll check on: {message.strip()[:120]} — expect a follow-up within one business day."
    )
