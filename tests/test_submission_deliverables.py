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
        for heading in ("## Architecture and method", "## Model choice and models used",
                        "## Cost, token usage, latency, and network disclosure",
                        "## Limitations", "## Team contributions"):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.report)

    def test_the_report_uses_the_words_the_specification_asks_for(self) -> None:
        """`Final Deliverables` names the coverage: architecture, models, cost,
        limitations, team contributions. A reviewer checking that list should
        find each word in the report rather than having to infer it from a
        section called something else."""
        lowered = self.report.lower()
        for word in ("architecture", "model", "cost", "limitation", "contribution"):
            with self.subTest(word=word):
                self.assertIn(word, lowered)

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
        self.assertIn("TECHJAM_KIT_ROOT", transcript)


class TheDisclosedAssetIsTheShippedAsset(unittest.TestCase):
    """The report states the index size and its two bindings, and a reviewer can
    check all three from the archive in one command.

    They had already drifted: the report described a 68,702,208-byte index built
    by an earlier parser, while the archive carried a 71,241,728-byte index whose
    parser fingerprint had moved with the clarification-facet change. Both
    numbers are mechanical, so nothing about them should depend on someone
    remembering to retype them.
    """

    ASSET = ROOT / ".artifacts" / "indexes" / "catalog-signatures.sqlite3"

    def setUp(self) -> None:
        if not self.ASSET.is_file():
            self.skipTest("no built signature index on this machine")
        import sqlite3

        connection = sqlite3.connect(f"file:{self.ASSET.as_posix()}?mode=ro", uri=True)
        try:
            self.metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        finally:
            connection.close()
        self.report = REPORT.read_text(encoding="utf-8")

    def test_the_report_cites_this_catalog_binding(self) -> None:
        self.assertIn(self.metadata["catalog_sha256"], self.report)

    def test_the_report_cites_this_parser_binding(self) -> None:
        self.assertIn(self.metadata["facet_parser_sha256"], self.report)

    def test_the_report_cites_this_size_and_schema(self) -> None:
        self.assertIn(f"{self.ASSET.stat().st_size:,}", self.report)
        self.assertIn(f"{self.metadata['schema_version']}; ", self.report)


class TheStorefrontShips(unittest.TestCase):
    """Not required by the specification, which puts interface work out of
    scope, but a reviewer who would rather type at the agent than read a
    transcript should not have to clone the repository to do it."""

    def test_the_interface_and_its_server_are_present(self) -> None:
        shipped = _tracked_under(_shipping_paths())
        for name in ("scripts/needle_storefront.py", "demo/storefront.html",
                     "storefront/service.py", "docs/STOREFRONT.md"):
            with self.subTest(path=name):
                self.assertIn(name, shipped)

    def test_nothing_scored_imports_it(self) -> None:
        """The archive carries one policy. A demo quietly running a different
        one would be worse than no demo, so the dependency runs one way only.

        Checked on the import graph rather than on the word, which appears in
        prose in both directions.
        """
        import ast

        for module in ("needle/agent.py", "needle/catalog.py", "needle/questions.py",
                       "starter/agent.py", "submission/agent.py"):
            with self.subTest(module=module):
                tree = ast.parse((ROOT / module).read_text(encoding="utf-8"), filename=module)
                imported: list[str] = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported += [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imported.append(node.module)
                offenders = [name for name in imported if name.split(".")[0] == "storefront"]
                self.assertEqual(offenders, [], f"{module} imports the demo layer")


class TheArchiveRunsOnWhatItClaims(unittest.TestCase):
    """The reproducibility rules make the version floor a promise, not a note.

    "exact Python version requirement if non-default" is a required part of the
    package, and an unreproducible bundle may be treated as invalid. A grep for
    newer syntax is not a check; parsing every shipped file against the declared
    grammar is.
    """

    def test_every_shipped_module_parses_under_the_declared_floor(self) -> None:
        import ast

        shipped = sorted(
            name for name in _tracked_under(_shipping_paths()) if name.endswith(".py")
        )
        self.assertTrue(shipped, "no python files were found to check")
        for name in shipped:
            with self.subTest(module=name):
                source = (ROOT / name).read_text(encoding="utf-8")
                try:
                    ast.parse(source, filename=name, feature_version=(3, 10))
                except SyntaxError as error:  # pragma: no cover - the failure is the point
                    self.fail(f"{name} needs newer than Python 3.10: {error}")

    def test_the_declared_floor_matches_the_run_notes(self) -> None:
        self.assertIn("Python: 3.10 or later", RUN_NOTES.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
