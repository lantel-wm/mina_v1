# AGENTS.md

## Project State

This repository contains the `mina` Minecraft Fabric mod and a Python sidecar agent service.

- Minecraft: `1.21.11`
- Mod id/name: `mina`
- Java target: `21`
- Fabric Loader: `0.19.2`
- Fabric API: `0.141.3+1.21.11`
- Fabric Loom plugin: `net.fabricmc.fabric-loom-remap` `1.16.1`
- Gradle Wrapper distribution: `gradle-9.4.1-bin.zip`
- Mappings: Mojang official mappings via `loom.officialMojangMappings()`

Important source files:

- Main mod initializer: `src/main/java/com/mina/MinaMod.java`
- Fabric command/tick/action code: `src/main/java/com/mina/game/`
- Fabric config model: `src/main/java/com/mina/config/MinaConfig.java`
- Fabric sidecar HTTP client: `src/main/java/com/mina/net/SidecarClient.java`
- Python sidecar service: `agent_service/src/mina_agent/`
- Client initializer: `src/client/java/com/mina/client/MinaClient.java`
- Mod metadata: `src/main/resources/fabric.mod.json`
- Version and dependency pins: `gradle.properties`
- Build logic: `build.gradle`

Generated outputs and caches are intentionally ignored:

- `.gradle/`
- `build/`
- `run/`
- `out/`
- `.uv-cache/`
- `.pytest_cache/`
- `agent_service/.venv/`
- `agent_service/.pytest_cache/`
- `agent_service/data/`

## Runtime Architecture

Mina uses a sidecar architecture.

- The Fabric mod registers `/mina <content>` and `/mina-admin ...`, samples Minecraft player/world state, and executes approved Minecraft actions on the server thread.
- The Python sidecar handles DeepSeek API calls, agent tool loops, SQLite memory, SearXNG search, and future MCP integration points.
- Puppet/body control is temporarily disabled. Mina should focus on text conversation, knowledge/search, memory, tightly constrained read-only Minecraft commands, and player/world state observation.
- Model-facing tools are limited to `web_search`, `memory_search`, `memory_write`, `run_read_only_command`, and configured non-Minecraft-write `mcp_call`.
- Explicit follow/chop/body-status requests must be refused locally with the paused-body message and must not call the model, expose body tools, or schedule Fabric body actions.
- If `MINA_API_KEY` is not configured, the sidecar still has a narrow deterministic fallback for safe high-confidence requests: player/world observation, a few read-only queries, memory recall/write, and simple search-result listing. Complex requests should still report that DeepSeek is not configured.
- PuppetPlayers remains optional at compile time and is currently used by the E2E harness for fake requester players, not as an enabled Mina body-control runtime.
- `/v1/action-results`, `/v1/observations`, `/v1/tasks`, and `/v1/tasks/{task_id}` are still present for compatibility and debugging, but body task progression is disabled in the default runtime.

Fabric config is generated at runtime in:

```sh
run/config/mina.json
```

Important defaults:

- Sidecar URL: `http://127.0.0.1:18911`
- Body username: `mina`
- Body control: disabled by default via `enableBody=false`
- Companion tick: disabled by default via `enableCompanion=false`
- Companion tick interval when enabled: `200` ticks
- Action permission policy: OP or `actionAllowlist`
- Denied server commands include `op`, `deop`, `stop`, `ban`, `whitelist`, and save-control commands.

## Runtime Dependencies

Current production focus does not require a Mina PuppetPlayers body.

- Fabric API for Minecraft `1.21.11` is required.
- Fabric Language Kotlin and PuppetPlayers `1.3.1+1.21.11` are optional for the current runtime.
- The live E2E harness still installs PuppetPlayers so `/mina-test` can create a fake requester player (`mina_tester`) in a headless dedicated server.
- Do not re-enable body execution, body actions, or model-facing body tools unless the project deliberately resumes the body-control track.

## Build

Use the project wrapper. The host may not have a global `gradle` command.

```sh
./gradlew build
```

For reproducible local-agent runs, prefer keeping Gradle's cache inside the repository:

```sh
GRADLE_USER_HOME=$PWD/.gradle ./gradlew build --no-daemon
```

Successful build output includes:

- `build/libs/mina-1.0.0.jar`
- `build/libs/mina-1.0.0-sources.jar`

The first build can take several minutes because Gradle, Minecraft, Fabric, and remapped dependencies are downloaded.

## Test And Verification

The baseline Java verification command is the full Gradle build:

```sh
GRADLE_USER_HOME=$PWD/.gradle ./gradlew build --no-daemon
```

This command verifies:

- Java source compilation for main and client source sets.
- `fabric.mod.json` resource processing.
- Jar creation.
- Fabric Loom remapping via `remapJar` and `remapSourcesJar`.

Expected current result:

```text
BUILD SUCCESSFUL
```

Known non-fatal output:

- Loom prints the Microsoft official mappings license notice.
- macOS may print `Could not start the FSEvents stream`; the current build still succeeds.
- Gradle currently reports Java test tasks as `NO-SOURCE`.

Python sidecar tests:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test pytest -q
```

This verifies:

- DeepSeek defaults target `deepseek-v4-flash`.
- Thinking defaults to disabled.
- Model-facing tools exclude paused body-control and private Fabric action primitives.
- Player/world observation, read-only command routing, memory, search, and paused-body refusal policies remain covered.
- Dormant body skill/runtime tests may remain skipped or internal-only while body control is paused.

Live real-game E2E:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite live --require-live-model
```

This is the only E2E runner. It loads `agent_service/.env`, requires a real DeepSeek `MINA_API_KEY`, refuses loopback/mock DeepSeek endpoints, starts the real `mina_agent.app` sidecar on an automatically selected free local port by default, starts a deterministic SearXNG-compatible search fixture unless `--searxng-url` is provided, and starts a dedicated Fabric/PuppetPlayers server in `build/e2e/server`, then drives declarative `/mina-test` scenarios. Built-in scenarios live in `agent_service/src/mina_agent/e2e/scenarios.py`; additional JSON manifests can be loaded with `--manifest path/to/scenarios.json`. `/mina-test` is registered only when the server runs with `-Dmina.testHarness=true` through the `runE2eServer` Gradle task. Body fixtures are disabled by default; use `--enable-body-fixtures` only for legacy/debug work outside the current target.

Latest E2E usage:

- Gate command: `UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite live --require-live-model`
- List selected scenarios without API key, sidecar, or server startup: `UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite live --list-scenarios`
- Run one scenario after a successful build: `UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --scenario knowledge_search_live_model --skip-build --require-live-model`
- Run focused suites: `--suite safety`, `--suite body`, or `--suite all`. The default suite is `live`. The `body` suite currently checks paused-body refusal behavior only.
- Load external scenario manifests: `--manifest path/to/scenarios.json --scenario custom_case`. The manifest can be either a list of scenario objects or `{"scenarios": [...]}`.
- Use an external SearXNG instead of the built-in deterministic fixture: `--searxng-url http://127.0.0.1:8888`.
- Use `--skip-build` only when `./gradlew build --no-daemon` has already passed for the current Java sources.

Required live environment:

- `MINA_API_KEY` must be set in `agent_service/.env` or the process environment.
- `MINA_BASE_URL` must point at DeepSeek, not localhost or any mock endpoint.
- `MINA_MODEL` must be a real DeepSeek model such as `deepseek-v4-flash`.
- Missing keys fail fast; the runner never downgrades to fake DeepSeek, scripted sidecars, or offline fallback.

Declarative scenario schema highlights:

- Required: `name`, `fixture`, `steps`, and a human-readable `rubric`.
- Common metadata: `tags`, `timeout`, `retry`, and `keep_artifacts`.
- Step kinds: `request`, `companion_tick`, `world_mutate`, `actor_spawn`, `actor_leave`, `actor_tp`, and `assert`.
- `request` and `companion_tick` steps require a unique `request_id`; `/v1/traces/{request_id}` is the trace join key.
- Trace invariants: `expected_tools`, `forbidden_tools`, `expected_actions`, `forbidden_actions`, `forbidden_model_tools`, `expected_model`, `expected_response_contains`, and `forbidden_response_contains`.
- World invariants: `world_asserts` run `/mina-test assert <name>` after scenario steps.
- The runner validates selected manifests before server startup, including duplicate `request_id` values, missing request ids, unknown step kinds, and invalid `expected_model.mode` values. Supported model modes are `exact` and `at_least`.

Useful suites:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite live --list-scenarios
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite body --require-live-model
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite safety --require-live-model
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --scenario read_only_time_router --require-live-model
```

Each run writes artifacts to `build/e2e/runs/<timestamp>/`: `run_manifest.json`, root `summary.json`, `trace-summary.json`, root `trace.jsonl`, `scenario_summaries.jsonl`, `server.log`, `sidecar.log`, `sidecar-stdout.log`, per-scenario `manifest.json`, per-scenario `summary.json`, per-scenario `final_snapshot.json`, per-scenario `trace.json`, per-scenario `trace.jsonl`, and `model_calls.jsonl`. Use `--list-scenarios` to print selected scenario metadata, timeouts, retries, invariant names, and tag counts without a live API key or server startup. The runner validates selected manifests before server startup, including duplicate `request_id` values, request-like steps missing `request_id`, unknown step kinds, and invalid `expected_model` modes. `run_manifest.json` records the selected scenarios, tag counts, and runner options. Root `summary.json` records git context, scenario/pass/fail counts, tag counts, per-scenario duration, model call counts, and token totals; root `scenario_summaries.jsonl` preserves one compact summary per selected scenario; per-scenario `summary.json` records status, duration, event/tool/action counts, exposed/requested model tool names, model token totals, and final snapshot summary; `trace-summary.json` includes model call counts and token totals. Root `trace.jsonl` aggregates per-scenario records for whole-run audit; per-scenario `manifest.json` preserves the executed rubric and invariants; per-scenario `final_snapshot.json` stores compact final world evidence; per-scenario `trace.jsonl` includes sidecar model/tool/action records plus structured E2E harness events for scenario pass/fail/retry, server stdin commands, matched stdout lines, and poll attempts. Response-content invariants check both model traces and player-visible server output; model-facing scenarios also assert that private low-level body/Fabric tools are not exposed in model-call tool lists. Failed scenarios keep best-effort per-scenario trace artifacts; on scenario failure, `failure.json` attempts to include a compact `/mina-test snapshot` hash/summary if the server is still running. The runner waits for the matching `request_id` turn response before advancing request steps, so stale chat output from a previous command cannot satisfy the next step. The sidecar exposes `/v1/model-calls`, `/v1/tool-calls`, `/v1/action-events`, `/v1/tasks`, `/v1/tasks/{task_id}/events`, and `/v1/traces/{request_id}` for focused debugging. Trace outputs compact large snapshots as `snapshot_hash` plus `snapshot_summary`, not raw world snapshots.

The live suite covers paused-body refusal, local player/world observation, local read-only command routing, and companion-tick scenarios, including action-permission denials, low-health alerts, low-hunger alerts, nearby-hostile alerts, and healthy-player silence, that should make zero model calls, plus model-facing scenarios that must call real DeepSeek for smalltalk without tool use, web search, prompt-injection resistance, and safety refusals. Do not add E2E scenarios backed by scripted sidecars, fake DeepSeek, or offline fallback mode; keep those concerns in unit tests only.

## Iteration Workflow

The working target is a usable Minecraft agent that can answer knowledge questions through sidecar tools, maintain useful memory, run tightly constrained read-only Minecraft commands, route literal allowed read-only command forms without a model call, and answer player/world state questions from Fabric snapshots. Puppet/body control is paused and should stay out of the default runtime.

Allowed read-only Minecraft command forms are intentionally narrow: `seed`, `time query daytime|gametime|day`, `weather query`, `list`, `list uuids`, `locate structure <identifier>`, and `locate biome <identifier>`. Natural high-confidence locate requests may route directly to these forms; write commands must remain rejected before Fabric execution.

For every behavior change:

1. Keep model-facing tools high-level and safe. While body control is paused, do not expose body tools or private Fabric action primitives to the model. Write-capable Minecraft commands and unrestricted MCP tools must remain rejected.
2. Add or update declarative E2E coverage in `agent_service/src/mina_agent/e2e/` and extend `/mina-test` only through safe fixture/assertion commands. E2E must use the real sidecar and real DeepSeek API; use unit tests, not mock E2E runners, for isolated policy or parser checks.
   Use trace invariants and response/action assertions to prove that body-control requests are refused locally and that read-only/world-observation flows do not schedule body actions.
3. Run the baseline checks:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test pytest -q
GRADLE_USER_HOME=$PWD/.gradle ./gradlew build --no-daemon
```

4. Run the relevant headless E2E scenarios with a real DeepSeek key configured in `agent_service/.env` or the environment. At minimum, keep live/safety passing before committing behavior changes, and run the paused-body suite when touching body-refusal paths:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite body --require-live-model
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite safety --require-live-model
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite live --require-live-model
```

5. Inspect `build/e2e/runs/<timestamp>/summary.json`, `trace-summary.json`, per-scenario `trace.jsonl`, `server.log`, and `sidecar.log` when an E2E scenario fails. The real sidecar also exposes `/v1/model-calls`, `/v1/tool-calls`, `/v1/action-events`, `/v1/tasks`, and `/v1/tasks/{task_id}/events` for focused debugging. Fix routing, policy, context, or snapshot formatting first; do not compensate by reintroducing body tools.
6. Commit after a coherent, tested increment. Push only when a git remote is configured and relevant live E2E scenarios pass.

## Run Sidecar

Create `agent_service/.env` from `agent_service/.env.example`, then set at least:

```sh
MINA_API_KEY=...
MINA_MODEL=deepseek-v4-flash
MINA_THINKING=disabled
```

Start the sidecar:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service python -m mina_agent
```

Sidecar logs are written to `agent_service/logs/mina_agent.log` by default, with terminal output preserved. Configure with `MINA_LOG_PATH`, `MINA_LOG_LEVEL`, `MINA_LOG_MAX_BYTES`, and `MINA_LOG_BACKUP_COUNT`.

Health check:

```sh
curl http://127.0.0.1:18911/healthz
```

DeepSeek API implementation notes:

- OpenAI-compatible base URL: `https://api.deepseek.com`
- Chat endpoint: `/chat/completions`
- Model: `deepseek-v4-flash`
- Mina uses raw HTTP instead of an SDK so `thinking`, tool calls, and error handling are explicit.
- v1 sends `stream=false`.
- v1 defaults to `"thinking": {"type": "disabled"}`.
- Internal JSON-output tasks must include `response_format={"type":"json_object"}` and prompt text containing the word `json`.
- If thinking is enabled later, assistant `reasoning_content` must be persisted and replayed during tool-call turns to avoid DeepSeek 400 responses.

## SearXNG

The sidecar expects SearXNG at:

```sh
http://127.0.0.1:8888
```

The local reference project at `/Users/zhaozhiyu/Projects/caster/chatbot` contains a SearXNG Docker setup. Mina calls the SearXNG JSON `/search` endpoint directly.

The E2E runner starts a local deterministic SearXNG-compatible fixture by default so live model tests can assert `web_search` behavior without relying on the public internet. Pass `--searxng-url http://127.0.0.1:8888` to exercise an external SearXNG instance instead.

## MCP

The sidecar includes an MCP registry boundary at `agent_service/src/mina_agent/mcp.py`.

- Default config path: `agent_service/config/mcp.json`
- Override config path with `MINA_MCP_CONFIG_PATH`.
- Default state: no MCP servers configured.
- Config may use either `{"servers": {...}}` or the common `{"mcpServers": {...}}` shape.
- Supported transports are one-request stdio and simple JSON-RPC HTTP/streamable HTTP. Stdio servers are initialized, called, and terminated per request with `timeout_seconds` protection.
- `mcp_call` is model-facing for configured non-Minecraft-write tools; registry helpers also support `tools/list` and `resources/read` for sidecar code.
- Do not grant MCP tools Minecraft write permissions directly; route Minecraft mutations through Fabric actions.

## Commands

Player command:

```text
/mina <content>
```

Admin commands:

```text
/mina-admin status
/mina-admin reload
/mina-admin stop
/mina-admin allow <player-or-uuid>
/mina-admin deny <player-or-uuid>
```

Only OP players can use `/mina-admin`. High-impact tools are limited to OP players or entries in `actionAllowlist`.

## Run Client

Launch a development Minecraft client with:

```sh
./gradlew runClient
```

The runtime directory is `run/`, which is ignored by git.

## Run Server

Launch a development Fabric server with:

```sh
GRADLE_USER_HOME=$PWD/.gradle ./gradlew runServer --no-daemon
```

For real DeepSeek-backed testing, start the sidecar first and set `MINA_API_KEY`.

## Development Notes

- Keep Java source compatible with Java 21.
- Keep the mod id as `mina` unless the metadata, packages, assets, and Gradle config are updated together.
- Keep DeepSeek model defaults on `deepseek-v4-flash`; do not fall back to deprecated `deepseek-chat` or `deepseek-reasoner`.
- Keep Minecraft mutations on the server thread.
- Keep LLM calls, search, memory, and MCP work in the sidecar.
- Keep PuppetPlayers optional at compile time unless a future change needs its Kotlin API directly.
- Keep Puppet/body control disabled in the default runtime until the project explicitly resumes that track.
- If adding tests or game tests, document the new command in this file and keep `./gradlew build` as the baseline verification step.
- Do not commit generated files from `.gradle/`, `build/`, `run/`, `.uv-cache/`, `.pytest_cache/`, `agent_service/.venv/`, or `agent_service/data/`.
