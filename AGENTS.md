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
- The sidecar routes explicit body-control intents through a deterministic `BodySubagent` before the main model. The main agent remains responsible for conversation, planning, knowledge, memory, and read-only command use; the body subagent owns starting, stopping, replacing, and reporting high-level PuppetPlayers tasks.
- If `MINA_API_KEY` is not configured, the sidecar still has a narrow deterministic fallback for safe high-confidence requests: current task status, stop task, follow, chop tree, a few read-only queries, and simple search-result listing. Complex requests should still report that DeepSeek is not configured.
- PuppetPlayers is optional at compile time. If it is not installed on the server, Mina can still chat/search/remember; body tools report unavailable.
- Mina's PuppetPlayers body is execution-only. Companion behavior is implemented through messages and state-aware companion ticks.
- The sidecar treats Fabric actions as a dispatch barrier. Once a tool call produces Minecraft actions, the harness returns them to Fabric immediately; further task progress must come from `/v1/action-results` or `/v1/observations`, not another model subturn based on unsent actions.

Fabric config is generated at runtime in:

```sh
run/config/mina.json
```

Important defaults:

- Sidecar URL: `http://127.0.0.1:18911`
- Body username: `mina`
- Companion tick: disabled by default via `enableCompanion=false`
- Companion tick interval when enabled: `200` ticks
- Action permission policy: OP or `actionAllowlist`
- Denied server commands include `op`, `deop`, `stop`, `ban`, `whitelist`, and save-control commands.

## Runtime Dependencies

For body execution, install these server-side mods alongside `mina`:

- Fabric API for Minecraft `1.21.11`
- Fabric Language Kotlin
- PuppetPlayers `1.3.1+1.21.11`

PuppetPlayers provides the `/puppet` command used by Mina's action bridge:

- spawn/join/leave
- `minecraft:move_to`
- `minecraft:look` on PuppetPlayers `1.3.1+1.21.11` accepts yaw/pitch rotation, not target coordinates. Mina's action bridge converts `look_at_position` target coordinates into `minecraft:look <yaw> <pitch>`.
- `minecraft:attack`
- `minecraft:use`
- `minecraft:swap_slot`
- `minecraft:delay` is chain-only. Use Mina's `body_chain` action for ordered sequences such as move, look, hold attack, delay, release attack.
- interrupt/stop actions and chain control

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
- Body tools require action permission.
- Allowed body tools schedule Fabric actions.

Live real-game E2E:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite live --require-live-model
```

This is the only E2E runner. It loads `agent_service/.env`, requires a real DeepSeek `MINA_API_KEY`, refuses loopback/mock DeepSeek endpoints, starts the real `mina_agent.app` sidecar, starts a deterministic SearXNG-compatible search fixture unless `--searxng-url` is provided, and starts a dedicated Fabric/PuppetPlayers server in `build/e2e/server`, then drives declarative `/mina-test` scenarios. Built-in scenarios live in `agent_service/src/mina_agent/e2e/scenarios.py`; additional JSON manifests can be loaded with `--manifest path/to/scenarios.json`. `/mina-test` is registered only when the server runs with `-Dmina.testHarness=true` through the `runE2eServer` Gradle task.

Useful suites:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite live --list-scenarios
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite body
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite safety
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --scenario read_only_time_live_model
```

Each run writes artifacts to `build/e2e/runs/<timestamp>/`: `run_manifest.json`, root `summary.json`, `trace-summary.json`, root `trace.jsonl`, `scenario_summaries.jsonl`, `server.log`, `sidecar.log`, `sidecar-stdout.log`, per-scenario `manifest.json`, per-scenario `summary.json`, per-scenario `final_snapshot.json`, per-scenario `trace.json`, per-scenario `trace.jsonl`, and `model_calls.jsonl`. Use `--list-scenarios` to print selected scenario metadata and tag counts without a live API key or server startup. `run_manifest.json` records the selected scenarios, tag counts, and runner options. Root `summary.json` records the git branch, commit, dirty state, tag counts, per-scenario duration, model call counts, and token totals; root `scenario_summaries.jsonl` preserves one compact summary per selected scenario; per-scenario `summary.json` records status, duration, event/tool/action counts, exposed/requested model tool names, model token totals, and final snapshot summary; `trace-summary.json` includes model call counts and token totals. Root `trace.jsonl` aggregates per-scenario records for whole-run audit; per-scenario `manifest.json` preserves the executed rubric and invariants; per-scenario `final_snapshot.json` stores compact final world evidence; per-scenario `trace.jsonl` includes sidecar model/tool/action records plus structured E2E harness events for scenario pass/fail/retry, server stdin commands, matched stdout lines, and poll attempts. Response-content invariants check both model traces and player-visible server output; model-facing scenarios also assert that private low-level body/Fabric tools are not exposed in model-call tool lists. Failed scenarios keep best-effort per-scenario trace artifacts; on scenario failure, `failure.json` attempts to include a compact `/mina-test snapshot` hash/summary if the server is still running. The runner waits for the matching `request_id` turn response before advancing request steps, so stale chat output from a previous command cannot satisfy the next step. The sidecar exposes `/v1/model-calls`, `/v1/tool-calls`, `/v1/action-events`, `/v1/tasks`, `/v1/tasks/{task_id}/events`, and `/v1/traces/{request_id}` for focused debugging. Trace outputs compact large snapshots as `snapshot_hash` plus `snapshot_summary`, not raw world snapshots.

The live suite covers deterministic body-router and companion-tick scenarios, including action-permission denials, low-health alerts, low-hunger alerts, nearby-hostile alerts, and healthy-player silence, that should make zero model calls, plus model-facing scenarios that must call real DeepSeek for smalltalk without tool use, read-only world queries, web search, prompt-injection resistance, and safety refusals. Do not add E2E scenarios backed by scripted sidecars, fake DeepSeek, or offline fallback mode; keep those concerns in unit tests only.

## Iteration Workflow

The working target is a usable Minecraft agent that can answer knowledge questions through sidecar tools, run tightly constrained read-only Minecraft commands, and control the PuppetPlayers body for simple verified tasks such as following a player and chopping a tree.

For every behavior change:

1. Keep model-facing tools high-level and safe. Minecraft mutations must go through Fabric actions and monitors; do not expose raw movement, attack, write-command, or unrestricted MCP tools to the model.
2. Add or update declarative E2E coverage in `agent_service/src/mina_agent/e2e/` and extend `/mina-test` only through safe fixture/assertion commands. E2E must use the real sidecar and real DeepSeek API; use unit tests, not mock E2E runners, for isolated policy or parser checks.
3. Run the baseline checks:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test pytest -q
GRADLE_USER_HOME=$PWD/.gradle ./gradlew build --no-daemon
```

4. Run the relevant headless E2E scenarios with a real DeepSeek key configured in `agent_service/.env` or the environment. At minimum, keep the live body suite passing before committing body-control changes:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite body
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite safety
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite live
```

5. Inspect `build/e2e/runs/<timestamp>/summary.json`, `trace-summary.json`, per-scenario `trace.jsonl`, `server.log`, and `sidecar.log` when an E2E scenario fails. The real sidecar also exposes `/v1/model-calls`, `/v1/tool-calls`, `/v1/action-events`, `/v1/tasks`, and `/v1/tasks/{task_id}/events` for focused debugging. Fix the policy, monitor, or skill runtime first; do not compensate by letting the model directly call lower-level body primitives.
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
- If adding tests or game tests, document the new command in this file and keep `./gradlew build` as the baseline verification step.
- Do not commit generated files from `.gradle/`, `build/`, `run/`, `.uv-cache/`, `.pytest_cache/`, `agent_service/.venv/`, or `agent_service/data/`.
