"""Local AI-style analysis over observed AP/client activity."""

from __future__ import annotations

from collections import Counter


def build_ai_analysis(
    *,
    aps: list[dict],
    clients: list[dict],
    alarm_count: int,
    monitor_mode_enabled: bool,
) -> dict:
    """Generate a concise AI-style assessment of local WiFi activity.

    This is intentionally local and deterministic so it runs offline without
    external services. The output shape is designed for UI rendering and API
    consumption.
    """
    visible_aps = [ap for ap in aps if ap.get("present")]
    visible_clients = [client for client in clients if client.get("present")]
    moving_aps = [ap for ap in visible_aps if ap.get("motion") == "moving"]
    hidden_aps = [ap for ap in visible_aps if not (ap.get("ssid") or "").strip()]
    unassociated_clients = [client for client in visible_clients if not client.get("associated_bssid")]
    probing_clients = [client for client in visible_clients if client.get("probe_count", 0) > 0]

    clients_per_ap = Counter(
        client["associated_bssid"] for client in visible_clients if client.get("associated_bssid")
    )
    busiest_ap = clients_per_ap.most_common(1)

    risk_score = 0
    if alarm_count > 0:
        risk_score += 3
    if len(unassociated_clients) >= 3:
        risk_score += 2
    elif len(unassociated_clients) >= 1:
        risk_score += 1
    if len(hidden_aps) >= 2:
        risk_score += 1
    if len(moving_aps) >= 3:
        risk_score += 1

    if risk_score >= 5:
        risk_level = "high"
    elif risk_score >= 3:
        risk_level = "medium"
    else:
        risk_level = "low"

    highlights: list[str] = [
        f"{len(visible_aps)} APs and {len(visible_clients)} clients currently in range.",
        f"{len(moving_aps)} AP targets show moving RSSI behavior.",
    ]
    if not monitor_mode_enabled:
        highlights.append("Client detection is limited until monitor mode is enabled.")
    else:
        highlights.append(f"{len(probing_clients)} clients are actively probing for SSIDs.")
    if hidden_aps:
        highlights.append(f"{len(hidden_aps)} hidden-SSID APs observed.")
    if busiest_ap:
        bssid, count = busiest_ap[0]
        highlights.append(f"Busiest AP {bssid} has {count} associated clients.")
    if unassociated_clients:
        highlights.append(f"{len(unassociated_clients)} clients have no AP association in captured frames.")

    recommendations: list[str] = []
    if not monitor_mode_enabled:
        recommendations.append("Enable monitor mode to improve client and management-frame visibility.")
    if alarm_count > 0:
        recommendations.append("Investigate alarm-zone devices first; they are physically closest.")
    if unassociated_clients:
        recommendations.append("Watch unassociated probing clients for repeated SSID hunting behavior.")
    if hidden_aps:
        recommendations.append("Validate hidden APs against your known-inventory list.")
    if not recommendations:
        recommendations.append("Network activity appears stable; continue passive monitoring.")

    summary = (
        f"Risk {risk_level.upper()}: {len(visible_aps)} APs, {len(visible_clients)} clients, "
        f"{alarm_count} proximity alarms active."
    )
    return {
        "model": "local-heuristic-v1",
        "risk_level": risk_level,
        "summary": summary,
        "highlights": highlights,
        "recommendations": recommendations,
        "metrics": {
            "visible_aps": len(visible_aps),
            "visible_clients": len(visible_clients),
            "moving_aps": len(moving_aps),
            "hidden_aps": len(hidden_aps),
            "unassociated_clients": len(unassociated_clients),
            "alarm_count": alarm_count,
        },
    }
