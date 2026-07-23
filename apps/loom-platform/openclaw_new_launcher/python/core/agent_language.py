from __future__ import annotations

from collections.abc import Sequence


_NEGATION_MARKERS = (
    "不要",
    "不需要",
    "无需",
    "不用",
    "不必",
    "别",
    "禁止",
    "避免",
    "请勿",
    "勿",
)
_NEGATION_BOUNDARIES = (
    "\n",
    "，",
    ",",
    "。",
    ".",
    "；",
    ";",
    "！",
    "!",
    "？",
    "?",
    "但是",
    "不过",
    "而是",
    "但",
    "而",
    "只",
)
_NEGATION_LOOKBACK = 24


def has_positive_term(text: str, terms: Sequence[str]) -> bool:
    for term in terms:
        if not term:
            continue
        start = 0
        while True:
            index = text.find(term, start)
            if index < 0:
                break
            if not is_negated_occurrence(text, index):
                return True
            start = index + max(1, len(term))
    return False


def is_negated_occurrence(text: str, index: int) -> bool:
    context = text[max(0, index - _NEGATION_LOOKBACK):index]
    boundary_end = 0
    for boundary in _NEGATION_BOUNDARIES:
        boundary_index = context.rfind(boundary)
        if boundary_index >= 0:
            boundary_end = max(boundary_end, boundary_index + len(boundary))
    scope = context[boundary_end:]
    return any(marker in scope for marker in _NEGATION_MARKERS)
