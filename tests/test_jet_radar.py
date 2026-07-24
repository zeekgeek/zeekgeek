"""Unit tests for jet_radar anomaly detection and state."""

from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta

from jet_radar.anomaly import (
    MovementBaseline,
    StrangeEventAlarm,
    TrackSnapshot,
    classify_maneuver,
    evaluate_triggers,
    find_tanker_rendezvous,
    movement_posture,
)
from jet_radar.state import JetObservation, RadarState
from jet_radar.watchlist import match_watchlist, nearest_privacy_destination


def _obs(
    hex_id: str,
    *,
    callsign: str | None = "TEST1",
    registration: str | None = None,
    lat: float = 40.0,
    lon: float = -74.0,
    alt: int | None = 40000,
    gs: float = 450.0,
    track: float = 90.0,
    squawk: str = "2000",
    on_ground: bool = False,
    is_tanker: bool = False,
    when: datetime | None = None,
    type_code: str = "GLF6",
) -> JetObservation:
    return JetObservation(
        hex_id=hex_id,
        callsign=callsign,
        registration=registration,
        type_code=type_code,
        lat=lat,
        lon=lon,
        altitude_ft=alt,
        ground_speed_kt=gs,
        track_deg=track,
        squawk=squawk,
        on_ground=on_ground,
        is_tanker=is_tanker,
        observed_at=when or datetime.now(UTC),
    )


class WatchlistTests(unittest.TestCase):
    def test_match_known_registration(self) -> None:
        hit = match_watchlist("N628TS")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertIn("Musk", hit.label)
        self.assertEqual(hit.movement_style, "reactive")

    def test_kauai_privacy_destination(self) -> None:
        match = nearest_privacy_destination(22.10, -159.52)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match[0].code, "kauai")


class AnomalyTests(unittest.TestCase):
    def test_baseline_scores_after_warmup(self) -> None:
        baseline = MovementBaseline(window=50, min_samples=5)
        for _ in range(5):
            baseline.record(10, 1)
        airborne_z, dep_z = baseline.score(25, 8)
        self.assertIsNotNone(airborne_z)
        assert airborne_z is not None
        self.assertGreater(airborne_z, 3.0)

    def test_high_speed_maneuver(self) -> None:
        track = TrackSnapshot(
            hex_id="abc",
            identity="N1",
            registration="N1",
            lat=40.0,
            lon=-74.0,
            altitude_ft=40000,
            ground_speed_kt=620.0,
            track_deg=90.0,
            previous_track_deg=20.0,
            previous_altitude_ft=40000,
            cycle_seconds=60.0,
            watched_label=None,
            movement_style=None,
            just_became_airborne=False,
            just_went_quiet=False,
        )
        trigger = classify_maneuver(track)
        self.assertIsNotNone(trigger)
        assert trigger is not None
        self.assertEqual(trigger.code, "high-speed-maneuver")

    def test_tanker_rendezvous(self) -> None:
        jet = TrackSnapshot(
            hex_id="jet1",
            identity="N9",
            registration="N9",
            lat=40.0,
            lon=-74.0,
            altitude_ft=30000,
            ground_speed_kt=440.0,
            track_deg=90.0,
            previous_track_deg=90.0,
            previous_altitude_ft=30000,
            cycle_seconds=60.0,
            watched_label=None,
            movement_style=None,
            just_became_airborne=False,
            just_went_quiet=False,
            is_tanker=False,
        )
        tanker = TrackSnapshot(
            hex_id="tank1",
            identity="ROCC01",
            registration="60-0001",
            lat=40.05,
            lon=-74.05,
            altitude_ft=30500,
            ground_speed_kt=420.0,
            track_deg=90.0,
            previous_track_deg=90.0,
            previous_altitude_ft=30500,
            cycle_seconds=60.0,
            watched_label=None,
            movement_style=None,
            just_became_airborne=False,
            just_went_quiet=False,
            is_tanker=True,
        )
        triggers = find_tanker_rendezvous([jet, tanker])
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].code, "tanker-rendezvous")

    def test_watchlist_scramble_trigger(self) -> None:
        tracks = [
            TrackSnapshot(
                hex_id="a",
                identity="N628TS [Elon]",
                registration="N628TS",
                lat=30.0,
                lon=-97.0,
                altitude_ft=5000,
                ground_speed_kt=300.0,
                track_deg=90.0,
                previous_track_deg=90.0,
                previous_altitude_ft=0,
                cycle_seconds=60.0,
                watched_label="Elon Musk (reported)",
                movement_style="reactive",
                just_became_airborne=True,
                just_went_quiet=False,
            ),
            TrackSnapshot(
                hex_id="b",
                identity="N194WM [Gates]",
                registration="N194WM",
                lat=47.0,
                lon=-122.0,
                altitude_ft=5000,
                ground_speed_kt=300.0,
                track_deg=90.0,
                previous_track_deg=90.0,
                previous_altitude_ft=0,
                cycle_seconds=60.0,
                watched_label="Bill Gates orbit (reported)",
                movement_style="reactive",
                just_became_airborne=True,
                just_went_quiet=False,
            ),
        ]
        triggers = evaluate_triggers(
            airborne=2,
            new_airborne=2,
            airborne_z=None,
            departures_z=None,
            emergency_squawks=[],
            dark_flights=0,
            sigma=3.0,
            tracks=tracks,
        )
        codes = {t.code for t in triggers}
        self.assertIn("watchlist-scramble", codes)

    def test_movement_posture(self) -> None:
        self.assertEqual(movement_posture([False] * 12), "sitting-still")
        self.assertEqual(movement_posture([True] * 12), "on-the-move")
        self.assertEqual(movement_posture([True, False, True, False, True, False]), "staging")

    def test_alarm_fires_and_clears(self) -> None:
        alarm = StrangeEventAlarm(window=4, threshold=3)
        self.assertIsNone(alarm.update(1))
        self.assertIsNone(alarm.update(1))
        self.assertEqual(alarm.update(1), "fired")
        self.assertTrue(alarm.active)
        self.assertIsNone(alarm.update(0))
        # Need the window to drain to zero.
        self.assertIsNone(alarm.update(0))
        self.assertIsNone(alarm.update(0))
        self.assertEqual(alarm.update(0), "cleared")


class StateTests(unittest.TestCase):
    def test_surge_and_strange_event(self) -> None:
        asyncio.run(self._surge_flow())

    async def _surge_flow(self) -> None:
        state = RadarState(stale_after=30, sigma=2.5, trigger_threshold=2, min_baseline_samples=5, cycle_seconds=60)
        now = datetime.now(UTC)
        # Warm baseline with a stable fleet of 4.
        for cycle in range(6):
            when = now + timedelta(seconds=cycle * 60)
            fleet = [_obs(f"base{i}", when=when, lat=40 + i * 0.1) for i in range(4)]
            await state.ingest_cycle(fleet)

        # Surge: many new jets + emergency.
        when = now + timedelta(seconds=600)
        fleet = [_obs(f"base{i}", when=when) for i in range(4)]
        fleet.extend([_obs(f"new{i}", when=when, callsign=None, lat=41 + i * 0.1) for i in range(8)])
        fleet[0] = _obs("base0", when=when, squawk="7700")
        events = await state.ingest_cycle(fleet)
        types = {e["type"] for e in events}
        self.assertTrue(any(t.startswith("trigger:") for t in types))
        snapshot = await state.snapshot()
        self.assertGreaterEqual(snapshot["airborne_count"], 10)

    def test_watchlist_and_privacy_landing(self) -> None:
        asyncio.run(self._privacy_flow())

    async def _privacy_flow(self) -> None:
        state = RadarState(stale_after=1.0, sigma=3.0, trigger_threshold=3, min_baseline_samples=20, cycle_seconds=1.0)
        now = datetime.now(UTC)
        # Watched privacy-heavy jet near Kauai.
        await state.ingest_cycle(
            [
                _obs(
                    "adzuck",
                    callsign="N688ZS",
                    registration="N688ZS",
                    lat=22.10,
                    lon=-159.52,
                    alt=2000,
                    when=now,
                )
            ]
        )
        snapshot = await state.snapshot()
        self.assertEqual(snapshot["watched_count"], 1)
        self.assertIn("Zuckerberg", snapshot["jets"][0]["watched_label"])

        # Age it out so it goes quiet near Kauai.
        await asyncio.sleep(1.1)
        events = await state.ingest_cycle([])
        types = {e["type"] for e in events}
        self.assertIn("left", types)
        self.assertIn("trigger:privacy-landing", types)
        snapshot = await state.snapshot()
        self.assertTrue(any("Kauai" in h["name"] for h in snapshot["hideout_candidates"]))

    def test_reactive_scramble_in_state(self) -> None:
        asyncio.run(self._scramble_flow())

    async def _scramble_flow(self) -> None:
        state = RadarState(stale_after=30, min_baseline_samples=50, cycle_seconds=60)
        now = datetime.now(UTC)
        # Sitting still on the ground.
        await state.ingest_cycle(
            [
                _obs("admusk", callsign="N628TS", registration="N628TS", on_ground=True, alt=None, when=now),
                _obs("adgate", callsign="N194WM", registration="N194WM", on_ground=True, alt=None, when=now),
            ]
        )
        snap = await state.snapshot()
        postures = {j["hex"]: j["posture"] for j in snap["jets"]}
        self.assertEqual(postures["admusk"], "sitting-still")

        later = now + timedelta(seconds=60)
        events = await state.ingest_cycle(
            [
                _obs("admusk", callsign="N628TS", registration="N628TS", alt=5000, when=later),
                _obs("adgate", callsign="N194WM", registration="N194WM", alt=5000, when=later),
            ]
        )
        codes = {e["type"] for e in events}
        self.assertIn("trigger:watchlist-scramble", codes)


class WebRouteTests(unittest.TestCase):
    def test_routes_exist(self) -> None:
        from fastapi.routing import APIRoute

        from jet_radar.web import create_app

        app = create_app(RadarState())
        paths = {(route.path, tuple(sorted(route.methods or []))) for route in app.routes if isinstance(route, APIRoute)}
        self.assertIn(("/api/jets", ("GET",)), paths)
        self.assertIn(("/api/events", ("GET",)), paths)
        self.assertIn(("/api/sensitivity", ("POST",)), paths)

    def test_stream_snapshot_is_smaller_than_full(self) -> None:
        asyncio.run(self._stream_size_flow())

    async def _stream_size_flow(self) -> None:
        state = RadarState(stale_after=30, min_baseline_samples=1, cycle_seconds=60)
        now = datetime.now(UTC)
        await state.ingest_cycle(
            [
                JetObservation(
                    hex_id=f"ad{i:04d}",
                    callsign=f"N{i:04d}",
                    lat=40.0 + i * 0.01,
                    lon=-74.0,
                    altitude_ft=40000,
                    observed_at=now,
                )
                for i in range(40)
            ]
        )
        full = await state.snapshot(stream=False)
        stream = await state.snapshot(stream=True)
        self.assertEqual(len(stream["jets"]), len(full["jets"]))
        self.assertNotIn("altitude_history", stream["jets"][0])
        self.assertIn("altitude_history", full["jets"][0])


if __name__ == "__main__":
    unittest.main()
