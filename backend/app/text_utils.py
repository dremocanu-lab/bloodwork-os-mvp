from __future__ import annotations

from typing import Any


def clean_display_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value)

    replacements = {
        "Â·": "·",
        "Â ": " ",
        "Â": "",
        "â€™": "'",
        "â€˜": "'",
        "â€œ": '"',
        "â€�": '"',
        "â€“": "–",
        "â€”": "—",
    }

    for bad, good in replacements.items():
        text = text.replace(bad, good)

    return " ".join(text.split())