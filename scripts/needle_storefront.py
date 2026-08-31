"""Serve the conversational storefront against the selected primary agent.

The Needle Lens replays released public samples to certify what the agent
decided. This serves the other half: a person types whatever they like and the
same agent answers, so behaviour the 200 released sessions never produce can be
seen before a judge finds it.

    python scripts/bootstrap.py
    python scripts/build_signature_index.py
    python scripts/needle_storefront.py

Then open http://127.0.0.1:8770.

The candidate generator is built from `PRIMARY_AGENT_KWARGS`. The default
interface adds the explicitly-labelled product journey layer; pass
`--benchmark-mode` for the exact one-target session shape. `--set key=value`
overrides one agent keyword and the interface displays the deviation, because a
demo quietly running a different policy from the scored one is worse than no
demo. The server binds the loopback interface only; nothing here is written to
be exposed to a network.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KIT = Path(
    os.environ.get(
        "TECHJAM_KIT_ROOT",
        ROOT / ".artifacts" / "participant-kit" / "techjam-conversational-search",
    )
)
ASSET = ROOT / ".artifacts" / "indexes" / "catalog-signatures.sqlite3"
HTML = ROOT / "demo" / "storefront.html"
sys.path.insert(0, str(ROOT))

from storefront.service import StorefrontService  # noqa: E402

# One megabyte is far more than a shopping message and small enough that a
# malformed Content-Length cannot make the server allocate without bound.
MAX_BODY_BYTES = 1 << 20


def parse_override(text: str) -> tuple[str, object]:
    """`key=value`, with the value read as JSON so types survive.

    `--set slate_size=10` gives an int, `--set lexical_mode='"expand"'` a string,
    `--set adaptive_slate=false` a bool. A bare word that is not valid JSON is
    kept as a string, which is what someone typing `--set lexical_mode=expand`
    means.
    """
    key, separator, raw = text.partition("=")
    if not separator or not key.strip():
        raise argparse.ArgumentTypeError(f"expected key=value, received {text!r}")
    try:
        value: object = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    return key.strip(), value


class StorefrontHandler(BaseHTTPRequestHandler):
    service: StorefrontService
    server_version = "NeedleStorefront/1.0"

    # -- plumbing ------------------------------------------------------------

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        if self.server.quiet:  # type: ignore[attr-defined]
            return
        super().log_message(format, *args)

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # The page is served from this origin and talks only to it. Denying
        # framing and sniffing costs nothing and keeps a local demo from being
        # embedded by anything else the browser happens to have open.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                # A navigation or closed tab may abandon an in-flight response.
                # The request is already over from that client's perspective;
                # do not turn a routine disconnect into a server traceback.
                return

    def _json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json(status, {"error": message})

    def _body(self) -> dict[str, object]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("invalid Content-Length") from None
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValueError("request body out of range")
        if length == 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid JSON body: {error}") from error
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    # -- routes --------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        route = self.path.split("?", 1)[0].rstrip("/") or "/"
        if route == "/":
            try:
                body = HTML.read_bytes()
            except OSError:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"cannot read {HTML}")
                return
            self._send(HTTPStatus.OK, body, "text/html; charset=utf-8")
            return
        if route == "/api/config":
            self._json(HTTPStatus.OK, self.service.describe())
            return
        self._error(HTTPStatus.NOT_FOUND, f"no such route: {route}")

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        route = self.path.split("?", 1)[0].rstrip("/") or "/"
        try:
            payload = self._body()
        except ValueError as error:
            self._error(HTTPStatus.BAD_REQUEST, str(error))
            return

        if route == "/api/session":
            profile = payload.get("profile")
            language = payload.get("language")
            try:
                conversation = self.service.start(
                    profile=profile if isinstance(profile, dict) else None,
                    language=str(language) if language else None,
                )
            except ValueError as error:
                self._error(HTTPStatus.BAD_REQUEST, str(error))
                return
            self._json(
                HTTPStatus.OK,
                {
                    "session_id": conversation.session_id,
                    "config": self.service.describe(),
                },
            )
            return

        if route == "/api/message":
            session_id = str(payload.get("session_id") or "").strip()
            message = str(payload.get("message") or "")
            if not session_id:
                self._error(HTTPStatus.BAD_REQUEST, "session_id is required")
                return
            try:
                turn = self.service.send(session_id, message)
            except ValueError as error:
                self._error(HTTPStatus.BAD_REQUEST, str(error))
                return
            self._json(HTTPStatus.OK, turn.as_dict())
            return

        if route == "/api/select":
            session_id = str(payload.get("session_id") or "").strip()
            parent_asin = str(payload.get("parent_asin") or "").strip()
            if not session_id or not parent_asin:
                self._error(HTTPStatus.BAD_REQUEST, "session_id and parent_asin are required")
                return
            try:
                selected = self.service.select(session_id, parent_asin)
            except ValueError as error:
                self._error(HTTPStatus.BAD_REQUEST, str(error))
                return
            self._json(HTTPStatus.OK, selected)
            return

        self._error(HTTPStatus.NOT_FOUND, f"no such route: {route}")


def build_service(arguments: argparse.Namespace) -> StorefrontService:
    catalog = Path(arguments.catalog) if arguments.catalog else KIT / "data" / "catalog.jsonl"
    if not catalog.is_file():
        raise SystemExit(
            f"catalog not found: {catalog}\n"
            "run `python scripts/bootstrap.py` first, or pass --catalog"
        )
    asset = Path(arguments.signature_index) if arguments.signature_index else ASSET
    return StorefrontService(
        catalog,
        signature_index_path=asset if asset.is_file() else None,
        overrides=dict(arguments.set or []),
        journey_mode=not arguments.benchmark_mode,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--catalog", default=None)
    parser.add_argument("--signature-index", default=None)
    parser.add_argument(
        "--set",
        action="append",
        type=parse_override,
        metavar="KEY=VALUE",
        help="override one agent keyword; the interface reports the deviation",
    )
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--benchmark-mode",
        action="store_true",
        help="disable the product journey overlay and drive the exact scored session shape",
    )
    parser.add_argument(
        "--warm",
        action="store_true",
        help="construct the agent before serving instead of on the first turn",
    )
    arguments = parser.parse_args(argv)

    if not HTML.is_file():
        raise SystemExit(f"interface not found: {HTML}")

    service = build_service(arguments)
    if arguments.warm:
        print("building the agent ...", flush=True)
        service.agent
        print(f"ready in {service.construction_seconds:.2f}s", flush=True)

    handler = type("BoundStorefrontHandler", (StorefrontHandler,), {"service": service})
    server = ThreadingHTTPServer((arguments.host, arguments.port), handler)
    server.quiet = bool(arguments.quiet)  # type: ignore[attr-defined]
    server.daemon_threads = True

    deviations = service.deviations
    print(f"needle storefront on http://{arguments.host}:{arguments.port}", flush=True)
    if service.journey_mode:
        print("  product journey mode over the frozen primary retrieval engine", flush=True)
    if deviations:
        print(f"  deviating from the primary preset: {deviations}", flush=True)
    elif not service.journey_mode:
        print("  running the selected primary configuration", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping", flush=True)
    finally:
        server.shutdown()
        server.server_close()
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
