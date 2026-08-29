"""The default EXP-010 slice catalogue.

Meaning-preserving slices apply a surface perturbation to every customer message
(or only the override message, for ``override_paraphrase``). Meaning-changing
slices edit one constraint in the reconstructed intent card. ``exact_surface`` is
the unperturbed baseline every other slice is compared against.
"""

from __future__ import annotations

from robustness.perturb import Meaning
from robustness.session import BASELINE, SliceSpec

MEANING_PRESERVING: tuple[SliceSpec, ...] = (
    SliceSpec("casing", Meaning.PRESERVING, ("casing",)),
    SliceSpec("whitespace", Meaning.PRESERVING, ("whitespace",)),
    SliceSpec("punctuation", Meaning.PRESERVING, ("punctuation",)),
    SliceSpec("accents", Meaning.PRESERVING, ("accents",)),
    SliceSpec("synonym", Meaning.PRESERVING, ("synonym",)),
    SliceSpec("word_order", Meaning.PRESERVING, ("word_order",)),
    SliceSpec("filler", Meaning.PRESERVING, ("filler",)),
    SliceSpec("politeness", Meaning.PRESERVING, ("politeness",)),
    SliceSpec("contraction", Meaning.PRESERVING, ("contraction",)),
    SliceSpec("number_format", Meaning.PRESERVING, ("number_format",)),
    SliceSpec("typo", Meaning.PRESERVING, ("typo",)),
    SliceSpec("paraphrase", Meaning.PRESERVING, ("politeness", "synonym", "filler", "word_order")),
    SliceSpec(
        "override_paraphrase",
        Meaning.PRESERVING,
        ("politeness", "synonym"),
        surface_scope="override_only",
    ),
)

MEANING_CHANGING: tuple[SliceSpec, ...] = (
    SliceSpec("negation", Meaning.CHANGING, card_edit="negate"),
    SliceSpec("attribute_swap", Meaning.CHANGING, card_edit="swap"),
    SliceSpec("constraint_drop", Meaning.CHANGING, card_edit="drop_soft"),
)

DEFAULT_SLICES: tuple[SliceSpec, ...] = (BASELINE, *MEANING_PRESERVING, *MEANING_CHANGING)

BY_NAME: dict[str, SliceSpec] = {spec.name: spec for spec in DEFAULT_SLICES}
