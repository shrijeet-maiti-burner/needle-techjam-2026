# EXP-027 answer the customer in the language they wrote in

Status: measured and landed. Seven languages: en, es, fr, de, hi, ja, zh.

## Registered question

"Can the agent conduct a session in the customer's language without changing a
single thing about the English session it already has?"

Answer: yes, and it is asserted rather than argued. Every message emitted across
all 200 public sessions is byte-identical to `64e2158`.

## The design decision, and why the first one was wrong

The first version of this work made the English sentence a template and filled
it per language. That is the obvious design and it is worse, because the English
wording carries distinctions a shared template flattens:

| situation | English says | a shared template would say |
|---|---|---|
| no category known | "I need one more detail to narrow the catalog" | "Starting from items." |
| category known | "among boots" | "in boots" |
| one candidate | "One candidate remains among boots" | "One left in boots" |

Those were tuned on the English sentence in #28. So English keeps its own code
path, unchanged, and `_translated_message_for` exists beside it. Only a customer
who wrote in another language reaches the second path.

## What is measured

| | `64e2158` | with this |
|---|---|---|
| every emitted message, 200 sessions | sha256 `be0a2a9f1e808557` | **identical** |
| public score / HR / MRR / MTTC | 0.978500 / 1.0000 / 0.996667 / 2.025 | identical |
| per-session `best_rank`, `first_hit_turn` | | identical on all 200 |
| robustness `summary`, `comparison`, `gate_failures` | | byte-identical |
| tests | 450 | 462 |

## Decisions worth recording

**Detection is per session, not per message.** `"Sí, cuero."` is three words and
reads as English on its own. A customer who opened in Spanish should not be
answered in English because their second message was short. The opening decides;
a pin overrides.

**An unsupported pinned code is ignored, and detection stands.** An earlier
revision fell back to English. That is worse: a caller passing a locale we
cannot speak has told us nothing, while a customer writing in kanji has told us
something. Falling back would answer a Japanese customer in English because
their storefront sent `xx`.

**Catalog values are never translated.** A product attribute stays exactly the
string the catalog holds. Inventing a translation of an attribute would assert
something the catalog does not say. Pinned by a test across every language.

**Category recovery reuses `CatalogIndex.resolve_category`.** An earlier revision
carried its own `resolve_coarse_category`; it is not here, because
`resolve_category` already resolves against the same closed vocabulary with
token-aligned fuzzy recovery and a uniqueness margin. A second resolver would be
a weaker duplicate of it.

It declines rather than guessing:

```
"Busco unas botas de cuero."   lexicon -> "boots"   resolved -> ""  (filed under several)
"我在找靴子。"                   lexicon -> "shoes boots"  resolved -> "shoes boots"
```

An unresolved noun still reaches retrieval as query text; it is only refused as
a bucket key.

**English cannot enter the lexicon branch.** `opening_category_signature` keys on
the simulator's own request grammar. A non-English request is differently
ordered, not unparseable, so the lexicon is the fallback; an English request
either states a category in that grammar or genuinely has none. Asserted in both
directions, and the byte-identical transcript above is the same fact measured
end to end.

## Limits

- Detection is script ranges plus Latin function-word cues with a two-cue
  threshold and a 30% script-share floor. A single Latin word in isolation is
  not enough evidence and reads as English, which is the safe direction.
- The seven languages are a fixed set. An eighth needs a phrase table; nothing
  is inferred at runtime.
- Non-English category recovery covers a shopping noun lexicon, not open
  vocabulary. A request naming something outside it resolves to nothing and the
  session proceeds unqualified rather than wrongly qualified.

## Reproduction

```bash
python3 -m pytest tests/test_multilingual_reply.py tests/test_language.py \
    tests/test_language_override.py
python3 scripts/evaluate.py --output results.json
python3 scripts/run_robustness.py --agent starter.agent:Agent
```

Pins: base `64e2158`, official `local_evaluator.py` at source commit
`34078351e1c3615e5505a2e829600b56a542e462`, Python 3.12, macOS, stdlib only,
zero tokens.
