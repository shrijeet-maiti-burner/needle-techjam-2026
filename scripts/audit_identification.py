"""Audit every direct catalog identification against evaluator ground truth.

This is a development diagnostic, not part of the submission. It exists
because a unique lookup can still be wrong when the parsed disclosure is only
a partial card or one of several semicolon readings. The audit fails closed if
any direct identification names a product other than the session target.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KIT = ROOT / ".artifacts" / "participant-kit" / "techjam-conversational-search"
DEFAULT_INDEX = ROOT / ".artifacts" / "indexes" / "catalog-signatures.sqlite3"


def main() -> None:
    parser = argparse.ArgumentParser(description="audit direct-identification precision")
    parser.add_argument("--kit-root", type=Path, default=DEFAULT_KIT)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    arguments = parser.parse_args()

    kit = arguments.kit_root.resolve()
    catalog_path = kit / "data" / "catalog.jsonl"
    dataset_path = kit / "data" / "public_set.jsonl"
    sys.path.insert(0, str(ROOT))
    sys.path.insert(1, str(kit))

    official = importlib.import_module("evaluator.local_evaluator")
    from needle.agent import Agent
    from needle.presets import PRIMARY_AGENT_KWARGS

    samples = official.load_jsonl(dataset_path)
    catalog_ids, categories, products = official.catalog_index(catalog_path)
    targets = [str(sample["ground_truth"]["parent_asin"]) for sample in samples]

    class AuditedAgent(Agent):
        def __init__(self) -> None:
            super().__init__(
                catalog_path,
                signature_index_path=arguments.index.resolve(),
                **PRIMARY_AGENT_KWARGS,
            )
            self._target_iterator = iter(targets)
            self._target = ""
            self.identifications: list[tuple[str, str]] = []
            self.promotions: list[tuple[str, bool]] = []
            identify = self.catalog.identify_from_disclosures
            promote = self.catalog.rank_disclosure_bucket

            def audited(*args: object, **kwargs: object) -> str | None:
                result = identify(*args, **kwargs)
                if result is not None:
                    self.identifications.append((self._target, result))
                return result

            self.catalog.identify_from_disclosures = audited  # type: ignore[method-assign]

            def audited_promotion(*args: object, **kwargs: object) -> tuple[str, ...]:
                result = promote(*args, **kwargs)
                if result:
                    self.promotions.append((self._target, self._target in result))
                return result

            self.catalog.rank_disclosure_bucket = audited_promotion  # type: ignore[method-assign]

        def reset(self, session_id: str, user_profile: dict[str, object]) -> None:
            self._target = next(self._target_iterator)
            super().reset(session_id, user_profile)

    agent = AuditedAgent()
    result = official.evaluate(agent, samples, catalog_ids, categories, products)
    wrong = [pair for pair in agent.identifications if pair[0] != pair[1]]
    removed = [target for target, retained in agent.promotions if not retained]
    report = {
        "direct_identification_calls": len(agent.identifications),
        "correct": len(agent.identifications) - len(wrong),
        "wrong": len(wrong),
        "wrong_examples": wrong[:10],
        "promotion_calls": len(agent.promotions),
        "promotion_target_retained": len(agent.promotions) - len(removed),
        "promotion_target_removed": len(removed),
        "promotion_removal_examples": removed[:10],
        "technical_score": result["recommended_technical_score"],
    }
    print(json.dumps(report, indent=2))
    if wrong:
        raise SystemExit("direct-identification precision audit failed")
    if removed:
        raise SystemExit("disclosure-bucket target-retention audit failed")


if __name__ == "__main__":
    main()
