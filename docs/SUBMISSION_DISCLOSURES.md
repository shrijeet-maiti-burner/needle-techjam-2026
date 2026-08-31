# Submission disclosure inventory

The final Devpost project description must truthfully list all development tools, APIs, libraries and frameworks, and datasets and assets actually used. Inclusion here records use; it does not imply endorsement or a technical dependency. Required naming and version granularity is still unresolved.

**The assistant row is deliberately present.** The rules require the Devpost
description to truthfully list all development tools actually used, and an
assistant used to write code is one. It is not a runtime dependency: nothing in
the scored path calls a model, the agent is standard library only, and the
official run reports zero tokens. Omitting a tool that was used is the kind of
defect that invalidates a submission, and it costs nothing to state.

Each team member must confirm this row covers what they personally used and add
anything it does not. It was written from one contributor's own use and cannot
speak for the others.

## Verified current inventory

| Category | Item | Role | Final runtime dependency |
|---|---|---|---|
| development tool | Git | version control | no |
| development tool | GitHub and GitHub Actions | collaboration and CI | no |
| development tool | PowerShell | local automation and release checks | no |
| development tool | Google Chrome headless mode and DevTools Protocol | responsive rendered-interface QA | no |
| development tool | AI coding assistant (Anthropic Claude, via Claude Code) | authoring and reviewing source, tests, and evidence records during development | no |
| development tool | AI coding assistant (OpenAI Codex) | authoring, reviewing, testing, release checks, and repository integration during development | no |
| language/runtime | Python 3.10+ | implementation and tests | yes |
| library/framework | Python standard library, including `sqlite3` FTS5 | retrieval, state, scripts, and tests | yes |
| API | official local Python `Agent` interface | evaluator integration | yes |
| dataset/asset | TikTok TechJam 2026 participant kit | public evaluator, sessions, schema, and catalog package | evaluator-side |
| dataset/asset | Amazon Reviews 2023, `Clothing_Shoes_and_Jewelry` derivative | source of the frozen competition catalog | evaluator-side |
| generated asset | catalog-bound SQLite signature index | startup optimisation; reproducibly derived from the frozen catalog | bundled, with source-only fallback |

## Before submission

- confirm the development-tool rows above cover what every contributor used, and add anything missing;
- add every external or local model, API, package, framework, generated asset, and source dataset actually used;
- record versions, licenses, costs, token usage, latency, network requirements, and fallback behavior where applicable;
- remove planned items that were never used;
- reconcile this inventory with the frozen dependency manifest, report, demo, and archive contents.
