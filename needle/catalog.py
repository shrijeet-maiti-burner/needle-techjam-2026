from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import unicodedata
from collections.abc import Iterable, Sequence
from pathlib import Path

from needle.contracts import Candidate


TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
SIGNATURE_MARKER_RE = re.compile(
    r"(?:key requirement is|what matters is|what i need is)\s*:\s*(.+)",
    re.IGNORECASE,
)
MATERIAL_RE = re.compile(
    r"\b(cotton|polyester|nylon|leather|wool|spandex|silk|rayon|fabric)\b",
    re.IGNORECASE,
)
COLOR_RE = re.compile(
    r"\b(black|white|blue|red|pink|green|brown|gray|grey|purple|yellow|orange)\b",
    re.IGNORECASE,
)

SEARCH_FIELDS = (
    "title",
    "categories",
    "features",
    "details",
    "store",
    "description",
)
DEFAULT_FIELD_WEIGHTS = (6.0, 4.0, 2.5, 2.5, 1.5, 1.0)
RETRIEVAL_MODES = frozenset({"sparse", "signature_first"})
QUERY_MODES = frozenset({"any", "all"})
SIGNATURE_INDEX_SCHEMA_VERSION = "1"

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "please",
        "some",
        "that",
        "the",
        "this",
        "to",
        "want",
        "with",
        "would",
        "you",
        "looking",
    }
)


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {item}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def _flatten_values(value: object) -> list[str]:
    if isinstance(value, dict):
        return [f"{key}: {item}" for key, item in value.items() if item not in (None, "", [])]
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)] if value not in (None, "") else []


def _clean_constraint(value: object, limit: int = 180) -> str:
    return re.sub(r"\s+", " ", str(value)).strip(" -;,.\t\n")[:limit].rstrip()


def canonical_signature(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", _clean_constraint(value).casefold())
    without_marks = "".join(character for character in normalized if not unicodedata.combining(character))
    return " ".join(TOKEN_RE.findall(without_marks))


def query_terms(text: str, limit: int = 60) -> list[str]:
    terms = (
        token.lower()
        for token in TOKEN_RE.findall(text)
        if len(token) > 1 and token.lower() not in STOPWORDS
    )
    return list(dict.fromkeys(terms))[:limit]


def extract_query_signatures(messages: Iterable[str]) -> tuple[str, ...]:
    """Extract catalog-grounded fragments from released-style dialogue.

    This deliberately recognizes only explicit value-bearing clauses and the
    small material/color vocabulary. It is a high-precision experiment arm,
    not a general semantic parser; sparse retrieval remains the fallback.
    """

    signatures: list[str] = []
    for message in messages:
        marker = SIGNATURE_MARKER_RE.search(message)
        if marker:
            # The released customer separates constraints with semicolons,
            # but catalog features can contain them too. Only the first span
            # is structurally unambiguous. Later spans remain available to
            # sparse retrieval instead of becoming unsafe exact evidence.
            signature = canonical_signature(marker.group(1).split(";", 1)[0])
            if signature:
                signatures.append(signature)

        material = MATERIAL_RE.search(message)
        if material:
            signatures.append(canonical_signature(material.group(1)))
        color = COLOR_RE.search(message)
        if color:
            signatures.append(canonical_signature(f"color: {color.group(1)}"))
    return tuple(dict.fromkeys(signatures))


def product_signatures(product: dict[str, object]) -> tuple[str, ...]:
    searchable = " ".join(_text(product.get(field)) for field in SEARCH_FIELDS)
    values: list[object] = [
        *_flatten_values(product.get("features")),
        *_flatten_values(product.get("details")),
    ]
    material = MATERIAL_RE.search(searchable)
    if material:
        values.insert(0, material.group(1).lower())
    color = COLOR_RE.search(searchable)
    if color:
        values.insert(1, f"color: {color.group(1).lower()}")
    if product.get("price") not in (None, ""):
        values.append(f"budget around ${product['price']}")
    return tuple(
        dict.fromkeys(
            signature
            for value in values
            if (signature := canonical_signature(value))
        )
    )


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_signature_index(catalog_path: str | Path, output_path: str | Path) -> dict[str, object]:
    """Build a catalog-bound exact-signature asset without public labels."""

    catalog = Path(catalog_path).resolve()
    output = Path(output_path).resolve()
    if not catalog.is_file():
        raise FileNotFoundError(f"catalog not found: {catalog}")
    if output.exists():
        raise FileExistsError(f"signature index already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    if temporary.exists():
        raise FileExistsError(f"temporary signature index already exists: {temporary}")

    connection = sqlite3.connect(temporary)
    product_count = 0
    signature_count = 0
    seen: set[str] = set()
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute(
            "CREATE TABLE signatures("
            "signature TEXT NOT NULL, parent_asin TEXT NOT NULL, "
            "PRIMARY KEY(signature, parent_asin)) WITHOUT ROWID"
        )
        batch: list[tuple[str, str]] = []
        with catalog.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                product = json.loads(line)
                parent_asin = str(product.get("parent_asin") or "").strip()
                if not parent_asin:
                    raise ValueError(f"missing parent_asin at catalog line {line_number}")
                if parent_asin in seen:
                    raise ValueError(f"duplicate parent_asin in catalog: {parent_asin}")
                seen.add(parent_asin)
                product_count += 1
                for signature in product_signatures(product):
                    batch.append((signature, parent_asin))
                if len(batch) >= 5_000:
                    connection.executemany("INSERT INTO signatures VALUES (?, ?)", batch)
                    signature_count += len(batch)
                    batch.clear()
        if batch:
            connection.executemany("INSERT INTO signatures VALUES (?, ?)", batch)
            signature_count += len(batch)
        metadata = {
            "schema_version": SIGNATURE_INDEX_SCHEMA_VERSION,
            "catalog_sha256": sha256_file(catalog),
            "product_count": str(product_count),
            "signature_count": str(signature_count),
        }
        connection.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
        connection.commit()
        connection.execute("VACUUM")
    except BaseException:
        connection.close()
        if temporary.exists():
            temporary.unlink()
        raise
    connection.close()
    temporary.replace(output)
    return {
        "path": str(output),
        "sha256": sha256_file(output),
        "size_bytes": output.stat().st_size,
        "catalog_sha256": metadata["catalog_sha256"],
        "product_count": product_count,
        "signature_count": signature_count,
    }


class CatalogIndex:
    """Validated in-memory lexical index with isolated experiment controls."""

    def __init__(
        self,
        catalog_path: str | Path,
        *,
        retrieval_mode: str = "sparse",
        query_mode: str = "any",
        field_weights: Sequence[float] = DEFAULT_FIELD_WEIGHTS,
        popularity_strength: float = 0.0,
        signature_bucket_limit: int = 100,
        signature_index_path: str | Path | None = None,
    ) -> None:
        if retrieval_mode not in RETRIEVAL_MODES:
            raise ValueError(f"unsupported retrieval mode: {retrieval_mode}")
        if query_mode not in QUERY_MODES:
            raise ValueError(f"unsupported query mode: {query_mode}")
        if len(field_weights) != len(SEARCH_FIELDS):
            raise ValueError(f"field_weights must contain {len(SEARCH_FIELDS)} values")
        parsed_weights = tuple(float(value) for value in field_weights)
        if any(not math.isfinite(value) or value < 0 for value in parsed_weights):
            raise ValueError("field_weights must be finite and non-negative")
        if not math.isfinite(popularity_strength) or not 0.0 <= popularity_strength <= 1.0:
            raise ValueError("popularity_strength must be between 0 and 1")
        if not 1 <= int(signature_bucket_limit) <= 50_000:
            raise ValueError("signature_bucket_limit must be in 1..50000")
        if signature_index_path is not None and retrieval_mode != "signature_first":
            raise ValueError("signature_index_path requires retrieval_mode='signature_first'")

        self.catalog_path = Path(catalog_path)
        if not self.catalog_path.is_file():
            raise FileNotFoundError(f"catalog not found: {self.catalog_path}")
        self.retrieval_mode = retrieval_mode
        self.query_mode = query_mode
        self.field_weights = parsed_weights
        self.popularity_strength = float(popularity_strength)
        self.signature_bucket_limit = int(signature_bucket_limit)
        self.signature_index_path = (
            Path(signature_index_path).expanduser().resolve()
            if signature_index_path is not None
            else None
        )
        self.connection = sqlite3.connect(":memory:")
        self._external_signature_connection: sqlite3.Connection | None = None
        self._signature_count_cache: dict[str, int] = {}
        self.product_count = 0
        self._rating_numbers: dict[str, int] = {}
        self._max_log_rating = 1.0
        self._build()
        if self.signature_index_path is not None:
            self._open_signature_index()

    def _build(self) -> None:
        cursor = self.connection.cursor()
        cursor.execute(
            "CREATE VIRTUAL TABLE products USING fts5("
            "parent_asin UNINDEXED, title, categories, features, details, store, description, "
            "rating_number UNINDEXED, tokenize='unicode61 remove_diacritics 2')"
        )
        if self.retrieval_mode == "signature_first" and self.signature_index_path is None:
            cursor.execute(
                "CREATE TABLE signatures("
                "signature TEXT NOT NULL, parent_asin TEXT NOT NULL, "
                "PRIMARY KEY(signature, parent_asin)) WITHOUT ROWID"
            )
        seen: set[str] = set()
        batch: list[tuple[str, str, str, str, str, str, str, int]] = []
        signature_batch: list[tuple[str, str]] = []
        with self.catalog_path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                product = json.loads(line)
                parent_asin = str(product.get("parent_asin") or "").strip()
                if not parent_asin:
                    raise ValueError(f"missing parent_asin at catalog line {line_number}")
                if parent_asin in seen:
                    raise ValueError(f"duplicate parent_asin in catalog: {parent_asin}")
                seen.add(parent_asin)
                rating_number = max(0, int(product.get("rating_number") or 0))
                self._rating_numbers[parent_asin] = rating_number
                batch.append(
                    (
                        parent_asin,
                        _text(product.get("title")),
                        _text(product.get("categories")),
                        _text(product.get("features")),
                        _text(product.get("details")),
                        _text(product.get("store")),
                        _text(product.get("description")),
                        rating_number,
                    )
                )
                if self.retrieval_mode == "signature_first" and self.signature_index_path is None:
                    signature_batch.extend(
                        (signature, parent_asin)
                        for signature in product_signatures(product)
                    )
                if len(batch) >= 1_000:
                    cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?)", batch)
                    batch.clear()
                    if signature_batch:
                        cursor.executemany("INSERT INTO signatures VALUES (?, ?)", signature_batch)
                        signature_batch.clear()
        if batch:
            cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?)", batch)
        if signature_batch:
            cursor.executemany("INSERT INTO signatures VALUES (?, ?)", signature_batch)
        self.connection.commit()
        self.product_count = len(seen)
        if self.product_count == 0:
            raise ValueError("catalog is empty")
        self._max_log_rating = max(
            (math.log1p(value) for value in self._rating_numbers.values()),
            default=1.0,
        ) or 1.0

    def _open_signature_index(self) -> None:
        assert self.signature_index_path is not None
        if not self.signature_index_path.is_file():
            raise FileNotFoundError(f"signature index not found: {self.signature_index_path}")
        uri = f"file:{self.signature_index_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        except sqlite3.DatabaseError:
            connection.close()
            raise
        expected = {
            "schema_version": SIGNATURE_INDEX_SCHEMA_VERSION,
            "catalog_sha256": sha256_file(self.catalog_path),
            "product_count": str(self.product_count),
        }
        mismatches = [
            key
            for key, expected_value in expected.items()
            if metadata.get(key) != expected_value
        ]
        if mismatches:
            connection.close()
            raise ValueError(f"signature index metadata mismatch: {', '.join(mismatches)}")
        connection.execute("PRAGMA query_only=ON")
        self._external_signature_connection = connection

    @property
    def _signature_connection(self) -> sqlite3.Connection:
        return self._external_signature_connection or self.connection

    def _signature_count(self, signature: str) -> int:
        cached = self._signature_count_cache.get(signature)
        if cached is not None:
            return cached
        row = self._signature_connection.execute(
            "SELECT COUNT(*) FROM signatures WHERE signature = ?",
            (signature,),
        ).fetchone()
        count = int(row[0]) if row is not None else 0
        self._signature_count_cache[signature] = count
        return count

    def _signature_rows(self, signatures: Sequence[str], limit: int) -> list[tuple[str]]:
        ordered = sorted(dict.fromkeys(signatures), key=lambda value: (self._signature_count(value), value))
        if not ordered or self._signature_count(ordered[0]) == 0:
            return []
        joins = " ".join(
            f"JOIN signatures AS s{index} "
            f"ON s{index}.parent_asin = s0.parent_asin AND s{index}.signature = ?"
            for index in range(1, len(ordered))
        )
        query = (
            f"SELECT s0.parent_asin FROM signatures AS s0 {joins} "
            "WHERE s0.signature = ? ORDER BY s0.parent_asin ASC LIMIT ?"
        )
        return self._signature_connection.execute(
            query,
            (*ordered[1:], ordered[0], limit),
        ).fetchall()

    def signature_candidates(
        self,
        messages: Iterable[str],
        *,
        limit: int | None = None,
    ) -> tuple[tuple[str, ...], frozenset[str]]:
        """Return a bounded intersection over exact catalog signatures.

        Signatures live in a compact SQLite table rather than a duplicate
        Python object graph. A limit fetches one extra row so callers can
        distinguish an eligible bucket from one that exceeds their promotion
        threshold.
        """

        if self.retrieval_mode != "signature_first":
            return (), frozenset()
        matched: list[str] = []
        for signature in extract_query_signatures(messages):
            proposed = [*matched, signature]
            if self._signature_rows(proposed, 1):
                matched.append(signature)
        if not matched:
            return (), frozenset()
        fetch_limit = self.product_count if limit is None else max(0, int(limit)) + 1
        rows = self._signature_rows(matched, fetch_limit)
        return tuple(matched), frozenset(str(row[0]) for row in rows)

    def _sparse_rows(self, text: str, limit: int) -> list[tuple[str, float]]:
        terms = query_terms(text)
        if limit == 0 or not terms:
            return []
        operator = " OR " if self.query_mode == "any" else " AND "
        expression = operator.join(f'"{term}"' for term in terms)
        weights = ", ".join(str(value) for value in (0.0, *self.field_weights, 0.0))
        rows = self.connection.execute(
            f"SELECT parent_asin, bm25(products, {weights}) AS rank "
            "FROM products WHERE products MATCH ? ORDER BY rank ASC, parent_asin ASC LIMIT ?",
            (expression, limit),
        ).fetchall()
        return [(str(parent_asin), -float(rank)) for parent_asin, rank in rows]

    def _popularity_prior(self, parent_asin: str) -> float:
        return math.log1p(self._rating_numbers[parent_asin]) / self._max_log_rating

    def _rerank_with_popularity(self, rows: list[tuple[str, float]]) -> list[tuple[str, float]]:
        if self.popularity_strength == 0.0 or len(rows) < 2:
            return rows
        scores = [score for _, score in rows]
        low, high = min(scores), max(scores)
        span = high - low

        def combined(item: tuple[str, float]) -> tuple[float, float, str]:
            parent_asin, sparse_score = item
            relevance = 1.0 if span == 0.0 else (sparse_score - low) / span
            value = relevance + self.popularity_strength * self._popularity_prior(parent_asin)
            return (-value, -sparse_score, parent_asin)

        return sorted(rows, key=combined)

    def search(
        self,
        text: str,
        limit: int,
        *,
        messages: Iterable[str] = (),
        excluded_ids: Iterable[str] = (),
    ) -> list[Candidate]:
        bounded_limit = max(0, min(int(limit), 500))
        if bounded_limit == 0:
            return []
        excluded = frozenset(excluded_ids)
        fetch_limit = min(50_000, bounded_limit + len(excluded) + 200)
        sparse_rows = self._rerank_with_popularity(self._sparse_rows(text, fetch_limit))
        sparse_scores = dict(sparse_rows)

        ordered: list[tuple[str, float]] = []
        if self.retrieval_mode == "signature_first":
            _, exact_ids = self.signature_candidates(messages, limit=self.signature_bucket_limit)
            if 0 < len(exact_ids) <= self.signature_bucket_limit:
                sparse_positions = {parent_asin: index for index, (parent_asin, _) in enumerate(sparse_rows)}
                exact_order = sorted(
                    exact_ids,
                    key=lambda parent_asin: (
                        sparse_positions.get(parent_asin, len(sparse_positions)),
                        -self._popularity_prior(parent_asin),
                        parent_asin,
                    ),
                )
                ordered.extend((parent_asin, sparse_scores.get(parent_asin, 0.0)) for parent_asin in exact_order)

        already_ordered = {parent_asin for parent_asin, _ in ordered}
        ordered.extend(row for row in sparse_rows if row[0] not in already_ordered)
        return [
            Candidate(parent_asin=parent_asin, sparse_score=sparse_score)
            for parent_asin, sparse_score in ordered
            if parent_asin not in excluded
        ][:bounded_limit]
