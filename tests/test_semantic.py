from __future__ import annotations

import unittest

from needle.contracts import Candidate
from needle.semantic import NoOpSemanticReranker


class NoOpSemanticRerankerTest(unittest.TestCase):
    def test_preserves_candidate_order_and_values(self) -> None:
        candidates = [Candidate("first", 2.0), Candidate("second", 1.0)]
        self.assertEqual(NoOpSemanticReranker().rerank(candidates, "query"), candidates)


if __name__ == "__main__":
    unittest.main()
