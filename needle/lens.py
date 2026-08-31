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
from collections.abc import Iterable, Sequence
from needle.catalog import CatalogIndex, canonical_signature
from needle.contracts import Candidate, TurnResponse
from needle.questions import clarification_board
from needle.state import Polarity, SessionState


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
    candidate_ids: Sequence[str],
    facets: dict[str, dict[str, str]],
    *,
    population_size: int,
    already_said: Sequence[str],
    turns_left: int,
    excluded_values: Sequence[str],
) -> list[dict[str, object]]:
    """Serialize the same bounded value-of-information board the agent uses.

    Unknown is an explicit answer group.  This avoids the classic information-
    gain error of pretending every product, or customer, can answer a proposed
    attribute question. The official evaluator channel remains ``other``
    because that protocol can return any two constraints; these rows govern
    only the natural-language question shown to a person.
    """
    sampled = len(candidate_ids) < population_size
    rows: list[dict[str, object]] = []
    for decision in clarification_board(
        candidate_ids,
        facets,
        already_said=already_said,
        turns_left=turns_left,
        sampled=sampled,
        excluded_values=excluded_values,
    ):
        row = decision.as_dict()
        row.update({
            "shadow_value": round(
                decision.catalog_coverage * decision.expected_candidate_reduction,
                6,
            ),
            "presupposition_safe": True,
            "sample_count": len(candidate_ids),
            "population_count": population_size,
        })
        rows.append(row)
    return rows


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
    ordered_disclosures_safe: bool | None = None,
    question_decision: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build one target-blind certificate from the actual response path."""

    ordered_safe = (
        state.intent_version == 1
        and catalog.ordered_disclosures_stable(state.retrieval_messages)
        if ordered_disclosures_safe is None
        else bool(ordered_disclosures_safe)
    )
    diagnostics = catalog.disclosure_diagnostics(
        state.retrieval_messages,
        category=category,
        allow_ordered=ordered_safe,
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
    question_facets = catalog.clarification_facets(sampled_ids)
    already_said = tuple(
        value
        for constraint in active
        if constraint.polarity is Polarity.POSITIVE
        for value in (constraint.attribute, constraint.value)
    )
    excluded_values = tuple(
        constraint.value
        for constraint in active
        if constraint.polarity is Polarity.NEGATIVE
    )
    question_board = _question_board(
        sampled_ids,
        question_facets,
        population_size=population_count,
        already_said=already_said,
        turns_left=max(0, 10 - int(turn)),
        excluded_values=excluded_values,
    )
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
        "ordered_disclosures_safe": ordered_safe,
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
            "human_message_causal": bool(
                question_decision and question_decision.get("asks")
            ),
            "human_message_decision": dict(question_decision or {}),
            "human_shadow_only": not bool(
                question_decision and question_decision.get("asks")
            ),
            "human_shadow_board": question_board,
        },
        "response": {
            "message": response["message"],
            "ask_attribute": response["ask_attribute"],
            "recommendations": list(recommendations),
            "usage": dict(response["usage"]),
        },
    }
