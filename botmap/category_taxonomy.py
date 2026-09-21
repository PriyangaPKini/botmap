"""Place category vocabularies and near-match lookup for zero-result hints.

Places carry two category vocabularies: the detailed `taxonomy.primary` and
the broader `basic_category`. A value used against the wrong one, or a value
that was renamed, silently returns zero rows. These helpers only word the
hint for that case; fuzzy matching here must never be used to filter rows.
"""

from __future__ import annotations

import difflib
from typing import Iterable, Optional, Set, Tuple

import pyarrow as pa
import pyarrow.compute as pc

CategoryPair = Tuple[Optional[str], Optional[str]]


def category_pairs(batches: Iterable[pa.RecordBatch]) -> Set[CategoryPair]:
    """Collect every distinct `(taxonomy.primary, basic_category)` pair.

    One pass yields both vocabularies and how they relate, so a hint can say
    which `basic_category` a `taxonomy.primary` value sits under. A release
    without `basic_category` pairs each value with None.
    """
    pairs: Set[CategoryPair] = set()
    for batch in batches:
        primaries = pc.struct_field(batch.column("taxonomy"), "primary").to_pylist()
        if "basic_category" in batch.schema.names:
            basics = batch.column("basic_category").to_pylist()
        else:
            basics = [None] * batch.num_rows
        pairs.update(zip(primaries, basics))
    return pairs


def closest_values(target: str, values: Iterable[str], n: int = 3) -> list[str]:
    """Return up to `n` of `values` closest to `target`, best first.

    Ranking is token-aware: `ferry_terminal` should match `ferry_service`
    via the shared "ferry" token, not `cafeteria` via character overlap.
    """
    target_lower = target.lower()
    target_tokens = set(target_lower.replace("_", " ").split())
    matcher = difflib.SequenceMatcher(autojunk=False)
    matcher.set_seq1(target_lower)

    # Inclusion rules (any one passes):
    #   - token overlap >= 1  → "ferry_terminal" ~ "ferry_service"
    #   - substring          → "cafe" ~ "cafeteria"
    #   - ratio >= 0.75      → typo correction ("coffe_shop" ~ "coffee_shop")
    # Anything weaker is noise (e.g. cafeteria ~ ferry_terminal at 0.609).
    scored = []
    for v in values:
        v_lower = v.lower()
        matcher.set_seq2(v_lower)
        ratio = matcher.ratio()
        v_tokens = set(v_lower.replace("_", " ").split())
        token_overlap = len(target_tokens & v_tokens)
        substring_hit = int(target_lower in v_lower or v_lower in target_lower)
        if token_overlap or substring_hit or ratio >= 0.75:
            score = ratio + 0.2 * token_overlap + 0.15 * substring_hit
            scored.append((score, v))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [v for _, v in scored[:n]]
