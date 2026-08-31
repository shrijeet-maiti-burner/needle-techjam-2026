"""`Agent.respond` must never raise, whatever the harness passes.

`local_evaluator.evaluate` wraps `respond` in `except Exception` and substitutes
`{"message": "", "ask_attribute": None, "recommendations": []}`. That costs more
than the turn: a None `ask_attribute` makes the simulated customer reply "Ask me
about one specific attribute" and disclose nothing, for every remaining turn. An
exception on turn one forfeits the session. These tests pin the guard.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from needle.agent import Agent
from needle.contracts import ALLOWED_ASK_ATTRIBUTES


PRODUCTS = [
    {
        "parent_asin": f"B{index:06d}",
        "title": "black cotton running shoe",
        "features": ["Cloudsoft cotton"],
        "details": {"Color": "Black"},
        "description": "road running trainer",
        "categories": ["Shoes", "Running"],
        "store": "Example",
        "rating_number": index,
    }
    for index in range(30)
]


def _assert_contract_valid(case: unittest.TestCase, response: object) -> list[str]:
    """Every rule the official normalizer and schema enforce."""
    case.assertIsInstance(response, dict)
    assert isinstance(response, dict)
    case.assertLessEqual(set(response), {"message", "ask_attribute", "recommendations", "usage"})
    case.assertIn("message", response)
    case.assertIsInstance(response["message"], str)

    ask_attribute = response.get("ask_attribute")
    if ask_attribute is not None:
        case.assertIn(ask_attribute, ALLOWED_ASK_ATTRIBUTES)

    recommendations = response.get("recommendations")
    case.assertIsInstance(recommendations, list)
    assert isinstance(recommendations, list)
    case.assertLessEqual(len(recommendations), 10)
    identifiers: list[str] = []
    for item in recommendations:
        case.assertIsInstance(item, dict)
        parent_asin = item.get("parent_asin")
        case.assertIsInstance(parent_asin, str)
        case.assertTrue(parent_asin)
        identifiers.append(parent_asin)
    case.assertEqual(len(identifiers), len(set(identifiers)), "recommendations must be unique")

    usage = response.get("usage")
    if usage is not None:
        case.assertEqual(set(usage), {"prompt_tokens", "completion_tokens"})
        for value in usage.values():
            case.assertIsInstance(value, int)
            case.assertGreaterEqual(value, 0)
    return identifiers


class RespondResilience(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.catalog_path = Path(directory.name) / "catalog.jsonl"
        self.catalog_path.write_text(
            "".join(json.dumps(product) + "\n" for product in PRODUCTS),
            encoding="utf-8",
        )
        self.agent = Agent(self.catalog_path)
        self.addCleanup(self.agent.close)
        self.catalog_ids = {product["parent_asin"] for product in PRODUCTS}

    # -- the abusive-input matrix ------------------------------------------ #

    def test_respond_never_raises(self) -> None:
        self.agent.reset("session", {})
        self.agent.respond("session", "black cotton running shoes", 1, 10)

        cases: list[tuple[str, tuple[object, object, object, object]]] = [
            ("replayed turn", ("session", "black shoes", 1, 10)),
            ("turn zero", ("session", "black shoes", 0, 10)),
            ("turn above ten", ("session", "black shoes", 11, 10)),
            ("turn skips ahead", ("session", "black shoes", 9, 10)),
            ("never reset", ("unknown-session", "black shoes", 1, 10)),
            ("empty session id", ("", "black shoes", 1, 10)),
            ("message is None", ("session", None, 4, 10)),
            ("message is bytes", ("session", b"black shoes", 5, 10)),
            ("message is empty", ("session", "", 6, 10)),
            ("message is whitespace", ("session", "   \t\n", 7, 10)),
            ("turn is a string", ("session", "black shoes", "abc", 10)),
            ("turn is None", ("session", "black shoes", None, 10)),
            ("top_k is None", ("session", "black shoes", 8, None)),
            ("top_k is negative", ("session", "black shoes", 8, -5)),
            ("top_k is huge", ("session", "black shoes", 8, 10_000)),
            ("top_k is a string", ("session", "black shoes", 8, "ten")),
            ("all arguments wrong", (None, None, None, None)),
            # `int()` rejects an unusable value three ways, and only two were
            # caught. NaN is a ValueError and was already covered; an infinity
            # is an OverflowError and escaped, which is the one a float carries.
            ("turn is infinity", ("session", "black shoes", float("inf"), 10)),
            ("turn is negative infinity", ("session", "black shoes", float("-inf"), 10)),
            ("turn is NaN", ("session", "black shoes", float("nan"), 10)),
            ("top_k is infinity", ("session", "black shoes", 8, float("inf"))),
            ("top_k is NaN", ("session", "black shoes", 8, float("nan"))),
        ]
        for label, arguments in cases:
            with self.subTest(case=label):
                try:
                    response = self.agent.respond(*arguments)  # type: ignore[arg-type]
                except Exception as error:  # noqa: BLE001 - that is the failure
                    self.fail(f"{label} raised {type(error).__name__}: {error}")
                identifiers = _assert_contract_valid(self, response)
                for parent_asin in identifiers:
                    self.assertIn(parent_asin, self.catalog_ids, f"{label} invented an id")

    def test_an_unusable_top_k_still_fills_the_slate(self) -> None:
        """An unusable bound must mean "the contract's ten", never "nothing".

        `_bounded_limit` already documents that intent. Before `OverflowError`
        was caught, an infinite `top_k` raised past it into
        `_degraded_response`, which caught the exception and returned an empty
        slate -- contract-valid, and scored as an ordinary miss.
        """
        self.agent.reset("bounds", {})
        for label, top_k in (("infinity", float("inf")), ("NaN", float("nan"))):
            with self.subTest(top_k=label):
                response = self.agent.respond("bounds", "black shoes", 1, top_k)
                self.assertTrue(
                    response["recommendations"],
                    f"an unusable top_k ({label}) emptied the slate",
                )

    def test_hostile_message_content_is_survivable(self) -> None:
        """FTS5 is a query language; user text reaches it as terms."""
        self.agent.reset("hostile", {})
        payloads = [
            'shoes" OR products MATCH "x',
            "shoes AND NOT shoes",
            "shoes NEAR/2 (cotton",
            "*" * 200,
            "'; DROP TABLE products; --",
            "^black shirt$",
            "\x00\x01\x02 shoes",
            "🙂👟 running shoes",
            "shoes " * 500,
        ]
        for index, payload in enumerate(payloads, start=1):
            with self.subTest(payload=payload[:24]):
                response = self.agent.respond("hostile", payload, min(index, 10), 10)
                _assert_contract_valid(self, response)

    # -- the guard must not mask a healthy path ---------------------------- #

    def test_a_healthy_session_records_no_failures(self) -> None:
        self.agent.reset("clean", {})
        for turn in range(1, 11):
            response = self.agent.respond("clean", "black cotton running shoes", turn, 10)
            _assert_contract_valid(self, response)
        self.assertEqual(self.agent.respond_failures, [])

    def test_degradation_is_recorded_not_silent(self) -> None:
        self.agent.respond("never-reset", "black shoes", 1, 10)
        self.assertEqual(len(self.agent.respond_failures), 1)
        self.assertIn("reset must be called", self.agent.respond_failures[0])

    def test_degraded_turn_still_asks_and_still_recommends(self) -> None:
        """A degraded turn must keep the information channel open: an empty
        `ask_attribute` wastes the customer reply, which is the only channel."""
        response = self.agent.respond("never-reset", "black cotton running shoes", 1, 10)
        self.assertEqual(response["ask_attribute"], "other")
        self.assertTrue(response["recommendations"], "degraded turn returned nothing")

    def test_final_turn_stops_asking_even_when_degraded(self) -> None:
        response = self.agent.respond("never-reset", "black shoes", 10, 10)
        self.assertIsNone(response["ask_attribute"])


class ResourceLifecycle(unittest.TestCase):
    """`close()` exists so a caller can replace or delete the catalog and the
    signature asset; on Windows an open handle locks the file."""

    def _catalog(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "catalog.jsonl"
        path.write_text(
            "".join(json.dumps(product) + "\n" for product in PRODUCTS),
            encoding="utf-8",
        )
        return path

    def test_close_is_idempotent(self) -> None:
        agent = Agent(self._catalog())
        agent.close()
        agent.close()

    def test_agent_is_a_context_manager(self) -> None:
        with Agent(self._catalog()) as agent:
            agent.reset("session", {})
            _assert_contract_valid(self, agent.respond("session", "black shoes", 1, 10))

    def test_catalog_index_is_a_context_manager(self) -> None:
        from needle.catalog import CatalogIndex

        with CatalogIndex(self._catalog()) as index:
            self.assertEqual(index.product_count, len(PRODUCTS))


if __name__ == "__main__":
    unittest.main()
