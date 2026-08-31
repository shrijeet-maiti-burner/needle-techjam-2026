"""Build and verify the minimal asset-bundled scoring archive."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KIT = ROOT / ".artifacts" / "participant-kit" / "techjam-conversational-search"
DEFAULT_ASSET = ROOT / ".artifacts" / "indexes" / "catalog-signatures.sqlite3"
DEFAULT_OUTPUT = ROOT / ".artifacts" / "releases" / "needle-submission.zip"
# Everything `submission/REPORT.md` cites has to be reachable from inside the
# archive. The report is the judge-facing document and it is the only one they
# are guaranteed to open; a required deliverable that it points at and the zip
# does not contain is a missing deliverable, not a broken link.
#
# `scripts/demo_session.py` is here because the specification requires "one
# demonstrated multi-turn session". `docs/OWNERSHIP.md` and
# `docs/SUBMISSION_DISCLOSURES.md` are here because the report cites them for
# the required team-contribution and cost/tool disclosures.
SHIPPING_PATHS = (
    "needle",
    "starter",
    "submission",
    "README.md",
    "requirements.txt",
    "scripts/demo_session.py",
    "docs/OWNERSHIP.md",
    "docs/SUBMISSION_DISCLOSURES.md",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_tracked(destination: Path) -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", *SHIPPING_PATHS],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    names = [name for name in listed.stdout.split("\0") if name]
    for name in names:
        source = ROOT / name
        if not source.is_file():
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return names


def evaluate_bundle(bundle: Path, kit: Path, output: Path) -> dict[str, object]:
    evaluator = kit / "evaluator" / "local_evaluator.py"
    catalog = kit / "data" / "catalog.jsonl"
    dataset = kit / "data" / "public_set.jsonl"
    required = (evaluator, catalog, dataset)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"official kit incomplete: {', '.join(missing)}")

    driver = (
        "import runpy,sys; "
        f"sys.path.insert(0, {str(bundle)!r}); "
        f"sys.argv=[{str(evaluator)!r}, '--catalog', {str(catalog)!r}, "
        f"'--dataset', {str(dataset)!r}, '--output', {str(output)!r}]; "
        f"runpy.run_path({str(evaluator)!r}, run_name='__main__')"
    )
    completed = subprocess.run(
        [sys.executable, "-c", driver],
        cwd=bundle,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "bundled official evaluation failed\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    if completed.stderr:
        raise RuntimeError(f"bundled evaluation wrote stderr:\n{completed.stderr}")
    return json.loads(output.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="build verified submission zip")
    parser.add_argument("--kit-root", type=Path, default=DEFAULT_KIT)
    parser.add_argument("--asset", type=Path, default=DEFAULT_ASSET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()

    asset = arguments.asset.resolve()
    output = arguments.output.resolve()
    kit = arguments.kit_root.resolve()
    catalog = kit / "data" / "catalog.jsonl"
    if not asset.is_file():
        raise FileNotFoundError(f"signature asset not found: {asset}")
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")

    uri = f"file:{asset.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    catalog_sha = sha256_file(catalog)
    if metadata.get("catalog_sha256") != catalog_sha:
        raise ValueError("signature asset is not bound to the official catalog")
    # The catalog binding was checked and the schema was not, so an asset built
    # against an older `SIGNATURE_INDEX_SCHEMA_VERSION` shipped happily and was
    # then rejected at load by the very agent it was built for. `CatalogIndex`
    # treats that as a soft failure and rebuilds in process, so nothing broke
    # and nothing said anything: the bundle simply carried 32MB it could not
    # use and paid 19 extra seconds of construction on every run.
    # Read from the package rather than duplicating the constant, so this can
    # never drift from the loader it is protecting. Imported here rather than at
    # module scope because the bundler is otherwise deliberately free of package
    # imports.
    sys.path.insert(0, str(ROOT))
    from needle.catalog import SIGNATURE_INDEX_SCHEMA_VERSION

    if metadata.get("schema_version") != SIGNATURE_INDEX_SCHEMA_VERSION:
        raise ValueError(
            "signature asset schema "
            f"{metadata.get('schema_version')!r} is not the {SIGNATURE_INDEX_SCHEMA_VERSION!r} "
            "this code reads; rebuild it with scripts/build_signature_index.py"
        )

    workspace = Path(tempfile.mkdtemp(prefix="needle-release-"))
    try:
        bundle = workspace / "bundle"
        bundle.mkdir()
        names = copy_tracked(bundle)
        bundled_asset = bundle / "submission" / "assets" / "catalog-signatures.sqlite3"
        bundled_asset.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(asset, bundled_asset)

        forbidden = (bundle / ".artifacts", bundle / "data", bundle / "evaluator")
        if any(path.exists() for path in forbidden):
            raise RuntimeError("bundle contains a forbidden development or evaluator path")

        result_path = workspace / "official-result.json"
        result = evaluate_bundle(bundle, kit, result_path)
        manifest = {
            "entry_point": "starter.agent:Agent",
            "python": ">=3.10",
            "tracked_file_count": len(names),
            "asset": {
                "path": "submission/assets/catalog-signatures.sqlite3",
                "size_bytes": bundled_asset.stat().st_size,
                "sha256": sha256_file(bundled_asset),
                "schema_version": metadata.get("schema_version"),
                "catalog_sha256": catalog_sha,
            },
            "public_rehearsal": {
                key: result[key]
                for key in (
                    "sample_count",
                    "hit_rate_at_10",
                    "mrr",
                    "mttc",
                    "recommended_technical_score",
                )
            },
        }
        (bundle / "MANIFEST.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(bundle.rglob("*")):
                if (
                    path.is_file()
                    and "__pycache__" not in path.parts
                    and path.suffix != ".pyc"
                ):
                    archive.write(path, path.relative_to(bundle).as_posix())
        print(json.dumps({
            "archive": str(output),
            "size_bytes": output.stat().st_size,
            "sha256": sha256_file(output),
            **manifest,
        }, indent=2, sort_keys=True))
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    main()
