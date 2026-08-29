"""Perturbed session driver for the EXP-010 robustness harness.

This mirrors the official ``evaluator.local_evaluator.evaluate`` session loop with
one addition: a perturbation hook that rewrites the customer's phrasing
(meaning-preserving slices) or edits the reconstructed intent card
(meaning-changing slices) before the agent sees it.

It is **not** the official evaluator. It is used only to measure how gracefully
the agent degrades under controlled perturbation; it never produces a leaderboard
metric. Message generation is delegated to the official simulator functions via
:class:`Simulator`, so the only thing this file re-implements is the loop.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from needle.state import COLORS, MATERIALS, SIZES, STYLES, USE_CASES
from robustness.perturb import Meaning, compose, negate_value, swap_value


# Combined in-catalog value vocabulary for the attribute-swap edit. Not
# bucket-aware on purpose: replacing "cotton" with "red" is still a genuine
# meaning change, which is what that slice tests.
_SWAP_VOCABULARY: tuple[str, ...] = tuple(
    sorted({value for group in (MATERIALS, COLORS, SIZES, STYLES, USE_CASES) for value in group})
)

_SURFACE_SCOPES = frozenset({"all", "override_only"})
_CARD_EDITS = frozenset({"negate", "swap", "drop_soft"})


@dataclass(frozen=True, slots=True)
class Simulator:
    """The message-generation surface of the official evaluator.

    Bound to ``evaluator.local_evaluator`` in production (see
    :func:`official_simulator`); a small fake is used in tests.
    """

    materialize_hidden_fields: Callable[[dict, Mapping[str, dict]], tuple[dict, dict]]
    initial_message: Callable[[dict, str, set[str]], str]
    customer_reply: Callable[[dict, object, set[str], bool], tuple[str, bool]]
    coarse_category: Callable[[Sequence[str]], str]
    normalize_recommendations: Callable[[object, set[str]], list[str]]
    max_turns: int = 10
    top_k: int = 10


def official_simulator() -> Simulator:
    """Bind to the bootstrapped participant kit. Raises ``ImportError`` if the kit
    is not on ``sys.path`` (run ``scripts/bootstrap.py`` and add the kit root)."""
    from evaluator import local_evaluator as evaluator

    return Simulator(
        materialize_hidden_fields=evaluator.materialize_hidden_fields,
        initial_message=evaluator.initial_message,
        customer_reply=evaluator.customer_reply,
        coarse_category=evaluator.coarse_category,
        normalize_recommendations=evaluator.normalize_recommendations,
        max_turns=evaluator.MAX_TURNS,
        top_k=evaluator.TOP_K,
    )


@dataclass(frozen=True, slots=True)
class SliceSpec:
    """One robustness slice: a named perturbation plus its meaning label."""

    name: str
    meaning: Meaning
    surface_kinds: tuple[str, ...] = ()
    surface_scope: str = "all"
    card_edit: str | None = None

    def __post_init__(self) -> None:
        if self.surface_scope not in _SURFACE_SCOPES:
            raise ValueError(f"unknown surface_scope: {self.surface_scope!r}")
        if self.card_edit is not None and self.card_edit not in _CARD_EDITS:
            raise ValueError(f"unknown card_edit: {self.card_edit!r}")
        if self.card_edit is not None and self.meaning is not Meaning.CHANGING:
            raise ValueError("a card_edit slice must be meaning_changing")


BASELINE = SliceSpec("exact_surface", Meaning.PRESERVING)


@dataclass(frozen=True, slots=True)
class SessionOutcome:
    sample_id: str
    scenario_type: str
    slice: str
    meaning: Meaning
    hit: bool
    first_hit_turn: int | None
    rank: int | None
    reciprocal_rank: float
    target_in_pool: bool
    changed: bool
    perturbation_detail: str = ""


@dataclass(slots=True)
class _MessageHook:
    spec: SliceSpec
    rng: random.Random
    details: list[str] = field(default_factory=list)

    def apply(self, message: str, *, override_turn: bool = False) -> tuple[str, bool]:
        if not self.spec.surface_kinds:
            return message, False
        if self.spec.surface_scope == "override_only" and not override_turn:
            return message, False
        result = compose(message, list(self.spec.surface_kinds), self.rng)
        if result.detail:
            self.details.append(result.detail)
        return result.text, result.changed


def _edit_card(card: dict, spec: SliceSpec, rng: random.Random) -> tuple[dict, bool, str]:
    """Return a copy of ``card`` with one meaning-changing edit applied."""
    if spec.card_edit is None:
        return card, False, ""
    edited = {
        key: (list(value) if isinstance(value, list) else value)
        for key, value in card.items()
    }

    if spec.card_edit == "drop_soft":
        soft = edited.get("soft_preferences") or []
        if not soft:
            return edited, False, "no soft preference to drop"
        index = rng.randrange(len(soft))
        removed = soft.pop(index)
        return edited, True, f"dropped soft preference {removed!r}"

    pools = [key for key in ("hard_constraints", "soft_preferences") if edited.get(key)]
    if not pools:
        return edited, False, "card has no constraints to edit"
    key = pools[rng.randrange(len(pools))]
    values = edited[key]
    index = rng.randrange(len(values))
    original = str(values[index])

    if spec.card_edit == "negate":
        result = negate_value(original, rng)
    else:  # swap
        result = swap_value(original, rng, alternatives=_SWAP_VOCABULARY)
    values[index] = result.text
    return edited, result.changed, f"{key}[{index}]: {result.detail}"


def run_perturbed_session(
    agent: object,
    sample: dict,
    *,
    catalog_ids: set[str],
    categories: Mapping[str, list[str]],
    products: Mapping[str, dict],
    simulator: Simulator,
    spec: SliceSpec,
    rng: random.Random,
) -> SessionOutcome:
    """Drive one perturbed session and score exact-target hit / rank / recall.

    Structurally identical to the official loop: session ends on the first
    eligible exact hit (rank and turn frozen there) or after ``max_turns``, and
    an intent-override session cannot convert before the scheduled override turn.
    """
    session_id = f"rob-{spec.name}-{sample['sample_id']}"
    agent.reset(session_id, sample["user_profile"])
    target = str(sample["ground_truth"]["parent_asin"])

    card, behavior = simulator.materialize_hidden_fields(dict(sample), products)
    card, card_changed, card_detail = _edit_card(card, spec, rng)
    effective = {**sample, "intent_card": card, "behavior": behavior}

    disclosed: set[str] = set()
    boundary_used = False
    override_applied = sample["scenario_type"] != "intent_override"
    hook = _MessageHook(spec, rng)

    category = simulator.coarse_category(categories.get(target, []))
    user_message, changed = hook.apply(simulator.initial_message(effective, category, disclosed))
    changed_any = changed or card_changed

    hit_turn: int | None = None
    rank: int | None = None
    target_in_pool = False

    for turn in range(1, simulator.max_turns + 1):
        try:
            response = agent.respond(session_id, user_message, turn, simulator.top_k)
        except Exception:
            response = {"message": "", "ask_attribute": None, "recommendations": []}
        if not isinstance(response, dict) or not isinstance(response.get("message"), str):
            response = {"message": "", "ask_attribute": None, "recommendations": []}

        ranked = simulator.normalize_recommendations(response.get("recommendations"), catalog_ids)
        if target in ranked:
            target_in_pool = True
        if override_applied and target in ranked:
            rank = ranked.index(target) + 1
            hit_turn = turn
            break
        if turn == simulator.max_turns:
            break

        override = effective.get("behavior", {}).get("override") or {}
        if not override_applied and turn + 1 == int(override.get("turn", 3)):
            override_applied = True
            new_value = str(override.get("new_value", ""))
            if new_value:
                disclosed.add(new_value)
            raw = str(override.get("message", "Actually, please ignore my earlier preference."))
            user_message, changed = hook.apply(raw, override_turn=True)
        else:
            raw, boundary_used = simulator.customer_reply(
                effective, response.get("ask_attribute"), disclosed, boundary_used
            )
            user_message, changed = hook.apply(raw)
        changed_any = changed_any or changed

    detail = "; ".join(part for part in (card_detail, *hook.details) if part)
    return SessionOutcome(
        sample_id=str(sample["sample_id"]),
        scenario_type=str(sample["scenario_type"]),
        slice=spec.name,
        meaning=spec.meaning,
        hit=hit_turn is not None,
        first_hit_turn=hit_turn,
        rank=rank,
        reciprocal_rank=0.0 if rank is None else 1.0 / rank,
        target_in_pool=target_in_pool,
        changed=changed_any,
        perturbation_detail=detail,
    )


def run_slice(
    agent: object,
    samples: Sequence[dict],
    spec: SliceSpec,
    *,
    catalog_ids: set[str],
    categories: Mapping[str, list[str]],
    products: Mapping[str, dict],
    simulator: Simulator,
    seed: object = 0,
) -> list[SessionOutcome]:
    """Run every sample through one slice. The per-session RNG is derived from
    ``(seed, slice name, sample id)`` so the whole slice is reproducible."""
    outcomes: list[SessionOutcome] = []
    for sample in samples:
        rng = random.Random(f"{seed}|{spec.name}|{sample['sample_id']}")
        outcomes.append(
            run_perturbed_session(
                agent,
                sample,
                catalog_ids=catalog_ids,
                categories=categories,
                products=products,
                simulator=simulator,
                spec=spec,
                rng=rng,
            )
        )
    return outcomes
