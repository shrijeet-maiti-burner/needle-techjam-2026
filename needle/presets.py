from __future__ import annotations

from types import MappingProxyType
from typing import Final, Mapping


# Every value here was selected on measured arms. The arms, their scores, the
# pins they were run against, and the dates live in docs/evidence/, which is the
# single source of truth for those numbers; they are deliberately not repeated
# here, where nothing would notice them going stale.
#
# - the primary selection, including `category_strength`, is in
#   FINAL_SELECTION_20260830.md
# - `override_policy` and `exclude_seen` are in EXP_006_008_018.md
# - `popularity_strength` has an open review in EXP_006_SHAPES.md: it is the one
#   value here whose disjoint-set evidence disagrees with its released-set
#   evidence, and the review recommends lowering it. Do not tune it against the
#   released set alone.
PRIMARY_AGENT_KWARGS: Final[Mapping[str, object]] = MappingProxyType(
    {
        "retrieval_mode": "signature_first",
        "signature_bucket_limit": 100,
        "popularity_strength": 0.30,
        "category_strength": 1.00,
        "exclude_seen": True,
        "override_policy": "retract_stated",
        "lexical_mode": "none",
        "slate_size": 10,
    }
)

# The packaging and robustness rollback: pure sparse retrieval with the same
# safe state handling and priors. It exists to be the known-good fallback, so
# changes to the primary do not belong here without their own measurement
# against `retrieval_mode="sparse"`.
ROLLBACK_AGENT_KWARGS: Final[Mapping[str, object]] = MappingProxyType(
    {
        "retrieval_mode": "sparse",
        "popularity_strength": 0.30,
        "category_strength": 1.00,
        "exclude_seen": True,
        "override_policy": "retract_stated",
        "lexical_mode": "none",
        "slate_size": 10,
    }
)
