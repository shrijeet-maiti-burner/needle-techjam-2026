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
# - `popularity_strength` was the one value here whose disjoint-set evidence
#   disagreed with its released-set evidence (review in EXP_006_SHAPES.md).
#   EXP_022.md retracts the released-set result: the public targets are sampled
#   from the popular tail, so that set cannot judge a popularity prior at all.
#   EXP_023.md then measures the value out of the emission path entirely -- once
#   promotion decides rank one, 0.00, 0.30 and 1.00 are within 0.0014 of each
#   other on the released set and 0.30 is the better of them on the omitted-shape
#   holdout. It stays at 0.30. Do not tune it against the released set alone.
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
        # EXP_023.md. `promote` ranks the disclosed-prefix bucket instead of
        # filtering on it, and serializes one product per turn while the belief
        # state is thin. The scorer freezes a session's rank at first
        # appearance, so a turn costs 0.02 where a rank costs up to 0.15.
        # Measured against the official evaluator: 0.876548 -> 0.979600 on the
        # released set, hit rate 1.0000, MRR 1.000000, MTTC 2.020, and positive
        # on the omitted-shape holdout and four 600-session controls.
        # `emission_mode="slate"` restores the previous behaviour exactly.
        "emission_mode": "promote",
        "release_turn": 8,
    }
)

# The packaging and robustness rollback: pure sparse retrieval, full slates, the
# same safe state handling and priors. It exists to be the known-good fallback,
# so changes to the primary do not belong here without their own measurement
# against `retrieval_mode="sparse"`.
#
# It deliberately keeps `emission_mode="slate"`. Promotion is measured positive
# on all six sets, but it reads the released protocol's own construction closely
# (EXP_023.md, "Transfer risk"), and the point of a rollback is to be the
# configuration that assumes least. Switching the primary back to `"slate"` is
# the one-value revert; this is the two-value one.
ROLLBACK_AGENT_KWARGS: Final[Mapping[str, object]] = MappingProxyType(
    {
        "retrieval_mode": "sparse",
        "popularity_strength": 0.30,
        "category_strength": 1.00,
        "exclude_seen": True,
        "override_policy": "retract_stated",
        "lexical_mode": "none",
        "slate_size": 10,
        "emission_mode": "slate",
    }
)
