"""Batch LLM enrichment script for uncategorized domains.

Run by maintainers after list import to generate owner, purpose_plain,
privacy_note, and suggestion for domains not covered by curated lists.

Usage:
    python -m vexilla.kb.build.enrich <input.json> <output.json>

Where input.json is a list of domains to enrich, and output.json
is the enriched result with LLM-generated fields.

This script prints the prompt template and expected output format.
It does NOT call an LLM — the maintainer pipes the output to an LLM.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CATEGORIES = [
    "essential", "os_update", "cdn", "cloud_infra",
    "advertising", "tracker_analytics", "telemetry",
    "social", "media_streaming", "messaging", "unrecognized",
]

CATEGORY_DESCRIPTIONS = {
    "essential": "Core internet services (search, email, maps, cloud storage)",
    "os_update": "Operating system updates, package repositories, app stores",
    "cdn": "Content delivery networks serving static assets",
    "cloud_infra": "Cloud computing infrastructure and hosting",
    "advertising": "Ad serving, ad exchanges, retargeting, ad measurement",
    "tracker_analytics": "Web analytics, user tracking, session recording, error monitoring",
    "telemetry": "Usage telemetry, crash reporting, update checks",
    "social": "Social media platforms and social widgets",
    "media_streaming": "Video, audio, and media streaming services",
    "messaging": "Instant messaging, video calls, team communication",
    "unrecognized": "Unknown or uncategorized service — use only when certain",
}


def make_enrichment_batch(domains: list[str]) -> dict:
    """Create the batch input for LLM enrichment.

    Returns a dict with the prompt and domain list.
    """
    return {
        "system_prompt": (
            "You are a domain categorization expert. For each domain, "
            "determine its category, owner, and write a one-sentence "
            "plain-language explanation of what the service does. "
            "Output valid JSON."
        ),
        "instruction": (
            f"Classify each domain into one of these categories:\n"
            + "\n".join(f"  {c}: {CATEGORY_DESCRIPTIONS[c]}" for c in CATEGORIES)
            + "\n\n"
            "For each domain, output a JSON object with the following fields:\n"
            "  domain: the domain name\n"
            "  owner: the company or organization that owns it\n"
            "  category: one of the categories above\n"
            "  purpose_plain: one plain sentence explaining what it's for\n"
            "  privacy_note: one sentence on privacy impact (optional, blank if none)\n"
            "  suggestion: safe, actionable suggestion (optional, blank if none)\n"
            "  confidence: high, medium, or low\n\n"
            "Respond with a JSON array only. No markdown, no explanation."
        ),
        "domains": domains[:500],  # batch size
    }


def read_domains_from_input(path: Path) -> list[str]:
    """Read domains from JSON or plain text file.

    JSON: [{"domain": "example.com"}, ...] or ["example.com", ...]
    Text: one domain per line, # comments skipped.
    """
    try:
        text = path.read_text().strip()
    except FileNotFoundError:
        logger.warning("File not found: %s", path)
        return []

    if text.startswith("["):
        data = json.loads(text)
        if isinstance(data, list):
            return [d if isinstance(d, str) else d.get("domain", "") for d in data]
        return []

    # Plain text — one domain per line
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def write_enrichment_batch(
    domains: list[str],
    output: Path,
) -> None:
    """Write the batch prompt to a file for LLM processing."""
    batch = make_enrichment_batch(domains)
    output.write_text(json.dumps(batch, indent=2))
    logger.info(
        "Wrote enrichment batch for %d domains to %s",
        len(domains), output,
    )


# Entry point
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python -m vexilla.kb.build.enrich <input.txt> [output.json]")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("enrichment_batch.json")

    domains = read_domains_from_input(input_path)
    if not domains:
        print("No domains found in input.")
        sys.exit(1)

    write_enrichment_batch(domains, output_path)
    print(f"\nTo enrich with an LLM, pipe {output_path} to your model.")
    print("Then merge the LLM response back into the pipeline.")
