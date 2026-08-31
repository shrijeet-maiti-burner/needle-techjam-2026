"""Typed numeric shopping preferences for the product-facing journey.

The catalog exposes three numeric facts a shopper can act on: ``price``,
``average_rating`` and ``rating_number``.  They must not be pushed through text
retrieval: a price is a bound, and "best rated" is an ordering request rather
than a product keyword.  This module turns only explicit numeric language into
typed filters and ranks.  Product names and values remain catalog-derived.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from needle.state import Polarity, _is_negated, extract_constraints


PRICE = "price"
RATING = "average_rating"
REVIEWS = "rating_number"

_NUMBER = r"\d+(?:,\d{3})*(?:\.\d{1,2})?"
_PRICE_CUE_RE = re.compile(r"\$|\b(?:price|budget|cost|spend|dollars?)\b", re.IGNORECASE)
_RATING_CUE_RE = re.compile(r"\b(?:rated|rating|stars?)\b", re.IGNORECASE)
_PRICE_RANGE_RE = re.compile(
    rf"(?:(?:price|budget|cost)\s*)?(?:between|from)?\s*"
    rf"(?P<low>\$?\s*{_NUMBER})\s*(?:and|to|[-\u2013\u2014])\s*"
    rf"(?P<high>\$?\s*{_NUMBER})(?:\s*dollars?)?",
    re.IGNORECASE,
)
_PRICE_MIN_RE = re.compile(
    rf"(?P<prefix>\b(?:price|budget|cost|spend)\b[^.!?,;]{{0,18}})?"
    rf"\b(?P<op>over|above|more\s+than|at\s+least|minimum(?:\s+of)?)\s*"
    rf"(?P<value>\$?\s*{_NUMBER})(?:\s*dollars?)?",
    re.IGNORECASE,
)
_PRICE_MAX_RE = re.compile(
    rf"\b(?P<op>under|below|less\s+than|at\s+most|up\s+to|maximum(?:\s+of)?)\s*"
    rf"(?P<value>\$?\s*{_NUMBER})(?![-a-z0-9>])(?:\s*dollars?)?",
    re.IGNORECASE,
)
_DIRECT_PRICE_RE = re.compile(
    rf"(?:\b(?:price|budget|cost)\b\s*(?:of|is|:)?\s*)?\$\s*{_NUMBER}",
    re.IGNORECASE,
)
_RATING_RANGE_RE = re.compile(
    rf"\b(?:rating\s+)?(?:between|from)\s*(?P<low>{_NUMBER})\s*"
    rf"(?:and|to|[-\u2013\u2014])\s*(?P<high>{_NUMBER})\s*(?:stars?|rating)?\b",
    re.IGNORECASE,
)
_RATING_MIN_RE = re.compile(
    rf"(?:\b(?:rated|rating)\s*(?P<after_op>at\s+least|above|over|of)?\s*"
    rf"(?P<after>{_NUMBER})|\b(?P<before_op>at\s+least|above|over|minimum(?:\s+of)?)\s*"
    rf"(?P<before>{_NUMBER}))\s*(?:stars?|rating)\b",
    re.IGNORECASE,
)
_RATING_MAX_RE = re.compile(
    rf"(?:\b(?:rated|rating)\s*(?P<after_op>at\s+most|up\s+to|below|under|less\s+than|maximum(?:\s+of)?)\s*"
    rf"(?P<after>{_NUMBER})\s*(?:stars?)?|\b(?P<before_op>at\s+most|up\s+to|below|under|less\s+than|"
    rf"maximum(?:\s+of)?)\s*(?P<before>{_NUMBER})\s*(?:stars?|rating))\b",
    re.IGNORECASE,
)
_RATING_PLUS_RE = re.compile(rf"\b(?P<value>{_NUMBER})\s*\+\s*stars?\b", re.IGNORECASE)
_REVIEW_RANGE_RE = re.compile(
    rf"\b(?:(?:reviews?|ratings?)\s*)?(?:between|from)\s*(?P<low>{_NUMBER})\s*"
    rf"(?:and|to|[-\u2013\u2014])\s*(?P<high>{_NUMBER})\s*"
    rf"(?:customer\s+)?(?:reviews?|ratings?)\b",
    re.IGNORECASE,
)
_REVIEW_MIN_RE = re.compile(
    rf"(?:\b(?:reviews?|ratings?)\s*(?P<after_op>at\s+least|over|above|more\s+than|"
    rf"minimum(?:\s+of)?)\s*(?P<after>{_NUMBER})|\b(?P<before_op>at\s+least|over|above|"
    rf"more\s+than|minimum(?:\s+of)?)\s*(?P<before>{_NUMBER})\s*"
    rf"(?:customer\s+)?(?:reviews?|ratings?))\b",
    re.IGNORECASE,
)
_REVIEW_MAX_RE = re.compile(
    rf"(?:\b(?:reviews?|ratings?)\s*(?P<after_op>at\s+most|up\s+to|below|under|less\s+than|"
    rf"maximum(?:\s+of)?)\s*(?P<after>{_NUMBER})|\b(?P<before_op>at\s+most|up\s+to|below|under|"
    rf"less\s+than|maximum(?:\s+of)?)\s*(?P<before>{_NUMBER})\s*"
    rf"(?:customer\s+)?(?:reviews?|ratings?))\b",
    re.IGNORECASE,
)

_NON_PRICE_QUANTITY_RE = re.compile(
    r"^\s*(?:stars?|ratings?|reviews?|people|persons?|pairs?|items?|products?|"
    r"pieces?|sets?|inches?|feet|foot|centimeters?|millimeters?|meters?|"
    r"cm|mm|kg|kilograms?|g|grams?|oz|ounces?|lb|pounds?)\b",
    re.IGNORECASE,
)

_PRICE_ASC_RE = re.compile(
    r"\b(?:cheapest|lowest[- ]price(?:d)?|least\s+expensive|most\s+affordable|"
    r"budget[- ]friendly)\b",
    re.IGNORECASE,
)
_PRICE_DESC_RE = re.compile(r"\b(?:most\s+expensive|highest[- ]price(?:d)?)\b", re.IGNORECASE)
_RATING_DESC_RE = re.compile(
    r"\b(?:best|top|highest)[- ]rated\b|\b(?:best|highest)\s+(?:customer\s+)?rating\b",
    re.IGNORECASE,
)
_RATING_ASC_RE = re.compile(r"\b(?:worst|lowest)[- ]rated\b", re.IGNORECASE)
_REVIEWS_DESC_RE = re.compile(r"\b(?:most[- ]reviewed|most\s+popular)\b", re.IGNORECASE)
_REVIEWS_ASC_RE = re.compile(r"\b(?:least[- ]reviewed|fewest\s+reviews?)\b", re.IGNORECASE)

_CLEAR_PATTERNS = {
    PRICE: re.compile(
        r"\b(?:any\s+price|no\s+(?:price|budget)\s+preference|"
        r"(?:price|budget)\s+(?:doesn['\u2019]?t|does\s+not)\s+matter)\b",
        re.IGNORECASE,
    ),
    RATING: re.compile(
        r"\b(?:any\s+rating|no\s+rating\s+preference|"
        r"ratings?\s+(?:doesn['\u2019]?t|does\s+not)\s+matter)\b",
        re.IGNORECASE,
    ),
    REVIEWS: re.compile(
        r"\b(?:any\s+review\s+count|no\s+review\s+preference|"
        r"reviews?\s+(?:don['\u2019]?t|do\s+not)\s+matter)\b",
        re.IGNORECASE,
    ),
}


def _number(value: str) -> float:
    return float(value.replace("$", "").replace(",", "").strip())


def _operator(match: re.Match[str]) -> str:
    groups = match.groupdict()
    return str(
        groups.get("op")
        or groups.get("after_op")
        or groups.get("before_op")
        or ""
    ).lower()


def _strict_minimum(match: re.Match[str]) -> bool:
    return _operator(match) in {"over", "above", "more than"}


def _strict_maximum(match: re.Match[str]) -> bool:
    return _operator(match) in {"under", "below", "less than"}


@dataclass(frozen=True, slots=True)
class NumericFilter:
    field: str
    minimum: float | None
    maximum: float | None
    turn: int
    source: str
    minimum_inclusive: bool = True
    maximum_inclusive: bool = True

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    def label(self) -> str:
        name = {
            PRICE: "price",
            RATING: "rating",
            REVIEWS: "reviews",
        }[self.field]
        unit = "$" if self.field == PRICE else ""
        suffix = " stars" if self.field == RATING else ""
        if self.minimum is not None and self.maximum is not None:
            return f"{name} {unit}{self.minimum:g} to {unit}{self.maximum:g}{suffix}"
        if self.minimum is not None:
            operator = "at least" if self.minimum_inclusive else "more than"
            return f"{name} {operator} {unit}{self.minimum:g}{suffix}"
        assert self.maximum is not None
        operator = "up to" if self.maximum_inclusive else "under"
        return f"{name} {operator} {unit}{self.maximum:g}{suffix}"


@dataclass(frozen=True, slots=True)
class RankingPreference:
    field: str
    descending: bool
    turn: int
    source: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    def label(self) -> str:
        labels = {
            (PRICE, False): "lowest listed price",
            (PRICE, True): "highest listed price",
            (RATING, False): "lowest confidence-adjusted rating",
            (RATING, True): "best confidence-adjusted rating",
            (REVIEWS, False): "fewest reviews",
            (REVIEWS, True): "most reviewed",
        }
        return labels[(self.field, self.descending)]


@dataclass(frozen=True, slots=True)
class NumericIntent:
    filters: tuple[NumericFilter, ...] = ()
    ranking: RankingPreference | None = None
    clear_fields: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        return bool(self.filters or self.ranking or self.clear_fields)


def parse_numeric_intent(message: str, turn: int) -> NumericIntent:
    """Parse explicit price, star and review-count intent without guessing."""

    text = str(message)
    filters: dict[str, NumericFilter] = {}
    clear = tuple(field for field, pattern in _CLEAR_PATTERNS.items() if pattern.search(text))

    price_range = _PRICE_RANGE_RE.search(text)
    if (
        price_range
        and _PRICE_CUE_RE.search(price_range.group(0))
        and not _is_negated(text, price_range.start())
    ):
        low, high = sorted((_number(price_range.group("low")), _number(price_range.group("high"))))
        filters[PRICE] = NumericFilter(PRICE, low, high, int(turn), text[:240])
    else:
        price_min = _PRICE_MIN_RE.search(text)
        if (
            price_min
            and _PRICE_CUE_RE.search(price_min.group(0))
            and not _is_negated(text, price_min.start())
        ):
            filters[PRICE] = NumericFilter(
                PRICE,
                _number(price_min.group("value")),
                None,
                int(turn),
                text[:240],
                minimum_inclusive=not _strict_minimum(price_min),
            )
        else:
            # Reuse the scored parser for upper bounds.  It already rejects
            # measurements such as "up to 30mm" and honors in-message fixes.
            caps = [
                float(value)
                for attribute, value, polarity in extract_constraints(text)
                if attribute == "budget" and polarity is Polarity.POSITIVE
            ]
            cap_matches = list(_PRICE_MAX_RE.finditer(text))
            last_cap = cap_matches[-1] if cap_matches else None
            explicit_money = bool(
                last_cap is not None and _PRICE_CUE_RE.search(last_cap.group(0))
            )
            direct_currency = bool(last_cap is None and _DIRECT_PRICE_RE.search(text))
            quantity_tail = (
                _NON_PRICE_QUANTITY_RE.search(text[last_cap.end() :])
                if last_cap is not None
                else None
            )
            if caps and (
                explicit_money
                or direct_currency
                or (last_cap is not None and quantity_tail is None)
            ):
                filters[PRICE] = NumericFilter(
                    PRICE,
                    None,
                    caps[-1],
                    int(turn),
                    text[:240],
                    maximum_inclusive=(
                        not _strict_maximum(last_cap) if last_cap is not None else True
                    ),
                )

    rating_range = _RATING_RANGE_RE.search(text)
    if (
        rating_range
        and _RATING_CUE_RE.search(rating_range.group(0))
        and not _is_negated(text, rating_range.start())
    ):
        low, high = sorted((_number(rating_range.group("low")), _number(rating_range.group("high"))))
        if 0 < low <= 5 and 0 < high <= 5:
            filters[RATING] = NumericFilter(RATING, low, high, int(turn), text[:240])
    else:
        rating_min = _RATING_MIN_RE.search(text)
        rating_plus = _RATING_PLUS_RE.search(text)
        found = rating_min or rating_plus
        if found and not _is_negated(text, found.start()):
            raw = (
                found.groupdict().get("after")
                or found.groupdict().get("before")
                or found.groupdict().get("value")
            )
            value = _number(str(raw))
            if 0 < value <= 5:
                filters[RATING] = NumericFilter(
                    RATING,
                    value,
                    None,
                    int(turn),
                    text[:240],
                    minimum_inclusive=not _strict_minimum(found),
                )

    rating_max = _RATING_MAX_RE.search(text)
    if rating_max and not _is_negated(text, rating_max.start()):
        raw = rating_max.groupdict().get("after") or rating_max.groupdict().get("before")
        value = _number(str(raw))
        if 0 < value <= 5:
            filters[RATING] = NumericFilter(
                RATING,
                None,
                value,
                int(turn),
                text[:240],
                maximum_inclusive=not _strict_maximum(rating_max),
            )

    review_range = _REVIEW_RANGE_RE.search(text)
    if review_range and not _is_negated(text, review_range.start()):
        low, high = sorted((_number(review_range.group("low")), _number(review_range.group("high"))))
        filters[REVIEWS] = NumericFilter(REVIEWS, low, high, int(turn), text[:240])
    else:
        review_min = _REVIEW_MIN_RE.search(text)
        review_max = _REVIEW_MAX_RE.search(text)
        found_review = review_min or review_max
        if found_review and not _is_negated(text, found_review.start()):
            raw = (
                found_review.groupdict().get("after")
                or found_review.groupdict().get("before")
            )
            value = _number(str(raw))
            filters[REVIEWS] = NumericFilter(
                REVIEWS,
                value if review_min is not None else None,
                value if review_max is not None else None,
                int(turn),
                text[:240],
                minimum_inclusive=(
                    not _strict_minimum(found_review) if review_min is not None else True
                ),
                maximum_inclusive=(
                    not _strict_maximum(found_review) if review_max is not None else True
                ),
            )

    ranking: RankingPreference | None = None
    for field, descending, pattern in (
        (RATING, True, _RATING_DESC_RE),
        (RATING, False, _RATING_ASC_RE),
        (REVIEWS, True, _REVIEWS_DESC_RE),
        (REVIEWS, False, _REVIEWS_ASC_RE),
        (PRICE, False, _PRICE_ASC_RE),
        (PRICE, True, _PRICE_DESC_RE),
    ):
        found = pattern.search(text)
        if found and not _is_negated(text, found.start()):
            ranking = RankingPreference(field, descending, int(turn), text[:240])
            break

    return NumericIntent(tuple(filters.values()), ranking, clear)


def searchable_text(message: str) -> str:
    """Remove numeric directives that are not catalog prose search terms."""

    text = str(message)
    # A bare numeric range can be a size or measurement. Strip it only when
    # the matched phrase itself contains an explicit money cue; otherwise it
    # remains available to ordinary catalog retrieval.
    text = _PRICE_RANGE_RE.sub(
        lambda match: " " if _PRICE_CUE_RE.search(match.group(0)) else match.group(0),
        text,
    )
    text = _PRICE_MIN_RE.sub(
        lambda match: " " if _PRICE_CUE_RE.search(match.group(0)) else match.group(0),
        text,
    )
    text = _PRICE_MAX_RE.sub(
        lambda match: (
            " "
            if _PRICE_CUE_RE.search(match.group(0))
            or _NON_PRICE_QUANTITY_RE.search(text[match.end() :]) is None
            else match.group(0)
        ),
        text,
    )
    text = _RATING_RANGE_RE.sub(
        lambda match: " " if _RATING_CUE_RE.search(match.group(0)) else match.group(0),
        text,
    )
    patterns = (
        _RATING_MIN_RE,
        _RATING_MAX_RE,
        _RATING_PLUS_RE,
        _REVIEW_RANGE_RE,
        _REVIEW_MIN_RE,
        _REVIEW_MAX_RE,
        _DIRECT_PRICE_RE,
        _PRICE_ASC_RE,
        _PRICE_DESC_RE,
        _RATING_DESC_RE,
        _RATING_ASC_RE,
        _REVIEWS_DESC_RE,
        _REVIEWS_ASC_RE,
        *_CLEAR_PATTERNS.values(),
    )
    for pattern in patterns:
        text = pattern.sub(" ", text)
    return " ".join(text.split())


__all__ = [
    "NumericFilter",
    "NumericIntent",
    "RankingPreference",
    "PRICE",
    "RATING",
    "REVIEWS",
    "parse_numeric_intent",
    "searchable_text",
]
