from __future__ import annotations

import unittest

from needle.evaluation import ContractCheckingAgent, validate_response


class FakeAgent:
    def reset(self, session_id: str, user_profile: dict) -> None:
        del session_id, user_profile

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        del session_id, user_message, turn, top_k
        return {
            "message": "question",
            "ask_attribute": "material",
            "recommendations": [{"parent_asin": "KNOWN"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }


class ContractValidationTest(unittest.TestCase):
    def test_accepts_strict_response(self) -> None:
        response = FakeAgent().respond("session", "message", 1, 10)
        self.assertEqual(validate_response(response, {"KNOWN"}), [])

    def test_reports_duplicate_unknown_and_extra_fields(self) -> None:
        response = {
            "message": "question",
            "ask_attribute": "not_allowed",
            "recommendations": [
                {"parent_asin": "UNKNOWN", "extra": True},
                {"parent_asin": "UNKNOWN"},
            ],
            "unexpected": True,
        }
        violations = validate_response(response, {"KNOWN"})
        combined = "\n".join(violations)
        self.assertIn("unknown response keys", combined)
        self.assertIn("invalid ask_attribute", combined)
        self.assertIn("unknown parent_asin", combined)
        self.assertIn("duplicate parent_asin", combined)

    def test_malformed_values_are_recorded_without_crashing_validator(self) -> None:
        response = {
            "message": "question",
            "ask_attribute": ["material"],
            "recommendations": [
                {"parent_asin": "KNOWN", "score": float("nan"), 7: "unexpected"},
            ],
            9: "unexpected",
        }
        combined = "\n".join(validate_response(response, {"KNOWN"}))
        self.assertIn("invalid ask_attribute", combined)
        self.assertIn("unknown response keys", combined)
        self.assertIn("unknown keys", combined)
        self.assertIn("score is not numeric", combined)

    def test_proxy_records_latency_and_response_count(self) -> None:
        proxy = ContractCheckingAgent(FakeAgent(), {"KNOWN"})
        proxy.reset("session", {})
        proxy.respond("session", "message", 1, 10)
        report = proxy.report.as_dict()
        self.assertTrue(report["passed"])
        self.assertEqual(report["response_count"], 1)
        self.assertIsNotNone(report["latency_ms"]["p95"])


if __name__ == "__main__":
    unittest.main()
