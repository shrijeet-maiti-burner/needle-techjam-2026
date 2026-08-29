from __future__ import annotations

import hashlib
import shutil
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / ".artifacts"
ARCHIVE = ARTIFACTS / "techjam-participant-kit.zip"
KIT_ROOT = ARTIFACTS / "participant-kit" / "techjam-conversational-search"
DOWNLOAD_URL = (
    "https://github.com/TechJam2026/techjam-conversational-search/"
    "releases/download/participant-kit/techjam-participant-kit.zip"
)
EXPECTED_SHA256 = "b3d7e283b835343b42c4919ea2ca90f2fb5a2aa2b10537f14dcf42f03e5b38ae"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            target = (destination / member.filename).resolve()
            if root != target and root not in target.parents:
                raise RuntimeError(f"unsafe archive member: {member.filename}")
        zipped.extractall(destination)


def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if not ARCHIVE.exists():
        print(f"downloading official participant kit to {ARCHIVE}")
        with urllib.request.urlopen(DOWNLOAD_URL) as response, ARCHIVE.open("wb") as output:
            shutil.copyfileobj(response, output)
    actual = sha256(ARCHIVE)
    if actual != EXPECTED_SHA256:
        raise RuntimeError(f"participant-kit checksum mismatch: {actual}")
    print(f"verified participant kit sha256 {actual}")
    if not (KIT_ROOT / "evaluator" / "local_evaluator.py").is_file():
        safe_extract(ARCHIVE, KIT_ROOT.parent)
        print(f"extracted participant kit to {KIT_ROOT}")
    else:
        print(f"participant kit already extracted at {KIT_ROOT}")


if __name__ == "__main__":
    main()
