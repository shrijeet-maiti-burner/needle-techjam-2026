# Submission disclosure inventory

The final Devpost project description must truthfully list all development tools, APIs, libraries and frameworks, and datasets and assets actually used. Inclusion here records use; it does not imply endorsement or a technical dependency. Required naming and version granularity is still unresolved.

**The assistant rows are deliberately present.** The rules require the Devpost
description to truthfully list all development tools actually used, and an
assistant used to write code is one. It is not a runtime dependency: nothing in
the scored path calls a model, the agent is standard library only, and the
official run reports zero tokens. Omitting a tool that was used is the kind of
defect that invalidates a submission, and it costs nothing to state.

Each team member must confirm this inventory covers what they personally used and add
anything it does not. It was written from one contributor's own use and cannot
speak for the others, so confirmation is recorded per person below rather than
assumed.

## Confirmation

| Contributor | Confirmed | Added on confirming |
|---|---|---|
| Athul Krishna Boban (`athul1810`) | 1 September 2026 | pytest, Node.js, GitHub CLI, macOS shell utilities |
| Shrijeet Maiti (`shrijeet-maiti-burner`) | 1 September 2026 | Visual Studio Code, ChatGPT |
| Aryaman Anand (`AryamanAnand19`) | 1 September 2026 | none |
| Yazhiniyan (`Yazhiniyan99`) | 1 September 2026 | none |

An unconfirmed row is not a claim that nothing is missing. It means nobody has
checked that person's own use against this list yet.

## Verified current inventory

| Category | Item | Role | Final runtime dependency |
|---|---|---|---|
| development tool | Git | version control | no |
| development tool | GitHub and GitHub Actions | collaboration and CI | no |
| development tool | Visual Studio Code | source editing, review and local test execution | no |
| development tool | PowerShell | local automation and release checks | no |
| development tool | Google Chrome headless mode and DevTools Protocol | responsive rendered-interface QA and rendered contrast measurement | no |
| development tool | Node.js | drives the DevTools Protocol session for that interface QA | no |
| development tool | GitHub CLI (`gh`) | opening and reading pull requests | no |
| development tool | macOS shell and standard command-line utilities (zsh, `curl`, `unzip`, `shasum`, `sysctl`) | local release checks, archive extraction, checksum and machine facts | no |
| development tool | AI coding assistant (Anthropic Claude, via Claude Code) | authoring and reviewing source, tests, and evidence records during development | no |
| development tool | AI coding assistant (OpenAI Codex) | authoring, reviewing, testing, release checks, and repository integration during development | no |
| development tool | AI assistant (OpenAI ChatGPT) | early ideation and planning | no |
| language/runtime | Python 3.10+ | implementation and tests | yes |
| library/framework | Python standard library, including `sqlite3` FTS5 | retrieval, state, scripts, and tests | yes |
| library/framework | pytest | local test runner during development; CI and the archive both run the suite under `unittest`, and nothing imports it | no |
| API | official local Python `Agent` interface | evaluator integration | yes |
| dataset/asset | TikTok TechJam 2026 participant kit | public evaluator, sessions, schema, and catalog package | evaluator-side |
| dataset/asset | Amazon Reviews 2023, `Clothing_Shoes_and_Jewelry` derivative | source of the frozen competition catalog | evaluator-side |
| generated asset | catalog-bound SQLite signature index | startup optimisation; reproducibly derived from the frozen catalog | bundled, with source-only fallback |

## Before submission

- copy this confirmed inventory into the final Devpost project description;
- add every external or local model, API, package, framework, generated asset, and source dataset actually used;
- record versions, licenses, costs, token usage, latency, network requirements, and fallback behavior where applicable;
- remove planned items that were never used;
- reconcile this inventory with the frozen dependency manifest, report, demo, and archive contents.

## What was checked, not assumed

Verified on 31 August and 1 September 2026, against the extracted archive
rather than the repository:

- no module reachable from `starter.agent` imports a network-capable library,
  across the 11 modules in the scored path;
- no shipped file references an external service. The only external links in
  the archive are two attributions in `README.md`, to the participant kit
  repository and to the source dataset, and neither is fetched at runtime;
- the interface loads no webfont, script or stylesheet from anywhere. It names
  font families that the machine either has or falls back from;
- the official run reports zero prompt tokens and zero completion tokens across
  all 405 responses, which is what "no model in the scored path" looks like
  from the evaluator's side;
- the pytest row is a development tool and nothing more: no file in the
  repository imports it, and the final `python -m unittest discover -s tests`
  run completed 588 tests with 585 passes and three expected pre-archive asset
  skips, which is the runner used by CI and the archive instructions.
