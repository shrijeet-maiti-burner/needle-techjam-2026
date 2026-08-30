"""Faithful, target-blind runtime certificates for the Needle demo.

The scored response remains the source of truth.  This module receives the
objects and candidate sets that produced that response, then serializes the
belief ledger, interpretation lattice, candidate funnel, ranking evidence and
a clearly labelled human-facing question-policy shadow.  It never receives the
hidden target and cannot influence ranking.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from needle.catalog import CatalogIndex, canonical_signature
from needle.contracts import Candidate, TurnResponse
from needle.state import Polarity, SessionState, extract_constraints


TRACE_VERSION = "needle-lens-v1"
QUESTION_ATTRIBUTES = ("material", "color", "style", "use_case", "size")


def _compact(value: object, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _sample_candidate_ids(values: Sequence[str], limit: int = 500) -> tuple[str, ...]:
    ordered = tuple(dict.fromkeys(values))
    if len(ordered) <= limit:
        return ordered
    head = ordered[: min(50, limit)]
    remaining = sorted(
        ordered[len(head):],
        key=lambda parent_asin: hashlib.sha256(parent_asin.encode()).digest(),
    )[: limit - len(head)]
    return (*head, *remaining)


def _constraint_record(constraint: object) -> dict[str, object]:
    return {
        "attribute": str(getattr(constraint, "attribute")),
        "value": str(getattr(constraint, "value")),
        "polarity": str(getattr(getattr(constraint, "polarity"), "value")),
        "turn": int(getattr(constraint, "turn")),
        "intent_version": int(getattr(constraint, "intent_version")),
        "status": str(getattr(getattr(constraint, "status"), "value")),
        "supersedes": getattr(constraint, "supersedes"),
    }


def _question_board(
    evidence: dict[str, dict[str, object]],
    *,
    population_size: int,
) -> list[dict[str, object]]:
    """Estimate presupposition-safe partition value over a bounded sample.

    Unknown is an explicit answer group.  This avoids the classic information-
    gain error of pretending every product, or customer, can answer a proposed
    attribute question.  The board is a human-shopping shadow; the official
    evaluator policy remains `other` because that protocol can return any two
    constraints and the registered experiment shows it dominates.
    """

    if not evidence:
        return []
    extracted_by_id: dict[str, dict[str, set[str]]] = {}
    for parent_asin, product in evidence.items():
        text = " ".join(
            str(product.get(field) or "")
            for field in ("title", "categories", "features", "details", "description")
        )
        attributes: defaultdict[str, set[str]] = defaultdict(set)
        for attribute, value, polarity in extract_constraints(text):
            if polarity is Polarity.POSITIVE:
                attributes[attribute].add(value)
        extracted_by_id[parent_asin] = dict(attributes)

    count = len(extracted_by_id)
    board: list[dict[str, object]] = []
    for attribute in QUESTION_ATTRIBUTES:
        groups: Counter[tuple[str, ...]] = Counter()
        known = 0
        for attributes in extracted_by_id.values():
            values = tuple(sorted(attributes.get(attribute, ())))
            if values:
                known += 1
                groups[values] += 1
            else:
                groups[("unknown",)] += 1
        expected_remaining = sum(size * size for size in groups.values()) / count
        expected_reduction = 1.0 - expected_remaining / count
        coverage = known / count
        board.append({
            "attribute": attribute,
            "catalog_coverage": round(coverage, 6),
            "distinct_answer_groups": len(groups) - int(("unknown",) in groups),
            "unknown_count": groups[("unknown",)],
            "expected_candidate_reduction": round(expected_reduction, 6),
            "shadow_value": round(coverage * expected_reduction, 6),
            "presupposition_safe": True,
            "sample_count": count,
            "population_count": population_size,
            "sampled": count < population_size,
        })
    return sorted(
        board,
        key=lambda item: (-float(item["shadow_value"]), str(item["attribute"])),
    )


def _candidate_evidence(
    evidence: dict[str, dict[str, object]],
    recommendations: Sequence[str],
    state: SessionState,
) -> list[dict[str, object]]:
    active = state.active_constraints()
    result: list[dict[str, object]] = []
    for rank, parent_asin in enumerate(recommendations, start=1):
        product = evidence.get(parent_asin, {})
        searchable = canonical_signature(
            " ".join(
                str(product.get(field) or "")
                for field in ("title", "categories", "features", "details", "store", "description")
            )
        )
        searchable_terms = frozenset(searchable.split())
        matched: list[str] = []
        conflicts: list[str] = []
        for constraint in active:
            value_terms = frozenset(canonical_signature(constraint.value).split())
            if value_terms and value_terms.issubset(searchable_terms):
                label = f"{constraint.attribute}:{constraint.value}"
                if constraint.polarity is Polarity.NEGATIVE:
                    conflicts.append(label)
                else:
                    matched.append(label)
        result.append({
            "rank": rank,
            "parent_asin": parent_asin,
            "title": _compact(product.get("title")),
            "category": _compact(product.get("categories"), 140),
            "store": _compact(product.get("store"), 80),
            "rating_number": int(product.get("rating_number") or 0),
            "matched_active_constraints": matched,
            "conflicting_active_exclusions": conflicts,
            "catalog_excerpt": _compact(product.get("features") or product.get("details")),
        })
    return result


def build_turn_trace(
    *,
    catalog: CatalogIndex,
    state: SessionState,
    turn: int,
    retrieval_text: str,
    category: str,
    promoted: Sequence[str],
    identified: str | None,
    sparse: Sequence[Candidate],
    recommendations: Sequence[str],
    output_limit: int,
    seen_before: Iterable[str],
    decision_path: str,
    response: TurnResponse,
    promotion_limit: int,
    include_empty: bool,
) -> dict[str, object]:
    """Build one target-blind certificate from the actual response path."""

    diagnostics = catalog.disclosure_diagnostics(
        state.messages,
        category=category,
        allow_ordered=state.intent_version == 1,
        include_empty=include_empty,
        limit=promotion_limit,
    )
    category_diagnostics = catalog.disclosure_diagnostics(
        (),
        category=category,
        include_empty=True,
        limit=promotion_limit,
    )
    sparse_ids = tuple(candidate.parent_asin for candidate in sparse)
    population_ids = tuple(promoted) if promoted else sparse_ids
    sampled_ids = _sample_candidate_ids(population_ids)
    evidence_ids = tuple(dict.fromkeys((*recommendations, *sampled_ids)))
    evidence = catalog.product_evidence(evidence_ids)
    population_count = len(population_ids)
    active = state.active_constraints()
    active_attributes = {constraint.attribute for constraint in active}
    union_count = int(diagnostics["union_count"])
    residual_count = union_count or len(sparse_ids)
    ambiguity_status = (
        "resolved_unique"
        if identified is not None
        else "evidence_bounded"
        if promoted
        else "fallback_unresolved"
    )
    return {
        "trace_version": TRACE_VERSION,
        "target_blind": True,
        "turn": int(turn),
        "intent_version": state.intent_version,
        "retrieval_text": retrieval_text,
        "category_evidence": category,
        "belief_ledger": {
            "events": [_constraint_record(constraint) for constraint in state.constraints],
            "active": [_constraint_record(constraint) for constraint in active],
            "unobserved_attributes": [
                attribute for attribute in QUESTION_ATTRIBUTES if attribute not in active_attributes
            ],
        },
        "interpretation_lattice": diagnostics,
        "candidate_funnel": [
            {"stage": "frozen_catalog", "count": catalog.product_count},
            {"stage": "opening_category", "count": int(category_diagnostics["union_count"])},
            {"stage": "evidence_safe_union", "count": union_count},
            {"stage": "sparse_recovery_pool", "count": len(sparse_ids)},
            {"stage": "emitted_slate", "count": len(recommendations)},
        ],
        "ambiguity_certificate": {
            "status": ambiguity_status,
            "candidate_count": residual_count,
            "plausible_parse_count": len(diagnostics["parses"]),
            "residual_max_entropy_bits": round(math.log2(max(1, residual_count)), 6),
            "safe_to_claim_unique": identified is not None,
            "selection_basis": (
                "all resolving parses agree on one catalog product"
                if identified is not None
                else "catalog popularity within the union of every plausible evidence bucket"
                if promoted
                else "fielded sparse relevance with bounded catalog priors"
            ),
        },
        "decision": {
            "path": decision_path,
            "identified_parent_asin": identified,
            "promotion_candidate_count": len(promoted),
            "sparse_candidate_count": len(sparse_ids),
            "seen_before_count": len(frozenset(seen_before)),
            "output_limit": output_limit,
            "recommendations": list(recommendations),
        },
        "recommendation_evidence": _candidate_evidence(evidence, recommendations, state),
        "question_policy": {
            "scored_policy": response["ask_attribute"],
            "scored_policy_basis": (
                "the official simulator's open channel can return any two remaining constraints; "
                "registered exp-013 found every named-attribute arm worse"
            ),
            "human_shadow_only": True,
            "human_shadow_board": _question_board(
                {parent_asin: evidence[parent_asin] for parent_asin in sampled_ids if parent_asin in evidence},
                population_size=population_count,
            ),
        },
        "response": {
            "message": response["message"],
            "ask_attribute": response["ask_attribute"],
            "recommendations": list(recommendations),
            "usage": dict(response["usage"]),
        },
    }
