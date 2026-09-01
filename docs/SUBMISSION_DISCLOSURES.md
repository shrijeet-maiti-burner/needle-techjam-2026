# Tools, APIs, libraries, datasets, and assets

This is the confirmed disclosure inventory for Needle. All four contributors
reviewed it on 1 September 2026. Development tools are listed separately from
runtime dependencies so their role is unambiguous.

## Inventory

| Category | Item | Role | Runtime dependency |
|---|---|---|---|
| development tool | Git | version control | no |
| development tool | GitHub and GitHub Actions | collaboration, review, hosting, and CI | no |
| development tool | Visual Studio Code | source editing, review, and local test execution | no |
| development tool | PowerShell | local automation and release checks | no |
| development tool | Google Chrome headless mode and DevTools Protocol | rendered responsive-interface and contrast QA | no |
| development tool | Node.js | DevTools Protocol driver for interface QA | no |
| development tool | GitHub CLI (`gh`) | pull-request and repository operations | no |
| development tool | macOS shell and standard command-line utilities (`zsh`, `curl`, `unzip`, `shasum`, `sysctl`) | independent archive, checksum, and machine verification | no |
| development tool | Anthropic Claude via Claude Code | source, test, evidence, and review assistance during development | no |
| development tool | OpenAI Codex | source, test, release, review, and repository-integration assistance during development | no |
| development tool | OpenAI ChatGPT | early ideation and planning | no |
| language/runtime | Python 3.10+ | implementation and test runtime | yes |
| library/framework | Python standard library, including `sqlite3` FTS5 | state, retrieval, ranking, scripts, server, and tests | yes |
| library/framework | pytest | supplementary local test runner; production and CI do not import it | no |
| API | official local Python `Agent` interface | evaluator integration | yes, evaluator-side |
| external API | none | no hosted service is called | no |
| dataset/asset | TikTok TechJam 2026 participant kit | evaluator, sessions, schema, and frozen catalog package | evaluator-side |
| dataset/asset | Amazon Reviews 2023 `Clothing_Shoes_and_Jewelry` derivative | source of the frozen competition catalog | evaluator-side |
| generated asset | catalog-bound SQLite signature index | validated startup optimization, rebuilt in process if absent or mismatched | bundled |

## Runtime boundary

The scored path uses no LLM, embedding model, external API, vector database,
network request, credential, or model download. It imports only Python standard
library modules. The optional storefront also uses no external script,
stylesheet, font, package, or hosted service.

The generated SQLite index is derived only from the frozen catalog. Its
manifest records the schema, catalog SHA-256, parser fingerprint, asset
SHA-256, and size. The loader verifies those bindings before use and rebuilds
an equivalent in-memory index rather than trusting a stale or corrupt asset.

## Verification

- no module reachable from `starter.agent` imports a network-capable
  third-party library;
- the official 200-session run reports zero prompt and completion tokens across
  all 405 responses;
- no shipped file contains a credential or secret, and no shipped code fetches
  an external resource;
- the interface writes customer and catalog content through safe text sinks and
  binds only to the loopback interface;
- `python -m unittest discover -s tests` runs 589 tests in a source checkout:
  586 pass and three expected asset checks skip until the untracked release
  asset is present.
