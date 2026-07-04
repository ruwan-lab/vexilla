"""Plain-language templates for insights and summaries.

All offline/deterministic — no runtime LLM calls.
Each template is a function that fills slots from typed data.
"""

from __future__ import annotations

from typing import Optional

# ── Daily summary skeleton ─────────────────────────────────────────

# Shown on non-empty days


def daily_summary_text(
    app_count: int,
    domain_count: int,
    total_mb: float,
    bg_mb: float,
    top_app_name: Optional[str],
    top_app_mb: float,
    tracker_count: int,
    flag_count: int,
) -> str:
    """Build the plain-language daily summary.

    Decomposes gracefully when any value is zero or missing.
    """
    lines: list[str] = []

    total_str = f"{total_mb:.1f} MB"
    bg_str = f"{bg_mb:.1f} MB"

    if app_count == 0:
        return "Vexilla did not detect any network activity today."

    # Main sentence
    lines.append(
        f"Today your device talked to {domain_count} services across"
        f" {app_count} apps, using {total_str}"
        f" ({bg_str} in the background)."
    )

    # Top app
    if top_app_name and top_app_mb > 0:
        lines.append(
            f"The biggest talker was {top_app_name} with {top_app_mb:.1f} MB."
        )

    # Trackers
    if tracker_count > 0:
        lines.append(
            f"{tracker_count} tracking{'' if tracker_count == 1 else ''}"
            f" or advertising { 'service was' if tracker_count == 1 else 'services were'}"
            f" contacted."
        )

    # Flag count
    if flag_count > 0:
        lines.append(
            f"There {'is' if flag_count == 1 else 'are'} {flag_count}"
            f" flagged item{'' if flag_count == 1 else 's'} to review."
        )

    return " ".join(lines)


def empty_summary_text() -> str:
    return "Vexilla is watching. Come back in a few minutes."
