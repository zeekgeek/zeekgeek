"""Private-jet movement radar.

Watches ADS-B traffic for business jets, learns a historical baseline of how
many are airborne, and sounds an alarm when movement triggers pile up faster
than history says they should — a hint that a strange event is taking place.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
