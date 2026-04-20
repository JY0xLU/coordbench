from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Iterable


def collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def clean_surface(value: str) -> str:
    value = collapse_whitespace(value)
    value = value.strip(" \t\r\n\"'`[](){}.,;:!?")
    return collapse_whitespace(value)


def ascii_fold(value: str) -> str:
    return (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
    )


def make_match_key(value: str) -> str:
    value = clean_surface(value).lower()
    value = ascii_fold(value)
    return re.sub(r"[^a-z0-9]+", "", value)


def prettify_prompt(value: str) -> str:
    value = clean_surface(value).rstrip(".:")
    if not value:
        return value
    return value[0].upper() + value[1:]


def _looks_like_reasoning_header(value: str) -> bool:
    lowered = clean_surface(value).lower()
    return lowered.startswith(
        (
            "thinking process",
            "reasoning",
            "analysis",
            "<think>",
            "**thinking process",
            "**reasoning",
        )
    )


def extract_first_answer_line(value: str) -> str:
    candidate = value
    think_segments = re.split(r"</think>", candidate, flags=re.IGNORECASE)
    if len(think_segments) > 1:
        candidate = think_segments[-1]

    lines = [clean_surface(line) for line in candidate.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    # Higher priority: search for explicit final answer markers in the full text
    lowered_all = value.lower()
    for marker in ("final answer:", "the most likely answer is:", "\u6700\u7ec8\u7b54\u6848:", "answer:"):
        if marker in lowered_all:
            parts = re.split(re.escape(marker), value, flags=re.IGNORECASE)
            if parts and len(parts) > 1:
                ans = clean_surface(parts[-1].splitlines()[0])
                if ans: return ans

    first = lines[0]
    if _looks_like_reasoning_header(first):
        # Qwen3.5 outputs "Thinking Process:...\n\nAnswer" without </think> tags.
        for line in reversed(lines):
            # Skip empty or headers
            if not line or _looks_like_reasoning_header(line):
                continue
            
            # Skip obvious reasoning meta-talk
            low = line.lower()
            if any(x in low for x in ("wait,", "actually,", "let me re-evaluate", "i will provide", "thinking process")):
                continue

            # Look for bold final answer like **London**
            bold_match = re.search(r"\*\*(.*?)\*\*", line)
            if bold_match:
                return clean_surface(bold_match.group(1))

            # Filter out numbered steps but allow short bold text or plain text
            stripped = line.lstrip()
            if re.match(r"^\d+[\.\)]\s", stripped):
                continue
            if stripped.startswith(("- ", "* ")):
                continue
            
            # Typical answer is short. If it's too long (>100), it might be a sentence summary.
            if len(line) > 100:
                continue

            return line
        return ""
    return first


def choose_representative(surface_forms: Iterable[str]) -> str:
    cleaned = [clean_surface(value) for value in surface_forms if clean_surface(value)]
    if not cleaned:
        return ""
    counts = Counter(cleaned)
    return sorted(counts.items(), key=lambda item: (-item[1], len(item[0]), item[0]))[0][0]
