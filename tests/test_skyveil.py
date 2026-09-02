"""Unit tests for SkyVeil anomaly detection and state."""

from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta

from skyveil.anomaly import FlightSnapshot, evaluate_flight, score_triggers
from skyveil.reference import hex_nation, registration_nation
from skyveil.scanner import parse_aircraft
from skyveil.state import FlightObservation, SkyState


def _snap(
    hex_id: str = "abc123",
    *,
    callsign: str | None = "N1AB",
    registration: str | None = "N1AB",
    type_code: str | None = "C172",
    emitter_category: str | None = "A1",
    lat: float | None = 40.0,
    lon: float | None = -74.0,
    altitude_ft: int | None = 5000,
    ground_speed_kt: float | None = 140.0,
    track_deg: float | None = 90.0,
    baro_rate_fpm: float | None = 0.0,
    squawk: str | None = "1200",
    emergency_field: str | None = None,
    nic: int | None = 8,
    nac_p: int | None = 9,
    on_ground: bool = False,
    is_pia: bool = False,
    is_ladd: bool = False,
    is_mil: bool = False,
    previous_track_deg: float | None = 90.0,
    previous_lat: float | None = 40.0,
    previous_lon: float | None = -74.0,
    previous_registration: str | None = None,
    previous_type_code: str | None = None,
    seconds_since_previous: float | None = 20.0,
    recent_headings: list[float] | None = None,
    recent_positions: list[tuple[float, float]] | None = None,
) -> FlightSnapshot:
    return FlightSnapshot(
        hex_id=hex_id,
        identity=callsign or registration or hex_id,
        callsign=callsign,
        registration=registration,
        type_code=type_code,
        emitter_category=emitter_category,
        lat=lat,
        lon=lon,
        altitude_ft=altitude_ft,
        ground_speed_kt=ground_speed_kt,
        track_deg=track_deg,
        baro_rate_fpm=baro_rate_fpm,
        squawk=squawk,
        emergency_field=emergency_field,
        nic=nic,
        nac_p=nac_p,
        on_ground=on_ground,
        is_pia=is_pia,
        is_ladd=is_ladd,
        is_mil=is_mil,
        previous_track_deg=previous_track_deg,
        previous_lat=previous_lat,
        previous_lon=previous_lon,
        previous_registration=previous_registration,
        previous_type_code=previous_type_code,
        seconds_since_previous=seconds_since_previous,
        recent_headings=recent_headings or [],
        recent_positions=recent_positions or [],
    )


class ReferenceTests(unittest.TestCase):
    def test_hex_nation_lookup(self) -> None:
        self.assertEqual(hex_nation("a12345"), "United States")
        self.assertEqual(hex_nation("400123"), "United Kingdom")
        self.assertIsNone(hex_nation("zzzzzz"))

    def test_registration_nation_lookup(self) -> None:
        self.assertEqual(registration_nation("N123AB"), "United States")
        self.assertEqual(registration_nation("G-ABCD"), "United Kingdom")
        self.assertIsNone(registration_nation(None))

    def test_registration_nation_rejects_non_n_number_shapes(self) -> None:
        # Military serials and placeholder registrations can start with "N"
        # without being a real FAA N-number (which never has a dash).
        self.assertIsNone(registration_nation("N48-018"))


class ScannerTests(unittest.TestCase):
    def test_parse_aircraft_reads_position_age(self) -> None:
        entry = {"hex": "abc123", "flight": "UAL1", "lat": 40.0, "lon": -74.0, "seen_pos": 0.42}
        obs = parse_aircraft(entry, datetime.now(UTC))
        self.assertEqual(obs.position_age_s, 0.42)

    def test_parse_aircraft_missing_position_age(self) -> None:
        entry = {"hex": "abc123", "flight": "UAL1", "lat": 40.0, "lon": -74.0}
        obs = parse_aircraft(entry, datetime.now(UTC))
        self.assertIsNone(obs.position_age_s)


class AnomalyTests(unittest.TestCase):
    def test_emergency_squawk_and_field(self) -> None:
        flight = _snap(squawk="7700", emergency_field="general")
        triggers = evaluate_flight(flight)
        codes = {t.code for t in triggers}
        self.assertIn("emergency-squawk", codes)
        self.assertIn("emergency-declared", codes)
        score, category = score_triggers(triggers)
        self.assertEqual(category, "emergency")
        self.assertGreaterEqual(score, 95.0)

    def test_no_anomalies_for_routine_flight(self) -> None:
        flight = _snap()
        triggers = evaluate_flight(flight)
        self.assertEqual(triggers, [])
        score, category = score_triggers(triggers)
        self.assertEqual(score, 0.0)
        self.assertIsNone(category)

    def test_extreme_altitude_flags_but_implausible_altitude_does_not(self) -> None:
        # A genuinely high (if rare) altitude is a lead; a six-digit
        # altitude is Mode-S/Gillham decode noise on a weak contact, not a
        # real flight, and must not be reported as one.
        believable = _snap(altitude_ft=55000)
        self.assertIn("extreme-altitude", {t.code for t in evaluate_flight(believable)})
        garbage = _snap(altitude_ft=103700)
        self.assertNotIn("extreme-altitude", {t.code for t in evaluate_flight(garbage)})

    def test_test_callsign_and_range_flags_experimental(self) -> None:
        flight = _snap(
            callsign="XPRMT12",
            registration="N912TX",
            type_code=None,
            emitter_category="B7",
            lat=34.9054,
            lon=-117.8837,
            altitude_ft=52000,
            previous_lat=34.9054,
            previous_lon=-117.8837,
            recent_headings=[0.0, 90.0, 180.0, 270.0, 15.0, 195.0],
            recent_positions=[(34.9054, -117.8837)] * 6,
        )
        triggers = evaluate_flight(flight)
        codes = {t.code for t in triggers}
        self.assertIn("test-callsign", codes)
        self.assertIn("unusual-emitter-category", codes)
        self.assertIn("extreme-altitude", codes)
        self.assertIn("test-range-presence", codes)
        _, category = score_triggers(triggers)
        self.assertEqual(category, "experimental")

    def test_pia_flags_cloaked(self) -> None:
        flight = _snap(is_pia=True, nic=0)
        triggers = evaluate_flight(flight)
        codes = {t.code for t in triggers}
        self.assertIn("privacy-icao-address", codes)
        self.assertIn("degraded-position-integrity", codes)
        _, category = score_triggers(triggers)
        self.assertEqual(category, "cloaked")

    def test_identity_churn_flags_cloaked(self) -> None:
        flight = _snap(registration="N999ZZ", previous_registration="N111AA")
        triggers = evaluate_flight(flight)
        codes = {t.code for t in triggers}
        self.assertIn("identity-churn", codes)

    def test_hex_nation_mismatch(self) -> None:
        flight = _snap(hex_id="400abc", registration="N555XY")
        triggers = evaluate_flight(flight)
        codes = {t.code for t in triggers}
        self.assertIn("hex-nation-mismatch", codes)

    def test_extreme_vertical_rate_and_overspeed(self) -> None:
        # A7 = rotorcraft, one of the few categories with a real speed cap.
        flight = _snap(baro_rate_fpm=-7200.0, ground_speed_kt=260.0, emitter_category="A7")
        triggers = evaluate_flight(flight)
        codes = {t.code for t in triggers}
        self.assertIn("extreme-vertical-rate", codes)
        self.assertIn("overspeed-for-category", codes)
        _, category = score_triggers(triggers)
        self.assertEqual(category, "erratic")

    def test_hard_turn(self) -> None:
        flight = _snap(track_deg=200.0, previous_track_deg=90.0, ground_speed_kt=250.0)
        triggers = evaluate_flight(flight)
        codes = {t.code for t in triggers}
        self.assertIn("hard-turn", codes)

    def test_position_discontinuity(self) -> None:
        flight = _snap(
            lat=41.0, lon=-73.0, previous_lat=40.0, previous_lon=-74.0,
            ground_speed_kt=100.0, seconds_since_previous=10.0,
        )
        triggers = evaluate_flight(flight)
        codes = {t.code for t in triggers}
        self.assertIn("position-discontinuity", codes)

    def test_position_discontinuity_skipped_when_speed_unreported(self) -> None:
        # A missing "gs" (common on MLAT-tracked traffic) is unknown speed,
        # not confirmed-stationary — must not be treated as a 0kt baseline.
        flight = _snap(
            lat=41.0, lon=-73.0, previous_lat=40.0, previous_lon=-74.0,
            ground_speed_kt=None, seconds_since_previous=10.0,
        )
        triggers = evaluate_flight(flight)
        codes = {t.code for t in triggers}
        self.assertNotIn("position-discontinuity", codes)

    def test_sustained_loiter(self) -> None:
        headings = [0.0, 90.0, 180.0, 270.0, 40.0, 200.0]
        positions = [(40.0, -74.0)] * 6
        flight = _snap(recent_headings=headings, recent_positions=positions)
        triggers = evaluate_flight(flight)
        codes = {t.code for t in triggers}
        self.assertIn("sustained-loiter", codes)

    def test_score_diminishing_returns_caps_at_100(self) -> None:
        flight = _snap(squawk="7700", emergency_field="general", is_pia=True, nic=0)
        triggers = evaluate_flight(flight)
        score, _ = score_triggers(triggers)
        self.assertLessEqual(score, 100.0)


class StateTests(unittest.TestCase):
    def test_ingest_and_snapshot_flow(self) -> None:
        asyncio.run(self._flow())

    async def _flow(self) -> None:
        state = SkyState(stale_after=30, detection_threshold=30.0)
        now = datetime.now(UTC)
        routine = FlightObservation(
            hex_id="rout01", callsign="UAL1", registration="N1UA", type_code="B738",
            emitter_category="A3", lat=40.0, lon=-74.0, altitude_ft=35000,
            ground_speed_kt=450.0, track_deg=90.0, squawk="2200", observed_at=now,
        )
        emergency = FlightObservation(
            hex_id="emerg01", callsign="DAL9", registration="N9DL", type_code="A321",
            emitter_category="A3", lat=41.0, lon=-75.0, altitude_ft=30000,
            ground_speed_kt=420.0, track_deg=90.0, squawk="7700", emergency_field="general",
            observed_at=now,
        )
        events = await state.ingest_cycle([routine, emergency])
        types = {e["type"] for e in events}
        self.assertTrue(any(t.startswith("detection-opened:emergency") for t in types))

        snapshot = await state.snapshot()
        self.assertEqual(snapshot["tracked_count"], 2)
        self.assertEqual(snapshot["detection_count"], 1)
        self.assertEqual(snapshot["detections"][0]["hex"], "emerg01")
        self.assertEqual(snapshot["category_counts"]["emergency"], 1)

        # Emergency resolves (squawk back to normal, no more declared emergency).
        later = now + timedelta(seconds=60)
        cleared = FlightObservation(
            hex_id="emerg01", callsign="DAL9", registration="N9DL", type_code="A321",
            emitter_category="A3", lat=41.05, lon=-75.05, altitude_ft=30000,
            ground_speed_kt=420.0, track_deg=90.0, squawk="2210", observed_at=later,
        )
        events = await state.ingest_cycle([routine, cleared])
        types = {e["type"] for e in events}
        self.assertIn("detection-cleared", types)
        snapshot = await state.snapshot()
        self.assertEqual(snapshot["detection_count"], 0)

    def test_stale_flight_marked_left_and_cleared(self) -> None:
        asyncio.run(self._stale_flow())

    async def _stale_flow(self) -> None:
        state = SkyState(stale_after=1.0, detection_threshold=30.0)
        now = datetime.now(UTC)
        emergency = FlightObservation(
            hex_id="e1", callsign="N1", squawk="7700", emergency_field="general",
            lat=40.0, lon=-74.0, altitude_ft=10000, ground_speed_kt=200.0, observed_at=now,
        )
        await state.ingest_cycle([emergency])
        await asyncio.sleep(1.1)
        events = await state.ingest_cycle([])
        types = {e["type"] for e in events}
        self.assertIn("detection-cleared", types)


    def test_stale_position_fix_does_not_false_positive_as_a_jump(self) -> None:
        # Two polls ~21s apart by wall clock, but the ADS-B position ages
        # ("seen_pos") show the real gap between fixes was ~31s: the first
        # fix was already 10s stale when polled, the second was fresh. A
        # naive poll-cadence elapsed time would read this as a ~429kt
        # implied jump (false positive); the seen_pos-corrected elapsed
        # time reads it as ~290kt, well within the reported 249kt + slack.
        asyncio.run(self._stale_fix_flow())

    async def _stale_fix_flow(self) -> None:
        state = SkyState(stale_after=60, detection_threshold=30.0)
        now = datetime.now(UTC)
        first = FlightObservation(
            hex_id="mil1", callsign="RCH651", registration=None, type_code="C17",
            lat=40.0, lon=-74.0, altitude_ft=28000, ground_speed_kt=249.0, track_deg=0.0,
            squawk="1200", nic=0, position_age_s=10.0, observed_at=now,
        )
        await state.ingest_cycle([first])
        second = FlightObservation(
            hex_id="mil1", callsign="RCH651", registration=None, type_code="C17",
            lat=40.04167, lon=-74.0, altitude_ft=28000, ground_speed_kt=249.0, track_deg=0.0,
            squawk="1200", nic=0, position_age_s=0.0, observed_at=now + timedelta(seconds=21),
        )
        await state.ingest_cycle([second])
        snapshot = await state.snapshot()
        flight = next(f for f in snapshot["flights"] if f["hex"] == "mil1")
        codes = {t["code"] for t in flight["triggers"]}
        self.assertNotIn("position-discontinuity", codes)


class WebRouteTests(unittest.TestCase):
    def test_routes_exist(self) -> None:
        from fastapi.routing import APIRoute

        from skyveil.web import create_app

        app = create_app(SkyState())
        paths = {(route.path, tuple(sorted(route.methods or []))) for route in app.routes if isinstance(route, APIRoute)}
        self.assertIn(("/api/flights", ("GET",)), paths)
        self.assertIn(("/api/events", ("GET",)), paths)
        self.assertIn(("/api/reference", ("GET",)), paths)


if __name__ == "__main__":
    unittest.main()
