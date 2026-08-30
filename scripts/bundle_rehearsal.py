"""Run the shipped entry point from a clean bundle, the way the organizer will.

The submission once scored zero because `starter/agent.py` resolved its
signature index inside `.artifacts/`, which is gitignored and therefore present
on every developer machine and in no bundle. `CatalogIndex.__init__` raised, so
`Agent()` never constructed and the evaluator's try/except around `respond` was
never reached. Nothing caught it: running from the repository always has
`.artifacts/` sitting there.

This copies only tracked shipping files into an empty directory that has no
`.artifacts/`, and drives the entry point through a full session against a small
synthetic catalog. It needs no network and no official kit, so it runs in CI on
every pull request.

    python3 scripts/bundle_rehearsal.py [--keep]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Only what the bundle is allowed to contain. `data/`, `evaluator/`, the kit,
# and every development artifact are deliberately excluded.
SHIPPING_PATHS = ("needle", "starter", "submission")

COLORS = ("black", "blue", "red", "white", "green", "gray")
MATERIALS = ("cotton", "denim", "wool", "linen", "nylon", "fleece")
ITEMS = ("shirt", "jacket", "sweater", "dress", "shorts", "hoodie")
USES = ("casual", "outdoor", "winter", "summer", "running", "gym")

# The catalog has to be comfortably larger than one session can consume:
# `exclude_seen` withholds every candidate already shown, so 10 turns of 10
# slots need more than 100 products before an empty slate means a real defect
# rather than an exhausted fixture.
PRODUCTS = [
    {
        "parent_asin": f"TEST{index:04d}",
        "title": f"{COLORS[index % 6]} {MATERIALS[(index // 6) % 6]} {ITEMS[index % 6]}",
        "categories": ["Clothing", ITEMS[index % 6].title()],
        "features": [
            f"{MATERIALS[(index // 6) % 6]} construction",
            f"{USES[(index // 6) % 6]} wear",
        ],
        "details": {"Color": COLORS[index % 6]},
        "store": f"Rehearsal {index % 7}",
        "description": (
            f"{USES[(index // 6) % 6]} {ITEMS[index % 6]} in "
            f"{COLORS[index % 6]} {MATERIALS[(index // 6) % 6]}"
        ),
        "price": 20 + index,
        "average_rating": 4.0,
        "rating_number": 10 + index,
    }
    for index in range(150)
]

# A full ten-turn session in the shape the evaluator drives: an opening
# requirement, disclosures, an override at turn 3, and the exhausted-constraint
# replies that follow. Ten turns because that is the real budget and because
# `exclude_seen` accumulates across them.
SESSION = [
    "I'm looking for a shirt. A key requirement is: cotton.",
    "For that, what matters is: color: black; casual fit.",
    "Actually, ignore my earlier preference. What I need is: wool.",
    "For that, what matters is: winter warmth; wool construction.",
    "I don't have an additional preference for other.",
    "I don't have a preference for size; please use your judgment.",
    "I don't have an additional preference for other.",
    "Those options are not quite right yet. Ask me about one specific attribute.",
    "I don't have an additional preference for other.",
    "I don't have an additional preference for other.",
]


def build_bundle(destination: Path) -> list[str]:
    """Copy tracked shipping files from the working tree into an empty tree.

    Tracked files only, so anything gitignored is excluded exactly as it would
    be from a real bundle. Copied from the working tree rather than exported
    from a commit, so a local run tests the edit in front of you; in CI the
    working tree is the checked-out commit, so the two agree.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", *SHIPPING_PATHS],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    names = [name for name in listed.stdout.split("\0") if name]
    if not names:
        raise SystemExit(f"no tracked files under {SHIPPING_PATHS}")
    for name in names:
        source = ROOT / name
        if not source.is_file():  # tracked but deleted in the working tree
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return names


def write_catalog(destination: Path) -> Path:
    catalog = destination / "catalog.jsonl"
    catalog.write_text(
        "".join(json.dumps(product) + "\n" for product in PRODUCTS),
        encoding="utf-8",
    )
    return catalog


DRIVER = '''
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from starter.agent import Agent

ALLOWED = {
    "budget", "brand", "category", "color", "size",
    "material", "style", "use_case", "feature", "other",
}

catalog = sys.argv[1]
identifiers = {json.loads(line)["parent_asin"] for line in open(catalog)}
agent = Agent(catalog)

# The invariant the score-zero bug violated: the shipped entry point must
# either resolve to no index and rebuild, or resolve to a file that is really
# in the bundle. The original defect pointed at `.artifacts/indexes/`, which
# resolves relative to the package root and so looks bundle-local while never
# existing in a bundle. Pointing at a file that is not there is the defect,
# whether or not the missing file happens to be fatal that week.
# `signature_index_fallback` is set when the entry point asked for an index and
# it could not be used. In a clean bundle that means it asked for a file that
# does not ship. Read it rather than `signature_index_path`, which the fallback
# has already reset to None by this point.
fallback = getattr(agent.catalog, "signature_index_fallback", None)
if fallback is not None:
    raise SystemExit(
        f"entry point requested an index that is not in the bundle: {fallback}"
    )

bundle_root = Path(__file__).resolve().parent
resolved = agent.experiment_configuration.get("signature_index_path")
if resolved is not None:
    resolved = Path(resolved).resolve()
    if not resolved.is_file():
        raise SystemExit(
            f"entry point resolved its index to a path absent from the bundle: {resolved}"
        )
    if not resolved.is_relative_to(bundle_root):
        raise SystemExit(
            f"entry point resolved its index outside the bundle: {resolved}"
        )

agent.reset("rehearsal", {"preference_tags": ["fit"], "summary": "test"})

messages = json.loads(sys.argv[2])
for turn, message in enumerate(messages, start=1):
    response = agent.respond("rehearsal", message, turn, 10)
    if not isinstance(response, dict):
        raise SystemExit(f"turn {turn}: response is {type(response).__name__}, not dict")
    if set(response) - {"message", "ask_attribute", "recommendations", "usage"}:
        raise SystemExit(f"turn {turn}: unexpected keys {sorted(set(response))}")
    if not isinstance(response.get("message"), str):
        raise SystemExit(f"turn {turn}: message is not a string")
    asked = response.get("ask_attribute")
    if asked is not None and asked not in ALLOWED:
        raise SystemExit(f"turn {turn}: invalid ask_attribute {asked!r}")
    recommendations = response.get("recommendations")
    if not isinstance(recommendations, list) or len(recommendations) > 10:
        raise SystemExit(f"turn {turn}: bad recommendations payload")
    for item in recommendations:
        if not isinstance(item, dict) or item.get("parent_asin") not in identifiers:
            raise SystemExit(f"turn {turn}: recommendation outside the catalog: {item!r}")
    if not recommendations:
        raise SystemExit(f"turn {turn}: empty slate")

# `respond` never raises by design: `evaluate` replaces the whole response when
# it does, which forfeits the turn, so the agent catches and degrades instead
# and records what happened. That makes a degradation invisible to every check
# above -- the response is still a valid dict with an in-catalog slate. It is
# the same shape of silence that let a signature asset ship for weeks while the
# agent rejected it at load. Read the record.
failures = getattr(agent, "respond_failures", [])
if failures:
    raise SystemExit(
        f"agent degraded on {len(failures)} turn(s) during rehearsal: {failures[:3]}"
    )

print("bundle rehearsal ok:", len(messages), "turns, slates non-empty and in-catalog")
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="keep the bundle directory")
    arguments = parser.parse_args()

    workspace = Path(tempfile.mkdtemp(prefix="needle-bundle-"))
    try:
        bundle = workspace / "bundle"
        build_bundle(bundle)

        stowaways = [
            path.name
            for path in bundle.iterdir()
            if path.name not in SHIPPING_PATHS
        ]
        if stowaways:
            raise SystemExit(f"bundle contains unexpected entries: {stowaways}")
        if (bundle / ".artifacts").exists():
            raise SystemExit("bundle contains .artifacts/, which never ships")

        catalog = write_catalog(workspace)
        driver = bundle / "_rehearsal_driver.py"
        driver.write_text(DRIVER, encoding="utf-8")

        completed = subprocess.run(
            [sys.executable, str(driver), str(catalog), json.dumps(SESSION)],
            cwd=bundle,
            capture_output=True,
            text=True,
        )
        sys.stdout.write(completed.stdout)
        if completed.returncode != 0:
            sys.stderr.write(completed.stderr)
            raise SystemExit(
                f"clean-bundle rehearsal failed with exit code {completed.returncode}"
            )
        if arguments.keep:
            print(f"bundle kept at {bundle}")
    finally:
        if not arguments.keep:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    main()
