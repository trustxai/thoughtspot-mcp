# Changelog

## [0.1.2](https://github.com/trustxai/thoughtspot-mcp/compare/v0.1.1...v0.1.2) (2026-07-06)


### Bug Fixes

* **tml:** cap export_tml result under the 1 MB tool-result limit ([#13](https://github.com/trustxai/thoughtspot-mcp/issues/13)) ([44e8345](https://github.com/trustxai/thoughtspot-mcp/commit/44e8345c5762bea1cd6a8824f4ddc783178d9051)), closes [#12](https://github.com/trustxai/thoughtspot-mcp/issues/12)

## [0.1.1](https://github.com/trustxai/thoughtspot-mcp/compare/v0.1.0...v0.1.1) (2026-07-03)


### Bug Fixes

* **deps:** move mcp[cli] extra out of runtime into dev group ([#10](https://github.com/trustxai/thoughtspot-mcp/issues/10)) ([f3e970e](https://github.com/trustxai/thoughtspot-mcp/commit/f3e970e8c5aad21f8a0079dfaaa7010b32ef8e38))

## 0.1.0 (2026-07-03)


### Features

* add connection tools (create/search/get/update/status/delete) ([#4](https://github.com/trustxai/thoughtspot-mcp/issues/4)) ([ce54393](https://github.com/trustxai/thoughtspot-mcp/commit/ce54393867bd62b818eafdd405cdb6e82d75ce9b))
* **data:** implement search_data, liveboard_data, answer_data tools ([#5](https://github.com/trustxai/thoughtspot-mcp/issues/5)) ([0c749a7](https://github.com/trustxai/thoughtspot-mcp/commit/0c749a7692b412690f695f1194eaa2e4d5b4080e))
* implement report export tools (T1.5) ([#3](https://github.com/trustxai/thoughtspot-mcp/issues/3)) ([6cd3124](https://github.com/trustxai/thoughtspot-mcp/commit/6cd31245e3062857d2afa5ffa257e62559db89e2))
* **metadata:** add search_metadata and delete_metadata tools ([#2](https://github.com/trustxai/thoughtspot-mcp/issues/2)) ([98048b8](https://github.com/trustxai/thoughtspot-mcp/commit/98048b84c4a2bce814f50766ac6155b32b6716d9))
* Phase 0 foundation ported from airbyte-mcp ([26119f4](https://github.com/trustxai/thoughtspot-mcp/commit/26119f4b13d01ffc03613d8d392adbc26f90b896))
* **tools:** add TML export/import tools (T1.2) ([#1](https://github.com/trustxai/thoughtspot-mcp/issues/1)) ([334d651](https://github.com/trustxai/thoughtspot-mcp/commit/334d65173172b4fb9596c82a739280ff257ac5b5))


### Bug Fixes

* **config:** default missing host scheme to https ([#9](https://github.com/trustxai/thoughtspot-mcp/issues/9)) ([e8bbfbc](https://github.com/trustxai/thoughtspot-mcp/commit/e8bbfbc26da2bf75f28a16c39d76e931e3a1f40f))
* **tests:** isolate unit tests from ambient .env credentials ([#7](https://github.com/trustxai/thoughtspot-mcp/issues/7)) ([19a2ded](https://github.com/trustxai/thoughtspot-mcp/commit/19a2ded1b53ecb6d7f1a6262a624b87449b50890))

## Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
