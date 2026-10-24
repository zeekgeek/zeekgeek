"""SkyVeil: a public-ADS-B flight anomaly radar.

Polls the free adsb.lol aggregator for a region's live air traffic plus its
global "flagged" feeds (declared emergencies, Privacy ICAO Address, LADD,
military) and scores every tracked flight for signs of an emergency, a
likely experimental/test flight, a cloaked or mislabeled broadcast, or
erratic flight-path kinematics.
"""

from __future__ import annotations
