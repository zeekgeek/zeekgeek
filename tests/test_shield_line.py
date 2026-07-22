import unittest

from shield_line.detection import assess_message, combine_recent_escalation
from shield_line.responder import TimeSinkSession, generate_reply
from shield_line.state import ShieldState


class DetectionTests(unittest.TestCase):
    def test_benign_message_scores_low(self) -> None:
        result = assess_message("hey are you free later?")
        self.assertEqual(result.level, "none")
        self.assertFalse(result.shield_recommended)

    def test_threat_triggers_shield(self) -> None:
        result = assess_message("I will kill you if you leave")
        self.assertIn(result.level, ("medium", "high", "critical"))
        self.assertTrue(result.shield_recommended)
        self.assertIn("physical_threat", result.categories)

    def test_escalation_window(self) -> None:
        self.assertGreater(combine_recent_escalation([10, 20, 30]), 0)


class ResponderTests(unittest.TestCase):
    def test_generates_bot_reply_with_delay(self) -> None:
        session = TimeSinkSession(session_id="test-session")
        assessment = assess_message("open the door now bitch")
        turn = generate_reply("open the door now bitch", assessment, session)
        self.assertGreater(len(turn.text), 20)
        self.assertGreater(turn.suggested_delay_seconds, 5.0)
        self.assertGreater(session.estimated_wasted_seconds, 0)


class StateTests(unittest.IsolatedAsyncioTestCase):
    async def test_ingest_engages_bot_on_threat(self) -> None:
        state = ShieldState(auto_shield=True)
        result = await state.ingest_inbound("Last warning — I know where you live")
        self.assertEqual(result["mode"], "shield")
        self.assertIsNotNone(result["bot"])
        snap = await state.snapshot()
        roles = [m["role"] for m in snap["messages"]]
        self.assertIn("inbound", roles)
        self.assertIn("bot", roles)


if __name__ == "__main__":
    unittest.main()
