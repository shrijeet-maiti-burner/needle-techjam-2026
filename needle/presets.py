from __future__ import annotations

from types import MappingProxyType
from typing import Final, Mapping


PRIMARY_AGENT_KWARGS: Final[Mapping[str, object]] = MappingProxyType(
    {
        "retrieval_mode": "signature_first",
        "signature_bucket_limit": 100,
        "popularity_strength": 0.20,
        "override_policy": "preserve_subject",
        "lexical_mode": "none",
        "slate_size": 10,
    }
)

ROLLBACK_AGENT_KWARGS: Final[Mapping[str, object]] = MappingProxyType(
    {
        "retrieval_mode": "sparse",
        "popularity_strength": 0.20,
        "override_policy": "preserve_subject",
        "lexical_mode": "none",
        "slate_size": 10,
    }
)
