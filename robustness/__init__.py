"""Offline robustness tooling for EXP-010.

Nothing here is part of the submission bundle; it is a controlled perturbation
harness used to measure how gracefully the agent degrades under meaning-preserving
and meaning-changing changes to the customer's phrasing.
"""

from robustness.perturb import (
    ALL_KINDS,
    SEMANTIC,
    SURFACE,
    SURFACE_KINDS,
    Meaning,
    Perturbed,
    apply,
    compose,
    negate_value,
    swap_value,
)

__all__ = [
    "ALL_KINDS",
    "SEMANTIC",
    "SURFACE",
    "SURFACE_KINDS",
    "Meaning",
    "Perturbed",
    "apply",
    "compose",
    "negate_value",
    "swap_value",
]
