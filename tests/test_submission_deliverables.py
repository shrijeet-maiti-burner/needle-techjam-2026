"""Everything the report points at has to be inside the archive.

`submission/REPORT.md` is the judge-facing document and the one they are
guaranteed to open. The competition specification lists four final deliverables,
two of which the report is responsible for carrying: "a short report covering
architecture, models, cost, limitations, and team contributions" and "one
demonstrated multi-turn session".

Before this guard the report cited five paths that the archive did not contain,
including `scripts/demo_session.py`, which was the only place the demonstrated
session existed. A judge opening the zip could not see a required deliverable at
all. That is a missing deliverable rather than a broken link, so it is asserted
here rather than reviewed by eye.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "submission" / "REPORT.md"
RUN_NOTES = ROOT / "submission" / "README.md"

# Paths the report may name without shipping them, each for a stated reason.
NOT_SHIPPED = {
    # the participant kit's own file, not ours
    "docs/submission_rules.md",
    # interface work is out of scope in the specification; the transcript is
    # the required artefact and it is embedded in the report itself
    "scripts/needle_storefront.py",
    "scripts/build_signature_index.py",
    "scripts/build_submission_bundle.py",
    "scripts/run_experiment.py",
    # named only to say it does not exist, which is the point of that paragraph
    "scripts/evaluate.py",
}

REFERENCE_RE = re.compile(r"(?:\.\./)?((?:docs|scripts|needle|starter|submission)/[\w./-]+\.\w+)")


def _shipping_paths() -> tuple[str, ...]:
    namespace: dict[str, object] = {}
    source = (ROOT / "scripts" / "build_submission_bundle.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        if line.startswith("SHIPPING_PATHS"):
            break
    exec(  # noqa: S102 - reading one constant out of a sibling script
        source[source.index("SHIPPING_PATHS"):source.index(")", source.index("SHIPPING_PATHS")) + 1],
        namespace,
    )
    return tuple(namespace["SHIPPING_PATHS"])


def _tracked_under(paths: tuple[str, ...]) -> set[str]:
    listed = subprocess.run(
        ["git", "ls-files", "--", *paths], cwd=ROOT, check=True,
        capture_output=True, text=True,
    )
    tracked = {name for name in listed.stdout.split("\n") if name}
    # The signature asset is deliberately untracked and is added by the bundler
    # from the build directory, so `git ls-files` cannot see it.
    tracked.add("submission/assets/catalog-signatures.sqlite3")
    return tracked


class EveryCitedPathShips(unittest.TestCase):
    def setUp(self) -> None:
        self.shipped = _tracked_under(_shipping_paths())

    def _check(self, document: Path) -> None:
        cited = {
            match.group(1)
            for match in REFERENCE_RE.finditer(document.read_text(encoding="utf-8"))
        }
        missing = sorted(
            path for path in cited
            if path not in NOT_SHIPPED and path not in self.shipped
        )
        self.assertEqual(
            missing, [],
            f"{document.name} cites paths the archive does not contain: {missing}",
        )

    def test_the_report_cites_only_shipped_paths(self) -> None:
        self._check(REPORT)

    def test_the_run_notes_cite_only_shipped_paths(self) -> None:
        self._check(RUN_NOTES)


class TheRequiredDeliverablesArePresent(unittest.TestCase):
    """The specification's "Final Deliverables" list, checked one by one."""

    def setUp(self) -> None:
        self.shipped = _tracked_under(_shipping_paths())
        self.report = REPORT.read_text(encoding="utf-8")

    def test_setup_and_reproduction_instructions(self) -> None:
        self.assertIn("submission/README.md", self.shipped)

    def test_a_working_agent_on_the_required_interface(self) -> None:
        self.assertIn("submission/agent.py", self.shipped)
        self.assertIn("starter/agent.py", self.shipped)

    def test_the_report_covers_every_required_topic(self) -> None:
        for heading in ("## Method", "## Model choice", "## Disclosure",
                        "## Limitations", "## Team contributions"):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.report)

    def test_one_demonstrated_multi_turn_session_is_in_the_report(self) -> None:
        """Readable from the archive alone, not only by running something."""
        self.assertIn("## Demonstrated session", self.report)
        transcript = self.report.split("## Demonstrated session", 1)[1]
        transcript = transcript.split("## Team contributions", 1)[0]
        for marker in ("turn 1", "turn 2", "customer", "agent", "HIT on turn"):
            with self.subTest(marker=marker):
                self.assertIn(marker, transcript)
        self.assertIn("scripts/demo_session.py", self.shipped,
                      "the transcript must also be reproducible from the archive")


if __name__ == "__main__":
    unittest.main()
