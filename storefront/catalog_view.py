"""Display records for the products an agent turn actually recommended.

The response contract carries `parent_asin` and nothing else, so a shopping
interface has to rejoin the catalog to show a person anything. Two constraints
shape how:

*Read the catalog, not the agent's index.* `CatalogIndex` builds an FTS5 table
of flattened text and keeps `price` and `average_rating` out of it entirely,
because retrieval has no use for them. Reading its internal schema to recover
display fields would couple this module to a private layout and still not
return the missing ones.

*Do not hold 50000 products in memory to show ten.* One pass records the byte
offset of each line, then a card is a `seek` and one `json.loads`. The index is
about 5MB for the released catalog against roughly 400MB to retain the parsed
products, and a turn pays for the ten rows it displays.

Matched terms are stated as what they are. `query_terms` and `fold_marks` are
imported from `needle.catalog` rather than reimplemented, so a term is shown as
matching only when it tokenizes the way retrieval tokenizes it. That makes the
chip a true statement about the product text -- it is deliberately *not* a claim
about why the product ranked where it did, which BM25 weights, the popularity
prior and disclosure promotion decide together.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from needle.catalog import _flatten_values, _text, fold_marks, query_terms


# Fields a card can cite, in the order a shopper reads them. `parent_asin` and
# `rating_number` are excluded: neither is prose, and a digit string matching a
# query term would be noise rather than evidence.
CITED_FIELDS: tuple[str, ...] = (
    "title",
    "features",
    "details",
    "categories",
    "store",
    "description",
)

_WHITESPACE = re.compile(r"\s+")


def _tidy(value: object, limit: int = 240) -> str:
    return _WHITESPACE.sub(" ", str(value)).strip()[:limit].strip()


@dataclass(frozen=True, slots=True)
class ProductCard:
    """Everything the interface renders for one recommendation."""

    parent_asin: str
    title: str
    store: str
    price: float | None
    average_rating: float | None
    rating_number: int
    categories: tuple[str, ...]
    features: tuple[str, ...]
    description: str
    matched: tuple[tuple[str, str, bool], ...] = field(default=())

    @property
    def category_path(self) -> str:
        return " › ".join(self.categories)

    def as_dict(self) -> dict[str, object]:
        return {
            "parent_asin": self.parent_asin,
            "title": self.title,
            "store": self.store,
            "price": self.price,
            "average_rating": self.average_rating,
            "rating_number": self.rating_number,
            "categories": list(self.categories),
            "category_path": self.category_path,
            "features": list(self.features),
            "description": self.description,
            "matched": [
                {"term": term, "field": name, "stale": stale}
                for term, name, stale in self.matched
            ],
        }


class CatalogView:
    """Byte-offset backed reader for catalog display fields.

    Construction is cheap; the offset pass runs on first use so a caller that
    never renders a card never pays for it.
    """

    def __init__(self, catalog_path: str | Path, *, max_features: int = 4) -> None:
        self.catalog_path = Path(catalog_path)
        self.max_features = max(0, int(max_features))
        self._offsets: dict[str, int] | None = None
        self._category_counts: Counter[str] | None = None
        self._category_aliases: Counter[str] | None = None
        self._audience_counts: Counter[str] | None = None

    # -- index ---------------------------------------------------------------

    @property
    def offsets(self) -> Mapping[str, int]:
        if self._offsets is None:
            self._build_offsets()
        assert self._offsets is not None
        return self._offsets

    def _build_offsets(self) -> None:
        """Record where each product line starts, and count leaf categories.

        Binary mode is required: `tell()` on a text-mode handle being iterated
        does not report a usable byte position, and the offsets must be exact
        for the later `seek`.
        """
        offsets: dict[str, int] = {}
        counts: Counter[str] = Counter()
        aliases: Counter[str] = Counter()
        audiences: Counter[str] = Counter()
        with self.catalog_path.open("rb") as handle:
            position = 0
            for raw in handle:
                start = position
                position += len(raw)
                if not raw.strip():
                    continue
                # Scanning for the identifier is what makes this pass cheap; a
                # full json.loads of every line would cost roughly a minute on
                # the released catalog and defeat the point of the index.
                found = _PARENT_ASIN_RE.search(raw)
                if found is None:
                    continue
                parent_asin = found.group(1).decode("utf-8", "replace")
                offsets.setdefault(parent_asin, start)
                array = _CATEGORIES_RE.search(raw)
                if array is not None:
                    path = _QUOTED_RE.findall(array.group(1))
                    # Only a leaf deep enough to be a shopping intent counts. A
                    # depth-two path is barely more specific than the catalog
                    # root -- the released data has 1136 products filed directly
                    # under "Westlake", which is a real category and a useless
                    # suggestion. Depth generalises; naming the shallow ones
                    # would hold for this catalog only.
                    if len(path) >= _MIN_SUGGESTION_DEPTH:
                        counts[path[-1].decode("utf-8", "replace")] += 1
                    if len(path) > 1:
                        audience = " ".join(
                            query_terms(path[1].decode("utf-8", "replace"), limit=6)
                        )
                        if audience:
                            audiences[audience] += 1
                    # Nodes below root and department are product types rather
                    # than audience labels.  Their words form the active
                    # catalog taxonomy used by journey routing, so a swapped
                    # catalog changes what the planner understands without a
                    # maintained list of product nouns.
                    for raw_name in path[2:]:
                        name = raw_name.decode("utf-8", "replace")
                        for alias in _category_aliases(name):
                            aliases[alias] += 1
        self._offsets = offsets
        self._category_counts = counts
        self._category_aliases = aliases
        self._audience_counts = audiences

    @property
    def product_count(self) -> int:
        return len(self.offsets)

    # -- records -------------------------------------------------------------

    def raw(self, parent_asin: str) -> dict[str, object] | None:
        """The catalog record for one identifier, or ``None`` if absent.

        An unknown identifier is a legitimate state, not an error: the catalog
        the interface reads and the catalog the agent was built against are
        supplied separately and a caller may point them at different files.
        """
        offset = self.offsets.get(str(parent_asin))
        if offset is None:
            return None
        with self.catalog_path.open("rb") as handle:
            handle.seek(offset)
            line = handle.readline()
        try:
            product = json.loads(line)
        except json.JSONDecodeError:
            return None
        return product if isinstance(product, dict) else None

    def card(
        self,
        parent_asin: str,
        *,
        terms: Sequence[str] = (),
        stale_terms: Iterable[str] = (),
    ) -> ProductCard:
        """A display record, degraded to identifier-only when the row is absent."""
        product = self.raw(parent_asin)
        if product is None:
            return ProductCard(
                parent_asin=str(parent_asin),
                title=str(parent_asin),
                store="",
                price=None,
                average_rating=None,
                rating_number=0,
                categories=(),
                features=(),
                description="",
            )
        categories = tuple(
            _tidy(value, 60) for value in _flatten_values(product.get("categories"))
        )
        features = tuple(
            text
            for value in _flatten_values(product.get("features"))
            if (text := _tidy(value, 120))
        )[: self.max_features]
        description = _tidy(" ".join(_flatten_values(product.get("description"))), 320)
        return ProductCard(
            parent_asin=str(product.get("parent_asin") or parent_asin),
            title=_tidy(product.get("title") or parent_asin, 200),
            store=_tidy(product.get("store") or "", 80),
            price=_coerce_price(product.get("price")),
            average_rating=_coerce_rating(product.get("average_rating")),
            rating_number=max(0, _coerce_int(product.get("rating_number"))),
            categories=categories,
            features=features,
            description=description,
            matched=self.matched_terms(product, terms, stale_terms=stale_terms),
        )

    def cards(
        self,
        parent_asins: Iterable[str],
        *,
        terms: Sequence[str] = (),
        stale_terms: Iterable[str] = (),
    ) -> list[ProductCard]:
        stale = frozenset(stale_terms)
        return [
            self.card(identifier, terms=terms, stale_terms=stale)
            for identifier in parent_asins
        ]

    # -- evidence ------------------------------------------------------------

    def matched_terms(
        self,
        product: Mapping[str, object],
        terms: Sequence[str],
        *,
        stale_terms: Iterable[str] = (),
    ) -> tuple[tuple[str, str, bool], ...]:
        """`(term, field, stale)` for each supplied term present in the product text.

        The first field carrying a term wins, in `CITED_FIELDS` order, so a word
        in the title is cited there rather than against the description that
        repeats it. Terms are compared after the same fold and tokenization
        retrieval applies, which is why an accented or differently-cased
        disclosure still shows as matched.

        `stale` marks a term the belief state has superseded but that is still
        in the text retrieval reads. Under `override_policy="retract_stated"`
        an override supersedes every constraint while deliberately keeping the
        replies the customer gave to our questions, so the two can legitimately
        disagree. Flagging it is the honest rendering: the alternative is a card
        citing a value the belief panel in the same view reports as dropped.
        """
        wanted = [term for term in dict.fromkeys(terms) if term]
        if not wanted:
            return ()
        stale = {fold_marks(term) for term in stale_terms}
        tokens_by_field = {
            name: set(query_terms(_text(product.get(name)), limit=4000))
            for name in CITED_FIELDS
        }
        found: list[tuple[str, str, bool]] = []
        for term in wanted:
            folded = fold_marks(term)
            for name in CITED_FIELDS:
                if folded in tokens_by_field[name]:
                    found.append((term, name, folded in stale))
                    break
        return tuple(found)

    # -- opening suggestions -------------------------------------------------

    def common_categories(self, count: int = 6) -> list[str]:
        """The most populated leaf categories, for opening suggestion chips.

        Read from the catalog rather than written down here, so the chips stay
        true if the catalog is swapped and cannot drift into advertising a
        category the corpus does not carry.
        """
        if self._category_counts is None:
            self._build_offsets()
        assert self._category_counts is not None
        return [name for name, _ in self._category_counts.most_common(max(0, int(count)))]

    def category_mentions(self, text: str, count: int = 4) -> list[str]:
        """Product-category phrases present in ``text``, longest first.

        The vocabulary is derived from the catalog category paths.  Singular
        variants are grammatical normalizations, not a hand-authored taxonomy.
        Overlapping hits collapse to the most specific phrase, so ``running
        shoes`` does not also open a second ``shoes`` line item.
        """

        if self._category_aliases is None:
            self._build_offsets()
        assert self._category_aliases is not None
        assert self._audience_counts is not None
        raw_tokens = re.findall(r"[a-z0-9]+", fold_marks(str(text)))
        message_units = [
            (token, position)
            for position, token in enumerate(raw_tokens)
            if query_terms(token, limit=1)
        ]
        message_tokens = [token for token, _ in message_units]
        if not message_tokens:
            return []
        matches: list[tuple[int, int, int, int, str]] = []
        for alias in self._category_aliases:
            # Audience nodes can recur deeper in inconsistent catalog paths;
            # they modify a line item and must never create one.
            if alias in self._audience_counts:
                continue
            alias_tokens = alias.split()
            width = len(alias_tokens)
            for start in range(len(message_tokens) - width + 1):
                if message_tokens[start : start + width] == alias_tokens:
                    end = start + width
                    matches.append(
                        (
                            start,
                            end,
                            message_units[start][1],
                            message_units[end - 1][1] + 1,
                            alias,
                        )
                    )
        matches.sort(key=lambda hit: (hit[0], -(hit[1] - hit[0]), hit[4]))

        # At one start position the longest catalog phrase wins.  Adjacent
        # category nodes form the phrase the customer actually used: the
        # catalog may store "Shoes > Running" while the utterance says
        # "running shoes".  Joining those two is safer than opening a line item
        # for each node.
        non_overlapping: list[tuple[int, int, int, int, str]] = []
        cursor = -1
        for start, end, raw_start, raw_end, alias in matches:
            if start < cursor:
                continue
            non_overlapping.append((start, end, raw_start, raw_end, alias))
            cursor = end
        merged: list[tuple[int, int, int, int]] = []
        for start, end, raw_start, raw_end, _ in non_overlapping:
            if merged and merged[-1][3] == raw_start:
                merged[-1] = (merged[-1][0], end, merged[-1][2], raw_end)
            else:
                merged.append((start, end, raw_start, raw_end))
        return [
            " ".join(message_tokens[start:end])
            for start, end, _, _ in merged[: max(0, int(count))]
        ]

    def audience_mentions(self, text: str, count: int = 2) -> list[str]:
        """Audience values named by the shopper, derived from catalog paths."""

        if self._audience_counts is None:
            self._build_offsets()
        assert self._audience_counts is not None
        tokens = query_terms(str(text), limit=100)
        found: list[tuple[int, int, str]] = []
        for audience in self._audience_counts:
            wanted = audience.split()
            width = len(wanted)
            for start in range(len(tokens) - width + 1):
                if tokens[start : start + width] == wanted:
                    found.append((start, -width, audience))
                    break
        return [
            audience
            for _, _, audience in sorted(found)[: max(0, int(count))]
        ]

    @staticmethod
    def audience(product: Mapping[str, object]) -> str:
        """The catalog's audience node, normalized for filtering/questions."""

        path = list(_flatten_values(product.get("categories")))
        if len(path) <= 1:
            return ""
        return " ".join(query_terms(str(path[1]), limit=6))


_PARENT_ASIN_RE = re.compile(rb'"parent_asin"\s*:\s*"([^"]+)"')
# The last string in the categories array is the leaf. Bounded to the array so a
# later field containing a bracket cannot be read as a category.
_CATEGORIES_RE = re.compile(rb'"categories"\s*:\s*\[([^\]]*)\]')
_QUOTED_RE = re.compile(rb'"([^"]+)"')

# Root plus a department plus a leaf. Below that the leaf is not a thing a
# person shops for.
_MIN_SUGGESTION_DEPTH = 3


def _category_aliases(name: str) -> tuple[str, ...]:
    """Catalog category plus conservative singular surface variants."""

    words = query_terms(name, limit=12)
    if not words:
        return ()

    def singular(word: str) -> str:
        if word.endswith("ies") and len(word) > 4:
            return f"{word[:-3]}y"
        if word.endswith("sses"):
            return word[:-2]
        if word.endswith("es") and len(word) > 4:
            return word[:-2]
        if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
            return word[:-1]
        return word

    aliases = [" ".join(words)]
    singular_words = [singular(word) for word in words]
    aliases.append(" ".join(singular_words))
    # A category such as "Suits & Sport Coats" must still understand the
    # ordinary request "suit".  Restrict single-word aliases to substantial
    # words; frequency and overlap handling above resolve shared nodes.
    aliases.extend(
        singular_word
        for original, singular_word in zip(words, singular_words)
        if len(singular_word) >= 4
        and original.endswith("s")
        and singular_word != original
    )
    return tuple(dict.fromkeys(alias for alias in aliases if alias))


def _coerce_price(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        price = float(value)
        return price if price > 0 else None
    # Catalog prices are numeric where present, but a string like "$27.99" costs
    # one regex to accept and would otherwise silently drop the price.
    digits = re.search(r"\d+(?:\.\d+)?", str(value))
    if digits is None:
        return None
    try:
        price = float(digits.group(0))
    except ValueError:
        return None
    return price if price > 0 else None


def _coerce_rating(value: object) -> float | None:
    try:
        rating = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return rating if 0.0 < rating <= 5.0 else None


def _coerce_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
