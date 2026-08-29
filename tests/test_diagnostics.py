from __future__ import annotations

import unittest

from needle.diagnostics import PerturbedAgent, surface_noise, template_paraphrase


class PerturbationTest(unittest.TestCase):
    def test_surface_noise_changes_form_but_not_words(self) -> None:
        transformed = surface_noise("Café-blue; cotton.")
        self.assertIn("CAFE", transformed)
        self.assertIn("COTTON", transformed)
        self.assertNotIn(";", transformed)

    def test_template_paraphrase_removes_released_markers(self) -> None:
        transformed = template_paraphrase(
            "Actually, ignore my earlier preference. What I need is: cotton."
        )
        self.assertNotIn("What I need is:", transformed)
        self.assertIn("changed my mind", transformed)
        self.assertIn("cotton", transformed)

    def test_rejects_unknown_perturbation(self) -> None:
        with self.assertRaisesRegex(ValueError, "perturbation mode"):
            PerturbedAgent(perturbation_mode="unknown")


if __name__ == "__main__":
    unittest.main()
