import json
import tempfile
import unittest
from pathlib import Path

import submission.agent as submission_agent
import starter.agent as starter_agent
from needle.presets import PRIMARY_AGENT_KWARGS


ALLOWED_ATTRIBUTES = {
    "category", "material", "color", "size", "style", "brand",
    "budget", "feature", "use_case", "other",
}


class SubmissionEntryPoint(unittest.TestCase):
    """The bundled asset is gitignored, so nothing previously constructed the
    documented entry point. These run it without the asset present, which is
    exactly the state of a fresh clone."""

    def catalog(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "catalog.jsonl"
        products = [
            {"parent_asin": f"B{index:06d}", "title": "running shoe",
             "features": ["Cloudsoft cotton"], "rating_number": index}
            for index in range(25)
        ]
        path.write_text(
            "".join(json.dumps(product) + "\n" for product in products),
            encoding="utf-8",
        )
        return path

    def test_exports_agent(self) -> None:
        self.assertTrue(hasattr(submission_agent, "Agent"))
        self.assertIn("Agent", submission_agent.__all__)

    def test_starter_prefers_a_present_bundled_asset(self) -> None:
        expected = (
            starter_agent.BUNDLED_INDEX
            if starter_agent.BUNDLED_INDEX.is_file()
            else starter_agent.DEVELOPMENT_INDEX
        )
        self.assertEqual(starter_agent.DEFAULT_INDEX, expected)

    def test_constructs_without_the_bundled_asset(self) -> None:
        agent = submission_agent.Agent(catalog_path=self.catalog())
        self.assertIsNotNone(agent.catalog.signature_index_fallback)

    def test_honours_the_official_contract(self) -> None:
        agent = submission_agent.Agent(catalog_path=self.catalog())
        agent.reset("session", {})
        response = agent.respond("session", "I'm looking for running shoes.", 1, 10)

        self.assertIsInstance(response["message"], str)
        self.assertIn(response["ask_attribute"], ALLOWED_ATTRIBUTES | {None})
        asins = [item["parent_asin"] for item in response["recommendations"]]
        self.assertLessEqual(len(asins), 10)
        self.assertEqual(len(asins), len(set(asins)), "recommendations must be unique")
        usage = response["usage"]
        self.assertGreaterEqual(usage["prompt_tokens"], 0)
        self.assertGreaterEqual(usage["completion_tokens"], 0)

    def test_accepts_a_positional_catalog_like_the_official_harness(self) -> None:
        """local_evaluator constructs Agent(args.catalog) positionally."""
        agent = submission_agent.Agent(self.catalog())
        agent.reset("session", {})
        self.assertIsInstance(agent.respond("session", "shoes", 1, 10), dict)

    def test_uses_the_selected_primary_preset(self) -> None:
        agent = submission_agent.Agent(catalog_path=self.catalog())
        configured = agent.experiment_configuration
        for key, value in PRIMARY_AGENT_KWARGS.items():
            if key in configured:
                self.assertEqual(configured[key], value, f"{key} drifted from the preset")


if __name__ == "__main__":
    unittest.main()
