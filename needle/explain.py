"""Grounded explanations for what the agent just did and why.

The response contract carries a `message` field that nothing scores. It has
been a constant since the first milestone -- the same two sentences on every
turn of every session -- which is a waste of the one field the customer actually
reads, and it makes any transcript a reviewer opens look like a stub.

Everything needed to say something true is already computed on the turn and then
discarded: the coarse category the customer opened with, the constraints the
belief state currently holds active, how many catalog products still satisfy all
of them, and whether that set has collapsed to one. This module turns that into
a sentence, and into a structured record for anything that wants to render it.

Two rules govern what may be said.

*Only claims the state supports.* "The only leather belt with a buckle closure"
is printed when the disclosure bucket holds exactly one product, and not
otherwise. There is no template that overstates a partial match, and none that
invents a reason.

*Never at the cost of a valid turn.* `local_evaluator.evaluate` replaces the
whole response when `respond` raises, which forfeits the turn, so every entry
point here is defensive and falls back to the previous constant rather than
propagating an exception.
"""
from __future__ import annotations

from typing import Sequence

from needle.language import DEFAULT as DEFAULT_LANGUAGE
from needle.language import phrases

# How many disclosed values to name before summarising. Reading a sentence with
# six clauses in it is worse than reading "and 3 more".
_NAMED_VALUES = 3


def _readable(value: str) -> str:
    """A catalog signature as a customer would read it back."""
    text = " ".join(str(value).split())
    return text[:60].rstrip() + "..." if len(text) > 60 else text


def _join(values: Sequence[str], joiner: str = "and") -> str:
    named = [_readable(value) for value in values[:_NAMED_VALUES]]
    remainder = len(values) - len(named)
    if remainder > 0:
        named.append(f"{remainder} more" if joiner == "and" else f"+{remainder}")
    if not named:
        return ""
    if len(named) == 1:
        return named[0]
    return ", ".join(named[:-1]) + f" {joiner} " + named[-1]


def _category(category: str) -> str:
    readable = " ".join(str(category).split())
    return readable if readable else "items"


def turn_record(
    *,
    turn: int,
    category: str,
    wanted: Sequence[str],
    unwanted: Sequence[str],
    candidates: int | None,
    identified: bool,
    emitted: Sequence[str],
    withheld: bool,
    sampled: bool = False,
    language: str = DEFAULT_LANGUAGE,
) -> dict:
    """What this turn did, as the input `message_for` renders.

    Ephemeral by design. `needle/lens.py` records the retained, far richer
    per-turn trace -- constraint provenance, per-attribute expected candidate
    reduction, per-recommendation matches and conflicts -- and there is no
    reason for a second, weaker one to exist beside it. This exists only to
    keep the sentence-building separable from the agent and therefore testable.
    """
    if identified:
        basis, confidence = "identified", "certain"
    elif candidates:
        basis = "disclosure_bucket"
        confidence = "narrowing" if candidates > 1 else "certain"
    else:
        basis, confidence = "ranking", "exploring"
    return {
        "options": ("", ()),
        "language": str(language or DEFAULT_LANGUAGE),
        "sampled": bool(sampled),
        "turn": int(turn),
        "category": _category(category),
        "wanted": [str(value) for value in wanted],
        "unwanted": [str(value) for value in unwanted],
        "candidates": None if candidates is None else int(candidates),
        "identified": bool(identified),
        "basis": basis,
        "confidence": confidence,
        "withheld": bool(withheld),
        "emitted": [str(value) for value in emitted],
    }


def message_for(record: dict, *, asking: bool) -> str:
    """One sentence the customer can act on, true of the state that produced it."""
    try:
        return _message_for(record, asking=asking)
    except Exception:  # noqa: BLE001 - a dull message beats a forfeited turn
        return (
            "What else matters most for the item you want?"
            if asking
            else "These are the closest catalog matches for your current request."
        )


def _message_for(record: dict, *, asking: bool) -> str:
    language = str(record.get("language") or DEFAULT_LANGUAGE)
    if language != DEFAULT_LANGUAGE:
        return _translated_message_for(record, asking=asking, language=language)
    category = record.get("category") or "items"
    generic_category = " ".join(str(category).lower().split()) == "items"
    wanted = list(record.get("wanted") or ())
    category_key = " ".join(str(category).lower().split())
    wanted = [
        value for value in wanted
        if " ".join(str(value).lower().split()) != category_key
    ]
    unwanted = list(record.get("unwanted") or ())
    candidates = record.get("candidates")
    facet, options = record.get("options") or ("", ())
    if asking and facet and options:
        # The choices are the values the remaining products actually carry, so
        # an option is never offered that nothing satisfies.
        #
        # Counts are shown only when they are counts of the whole candidate set.
        # The set is sampled when it is large, and printing "black (123)" beside
        # "1034 candidates" would be quoting a number of a different thing.
        if record.get("sampled"):
            offered = ", ".join(value for value, _ in options)
        else:
            offered = ", ".join(f"{value} ({count})" for value, count in options)
        tail = (
            f" Which {facet}? {offered}."
            " You can also tell me anything else you prefer."
        )
    else:
        tail = " What else matters?" if asking else ""

    if unwanted:
        ruled_out = f" I have ruled out {_join(unwanted)}."
    else:
        ruled_out = ""

    if record.get("identified") or (candidates == 1 and wanted):
        scope = "in the catalog" if generic_category else f"among {category}"
        return (
            f"One candidate remains {scope} using {_join(wanted)}, so that is "
            f"what I am showing.{ruled_out}"
        ).strip()

    if not wanted:
        opening = (
            "I need one more detail to narrow the catalog"
            if generic_category
            else f"I am starting with {category}"
        )
        if asking and facet and options:
            return f"{opening}.{ruled_out}{tail}".strip()
        return (
            f"{opening}. Tell me the one thing that matters most "
            f"and I will narrow it down.{ruled_out}"
        ).strip()

    if isinstance(candidates, int) and candidates > 1:
        shown = "the most reviewed" if record.get("withheld") else "the closest"
        # Two separate claims, each exactly true: the bucket holds this many
        # products, and these are the values disclosed so far. Phrasing it as
        # "N items match X" would be looser than the state supports, because the
        # bucket unions several plausible parses of the same clause and is not
        # keyed on X alone.
        scope = "in the catalog" if generic_category else f"among {category}"
        return (
            f"I have {candidates} candidates {scope} and am narrowing with "
            f"{_join(wanted)}. Showing {shown}.{ruled_out}{tail}"
        ).strip()

    scope = "the catalog" if generic_category else category
    return f"I am narrowing {scope} using {_join(wanted)}.{ruled_out}{tail}".strip()


__all__ = ["turn_record", "message_for"]


def _translated_message_for(record: dict, *, asking: bool, language: str) -> str:
    """The same turn, said in the language the customer wrote in.

    Deliberately a separate path rather than a template pass over the English
    one. The English wording carries distinctions this cannot: "in the catalog"
    against "among boots", "one more detail" against naming the category. Those
    were tuned on the English sentence, and a shared template flattens them, so
    English keeps its own path byte for byte and only a customer who wrote in
    another language reaches this one.

    The templates are fixed sentences with catalog values interpolated. Nothing
    here translates a product: a value stays exactly the string the catalog
    holds, because inventing a translation of a product attribute would assert
    something the catalog does not say. See needle/language.py.
    """
    say = phrases(language)
    stop = say["stop"]
    category = record.get("category") or "items"
    # "items" is the English path's word for "no category known yet", not a
    # catalog value, so it is the one category string that gets translated.
    if " ".join(str(category).lower().split()) == "items":
        category = say["items"]
    wanted = list(record.get("wanted") or ())
    unwanted = list(record.get("unwanted") or ())
    candidates = record.get("candidates")
    facet, options = record.get("options") or ("", ())

    if asking and facet and options:
        offered = (
            ", ".join(value for value, _ in options)
            if record.get("sampled")
            else ", ".join(f"{value} ({count})" for value, count in options)
        )
        chosen = say["choose"].format(facet=say.get(facet, facet))
        tail = f" {chosen} {offered} -- {say['or_other']}{stop}"
    else:
        tail = f" {say['ask']}" if asking else ""

    ruled_out = (
        " " + say["ruled_out"].format(values=_join(unwanted, say["and"])) if unwanted else ""
    )

    if record.get("identified") or (candidates == 1 and wanted):
        head = say["single"].format(category=category, values=_join(wanted, say["and"]))
        return f"{head}{ruled_out}".strip()

    # `narrow` names a count, so it can only be used when there is one. The
    # agent leaves `candidates` unset whenever the bucket was not resolved, and
    # a sentence reading "there are  options left" is worse than not saying it.
    if wanted and isinstance(candidates, int) and candidates > 1:
        head = say["narrow"].format(
            count=candidates, category=category, values=_join(wanted, say["and"])
        )
    elif wanted:
        head = say["going_on"].format(category=category, values=_join(wanted, say["and"]))
    else:
        head = say["start"].format(category=category)
    return f"{head}{ruled_out}{tail}".strip()
