"""Evidence-bounded reranking for related shopping line items.

This is intentionally not a table of approved outfit pairs.  It combines the
catalog's own facets, explicit journey constraints, general colour geometry and
the rank produced by Needle.  Missing evidence lowers confidence; it never
becomes a fabricated incompatibility claim.
"""
from __future__ import annotations

import colorsys
import math
import re
import statistics
from dataclasses import asdict, dataclass
from typing import Iterable, Mapping, Sequence

from needle.catalog import _flatten_values, fold_marks, product_clarification_facets, query_terms
from needle.state import COLORS, extract_constraints

from storefront.catalog_view import CatalogView
from storefront.journey import (
    ConstraintGroup,
    ConstraintOperator,
    ConstraintStrength,
    LineItem,
    ShoppingPlan,
)
from storefront.preferences import PRICE, RATING, REVIEWS


_COLOR_RGB: Mapping[str, tuple[int, int, int]] = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "blue": (0, 90, 190),
    "red": (200, 35, 45),
    "pink": (235, 120, 155),
    "green": (40, 130, 75),
    "brown": (120, 72, 40),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
    "purple": (115, 65, 150),
    "yellow": (235, 195, 35),
    "orange": (225, 120, 30),
    "beige": (215, 195, 155),
    "navy": (20, 35, 80),
    "tan": (190, 145, 90),
    "gold": (205, 160, 35),
    "silver": (180, 185, 190),
    "burgundy": (115, 25, 45),
    "maroon": (100, 20, 35),
    "khaki": (175, 165, 105),
    "cream": (245, 235, 205),
    "ivory": (250, 245, 225),
}


@dataclass(frozen=True, slots=True)
class CompatibilityEvidence:
    anchor_id: str
    score: float
    confidence: str
    signals: tuple[str, ...]
    limitations: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RankedProduct:
    parent_asin: str
    score: float
    matched_constraints: int
    total_constraints: int
    hard_violation: bool
    compatibility: CompatibilityEvidence | None = None


@dataclass(frozen=True, slots=True)
class RerankResult:
    products: tuple[RankedProduct, ...]
    filtered_ids: tuple[str, ...]
    relaxed: bool
    reason: str
    ranking: Mapping[str, object] | None = None


def _record_text(product: Mapping[str, object]) -> str:
    fields = ("title", "features", "details", "categories", "description", "store")
    return " ".join(
        str(value)
        for field in fields
        for value in _flatten_values(product.get(field))
    )


def _tokens(product: Mapping[str, object]) -> frozenset[str]:
    return frozenset(query_terms(_record_text(product), limit=4000))


def _value_matches(value: str, tokens: frozenset[str]) -> bool:
    wanted = query_terms(value, limit=20)
    return bool(wanted and all(token in tokens for token in wanted))


def _stem(token: str) -> str:
    if token.endswith("oes") and len(token) > 4:
        return token[:-1]
    if token.endswith("sses") and len(token) > 5:
        return token[:-2]
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
    if token.endswith("es") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        return token[:-1]
    return token


def _category_matches(category: str, product: Mapping[str, object]) -> bool:
    if category == "item":
        return True
    wanted = {_stem(token) for token in query_terms(category, limit=12)}
    path = list(_flatten_values(product.get("categories")))
    category_tokens = {
        _stem(token)
        # The root is literally "Clothing, Shoes & Jewelry" for every row and
        # would make every product look like a shoe.  The next node is an
        # audience.  Product type evidence begins after both.
        for value in path[2:]
        for token in query_terms(str(value), limit=40)
    }
    # A catalog-derived phrase such as "running shoes" names one product type.
    # Accepting either token admitted running socks and non-running shoes into
    # the same slate.  Every stated category token must therefore occur in the
    # product's category path; singular normalization above keeps this strict
    # without making it spelling-fragile.
    return not wanted or wanted.issubset(category_tokens)


def _category_quality(category: str, product: Mapping[str, object]) -> float:
    """Prefer a leaf match over a broad ancestor match."""

    if category == "item":
        return 0.0
    wanted = {_stem(token) for token in query_terms(category, limit=12)}
    path = list(_flatten_values(product.get("categories")))[2:]
    if not wanted or not path:
        return 0.0
    nodes = [
        {_stem(token) for token in query_terms(str(value), limit=40)}
        for value in path
    ]
    if wanted == nodes[-1]:
        return 1.12
    if wanted.intersection(nodes[-1]):
        return 1.0
    if len(nodes) > 1 and wanted.intersection(nodes[-2]):
        return 0.78
    return 0.48 if any(wanted.intersection(node) for node in nodes) else 0.0


def _audience(product: Mapping[str, object]) -> str:
    # The catalog taxonomy is the declared source of audience truth. Titles
    # occasionally disagree with their filed department, so use title text
    # only when the taxonomy has no recognized audience node.
    path = list(_flatten_values(product.get("categories")))
    if len(path) > 1:
        taxonomy = fold_marks(str(path[1])).strip().lower()
        if taxonomy in {"men", "women", "boys", "girls"}:
            return taxonomy
    title_terms = set(query_terms(str(product.get("title") or ""), limit=80))
    stated = [
        audience
        for audience in ("men", "women", "boys", "girls")
        if audience in title_terms
    ]
    if len(stated) == 1:
        return stated[0]
    return ""


def _group_matches(group: ConstraintGroup, product: Mapping[str, object], tokens: frozenset[str]) -> int:
    if group.attribute == "budget":
        try:
            cap = min(float(value) for value in group.values)
            price = float(product.get("price"))
        except (TypeError, ValueError):
            return 0
        return int(price <= cap)
    return sum(_value_matches(value, tokens) for value in group.values)


def _hard_violation(item: LineItem, product: Mapping[str, object], tokens: frozenset[str]) -> bool:
    for group in item.constraints:
        matches = _group_matches(group, product, tokens)
        if group.operator is ConstraintOperator.NOT and matches:
            return True
        if group.strength is not ConstraintStrength.HARD:
            continue
        if group.operator is ConstraintOperator.ANY and not matches:
            return True
        if group.operator is ConstraintOperator.ALL and matches < len(group.values):
            return True
    return False


def _numeric_value(product: Mapping[str, object], field: str) -> float | None:
    raw = product.get(field)
    if field == PRICE and isinstance(raw, str):
        found = re.search(r"\d+(?:,\d{3})*(?:\.\d+)?", raw)
        raw = found.group(0).replace(",", "") if found is not None else None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    if field == PRICE:
        return value if value > 0 else None
    if field == RATING:
        return value if 0 < value <= 5 else None
    if field == REVIEWS:
        return value if value >= 0 else None
    return None


def _numeric_violation(item: LineItem, product: Mapping[str, object]) -> bool:
    """Unknown numeric facts cannot truthfully satisfy a hard numeric filter."""

    for constraint in item.numeric_filters:
        value = _numeric_value(product, constraint.field)
        if value is None:
            return True
        if constraint.minimum is not None and (
            value < constraint.minimum
            or (not constraint.minimum_inclusive and value == constraint.minimum)
        ):
            return True
        if constraint.maximum is not None and (
            value > constraint.maximum
            or (not constraint.maximum_inclusive and value == constraint.maximum)
        ):
            return True
    return False


def _colors(product: Mapping[str, object]) -> tuple[str, ...]:
    found = [
        value
        for attribute, value, polarity in extract_constraints(_record_text(product))
        if attribute == "color" and polarity.value == "positive"
    ]
    return tuple(dict.fromkeys(value for value in found if value in COLORS))


def _use_cases(product: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            value
            for attribute, value, polarity in extract_constraints(_record_text(product))
            if attribute == "use_case" and polarity.value == "positive"
        )
    )


def _context_fit(product: Mapping[str, object], global_context: Iterable[str]) -> tuple[float, str]:
    """Score only occasion evidence the catalog actually states."""

    wanted = set(global_context)
    if not wanted:
        return 0.0, ""
    stated = set(_use_cases(product))
    overlap = wanted.intersection(stated)
    if overlap:
        return 0.42, "occasion evidence: " + ", ".join(sorted(overlap)[:3])
    if stated:
        return -0.24, "different stated occasion: " + ", ".join(sorted(stated)[:3])
    return 0.0, ""


def _color_harmony(left: str, right: str) -> float:
    """General hue/lightness harmony in [0, 1], not a pair lookup."""

    if left == right:
        return 0.86
    first = _COLOR_RGB.get(left)
    second = _COLOR_RGB.get(right)
    if first is None or second is None:
        return 0.5
    h1, l1, s1 = colorsys.rgb_to_hls(*(channel / 255.0 for channel in first))
    h2, l2, s2 = colorsys.rgb_to_hls(*(channel / 255.0 for channel in second))
    hue_distance = min(abs(h1 - h2), 1.0 - abs(h1 - h2))
    lightness_contrast = abs(l1 - l2)
    # Neutrals combine broadly; for chromatic pairs, analogous and
    # complementary hues are stronger than an arbitrary middle distance.
    if min(s1, s2) < 0.12:
        return min(0.95, 0.68 + 0.22 * lightness_contrast)
    analogous = math.exp(-((hue_distance / 0.12) ** 2))
    complementary = math.exp(-(((hue_distance - 0.5) / 0.12) ** 2))
    return min(0.95, 0.42 + 0.35 * max(analogous, complementary) + 0.18 * lightness_contrast)


def compatibility_evidence(
    anchor_id: str,
    anchor: Mapping[str, object],
    candidate: Mapping[str, object],
    global_context: Iterable[str],
) -> CompatibilityEvidence:
    anchor_facets = product_clarification_facets(dict(anchor))
    candidate_facets = product_clarification_facets(dict(candidate))
    signals: list[str] = []
    limitations: list[str] = []
    score = 0.5
    evidence_count = 0

    anchor_style = anchor_facets.get("style")
    candidate_style = candidate_facets.get("style")
    if anchor_style and candidate_style:
        evidence_count += 1
        if anchor_style == candidate_style:
            score += 0.20
            signals.append(f"shared {anchor_style} formality/style evidence")
        elif {anchor_style, candidate_style}.intersection({"formal", "elegant", "classic"}) and {anchor_style, candidate_style}.intersection({"casual", "athletic", "sporty"}):
            score -= 0.18
            signals.append(f"possible style mismatch: {anchor_style} versus {candidate_style}")
        else:
            signals.append(f"different catalog styles: {anchor_style} and {candidate_style}")

    anchor_audience = _audience(anchor)
    candidate_audience = _audience(candidate)
    if anchor_audience and candidate_audience:
        evidence_count += 1
        if anchor_audience == candidate_audience:
            score += 0.16
            signals.append(f"shared catalog audience: {anchor_audience}")
        else:
            score -= 0.30
            signals.append(
                f"possible wearer mismatch: {anchor_audience} versus {candidate_audience}"
            )

    anchor_colors = _colors(anchor)
    candidate_colors = _colors(candidate)
    if anchor_colors and candidate_colors:
        evidence_count += 1
        best = max(
            (value, left, right)
            for left in anchor_colors
            for right in candidate_colors
            for value in (_color_harmony(left, right),)
        )
        score += 0.28 * (best[0] - 0.5)
        signals.append(f"colour relationship evaluated from {best[1]} and {best[2]}")
    else:
        limitations.append("one or both products lack reliable colour metadata")

    context_delta, context_signal = _context_fit(candidate, global_context)
    if context_signal:
        evidence_count += 1
        score += 0.45 * context_delta
        signals.append(context_signal)
    elif tuple(global_context):
        limitations.append("the candidate does not state the journey occasion")

    if not signals:
        limitations.append("catalog text is insufficient for a strong compatibility claim")
    confidence = "high" if evidence_count >= 3 else "medium" if evidence_count == 2 else "low"
    return CompatibilityEvidence(
        anchor_id=anchor_id,
        score=round(max(0.0, min(1.0, score)), 4),
        confidence=confidence,
        signals=tuple(signals),
        limitations=tuple(limitations),
    )


def rerank_products(
    view: CatalogView,
    plan: ShoppingPlan,
    item: LineItem,
    candidate_ids: Sequence[str],
    *,
    anchor_id: str | None = None,
    enforce_anchor_audience: bool = False,
    explore: bool = False,
    limit: int = 10,
) -> RerankResult:
    """Filter hard violations, then stably rerank with inspectable evidence."""

    anchor = view.raw(anchor_id) if anchor_id else None
    anchor_audience = _audience(anchor) if anchor is not None else ""
    rows: list[RankedProduct] = []
    products: dict[str, Mapping[str, object]] = {}
    filtered: list[str] = []
    seen: set[str] = set()
    catalog_products = view.raw_many(candidate_ids)
    for rank, identifier in enumerate(candidate_ids, start=1):
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        product = catalog_products.get(identifier)
        if product is None:
            continue
        product_tokens = _tokens(product)
        category_ok = _category_matches(item.category, product)
        violation = _hard_violation(
            item, product, product_tokens
        ) or _numeric_violation(item, product)
        candidate_audience = _audience(product)
        explicit_audience_mismatch = (
            bool(item.audience)
            and candidate_audience in {"men", "women", "boys", "girls"}
            and candidate_audience != item.audience
        )
        audience_mismatch = (
            enforce_anchor_audience
            and
            anchor is not None
            and anchor_audience in {"men", "women", "boys", "girls"}
            and candidate_audience in {"men", "women", "boys", "girls"}
            and anchor_audience != candidate_audience
        )
        if not category_ok or violation or explicit_audience_mismatch or audience_mismatch:
            filtered.append(identifier)
            continue

        products[identifier] = product

        matched = len(item.numeric_filters)
        total = len(item.numeric_filters)
        score = 0.55 / math.log2(rank + 1.0)
        score += 0.90 * _category_quality(item.category, product)
        context_delta, _ = _context_fit(product, plan.global_context)
        score += context_delta
        for group in item.positive_groups():
            group_matches = _group_matches(group, product, product_tokens)
            matched += min(len(group.values), group_matches)
            total += len(group.values)
            if group.operator is ConstraintOperator.ANY:
                score += 0.36 if group_matches else 0.0
                if group.prefer_all and group_matches == len(group.values):
                    score += 0.32
            else:
                score += 0.22 * group_matches
            if group.strength is ConstraintStrength.SOFT:
                score -= 0.06 * max(0, len(group.values) - group_matches)

        evidence = (
            compatibility_evidence(anchor_id or "", anchor, product, plan.global_context)
            if anchor_id and anchor is not None
            else None
        )
        if evidence is not None:
            score += 0.60 * evidence.score
        rows.append(
            RankedProduct(
                parent_asin=identifier,
                score=round(score, 6),
                matched_constraints=matched,
                total_constraints=total,
                hard_violation=False,
                compatibility=evidence,
            )
        )

    relaxed = False
    reason = "hard constraints and category integrity enforced"
    if not rows:
        # Empty is safer than unrelated products for a shopper, but return an
        # explicit relaxation signal so the service can ask permission rather
        # than silently discarding a requirement.
        return RerankResult((), tuple(filtered), False, "no candidate satisfies every hard requirement")

    rows.sort(key=lambda row: (-row.score, row.parent_asin))
    ranking_evidence: dict[str, object] | None = None
    if item.ranking is not None:
        preference = item.ranking
        values: dict[str, float | None] = {}
        method = "catalog field"
        if preference.field == RATING:
            observed = [
                (
                    _numeric_value(products[row.parent_asin], RATING),
                    _numeric_value(products[row.parent_asin], REVIEWS),
                )
                for row in rows
            ]
            supported = [
                (rating, reviews)
                for rating, reviews in observed
                if rating is not None and reviews is not None
            ]
            if supported:
                total_weight = sum(max(1.0, reviews) for _, reviews in supported)
                prior_mean = (
                    sum(rating * max(1.0, reviews) for rating, reviews in supported)
                    / total_weight
                )
                prior_weight = float(
                    statistics.median(max(1.0, reviews) for _, reviews in supported)
                )
            else:
                prior_mean, prior_weight = 0.0, 1.0
            for row in rows:
                rating = _numeric_value(products[row.parent_asin], RATING)
                reviews = _numeric_value(products[row.parent_asin], REVIEWS)
                values[row.parent_asin] = (
                    (rating * reviews + prior_mean * prior_weight) / (reviews + prior_weight)
                    if rating is not None and reviews is not None
                    else None
                )
            method = "bayesian average weighted by catalog review count"
            ranking_evidence = {
                "field": preference.field,
                "label": preference.label(),
                "direction": "descending" if preference.descending else "ascending",
                "method": method,
                "prior_mean": round(prior_mean, 4),
                "prior_weight": round(prior_weight, 2),
                "eligible_with_value": sum(value is not None for value in values.values()),
            }
        else:
            values = {
                row.parent_asin: _numeric_value(products[row.parent_asin], preference.field)
                for row in rows
            }
            ranking_evidence = {
                "field": preference.field,
                "label": preference.label(),
                "direction": "descending" if preference.descending else "ascending",
                "method": method,
                "eligible_with_value": sum(value is not None for value in values.values()),
            }

        def preference_order(row: RankedProduct) -> tuple[float, bool, float, float, str]:
            value = values.get(row.parent_asin)
            ordered = (
                -value if preference.descending and value is not None
                else value if value is not None
                else 0.0
            )
            # Explicit ordering applies within the right product type.  A
            # highly-rated accessory that mentions the category must not beat
            # a product filed at that category's leaf.
            quality = _category_quality(item.category, products[row.parent_asin])
            return (-quality, value is None, ordered, -row.score, row.parent_asin)

        rows.sort(key=preference_order)
        reason = f"hard constraints enforced; ranked by {preference.label()}"
    elif explore and len(rows) > 1:
        rows = _diversify(view, rows)
        reason = "hard constraints enforced; slate diversified by catalog facets"
    return RerankResult(
        tuple(rows[: max(0, int(limit))]),
        tuple(filtered),
        relaxed,
        reason,
        ranking_evidence,
    )


def _diversify(view: CatalogView, rows: Sequence[RankedProduct]) -> list[RankedProduct]:
    """Greedy relevance/diversity selection over catalog-derived facets."""

    remaining = list(rows)
    selected: list[RankedProduct] = []
    selected_signatures: list[frozenset[str]] = []
    while remaining:
        best_index = 0
        best_value = float("-inf")
        for index, row in enumerate(remaining):
            product = view.raw(row.parent_asin) or {}
            facets = product_clarification_facets(dict(product))
            signature = frozenset(f"{key}:{value}" for key, value in facets.items())
            if not selected_signatures:
                novelty = 1.0
            else:
                novelty = min(
                    1.0 - len(signature.intersection(previous)) / max(1, len(signature.union(previous)))
                    for previous in selected_signatures
                )
            value = 0.72 * row.score + 0.28 * novelty
            if value > best_value:
                best_index, best_value = index, value
        chosen = remaining.pop(best_index)
        product = view.raw(chosen.parent_asin) or {}
        facets = product_clarification_facets(dict(product))
        selected_signatures.append(frozenset(f"{key}:{value}" for key, value in facets.items()))
        selected.append(chosen)
    return selected


__all__ = [
    "CompatibilityEvidence",
    "RankedProduct",
    "RerankResult",
    "compatibility_evidence",
    "rerank_products",
]
