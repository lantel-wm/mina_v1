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
- Built-in E2E scenarios: `agent_service/src/mina_agent/e2e/scenarios.py`

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

- The Fabric mod registers `/mina <content>` and `/mina-admin ...`, samples Minecraft player/world state, and executes approved read-only Minecraft actions on the server thread.
- The Python sidecar handles DeepSeek API calls, agent tool loops, SQLite memory, SearXNG search, and MCP integration points. Runtime turns are LLM-first when `MINA_API_KEY` is configured; deterministic code should stay at safety/tool boundaries, not as player-facing intent routes.
- The current product scope is text conversation, knowledge/search, memory, tightly constrained read-only Minecraft commands, and player/world state observation.
- There is no separate controllable Mina character in the runtime. Movement, mining, attacking, item use, and world mutation tools are not model-facing and should not be reintroduced.
- Model-facing tools are limited to `web_search`, `memory_search`, `memory_write`, `run_read_only_command`, and configured non-Minecraft-write `mcp_call`.
- Do not add hardcoded player-intent routes or local keyword classifiers for observation, search, memory, or commands. Memory is an agent service, not a player-facing command router: stable agent memory is budget-loaded into prompt context, and `memory_search` is an optional model-facing retrieval tool for older or specific stored context.
- Exact allowlisted command forms such as `time query day`, `weather query`, and `list` still go through the live model tool loop when `MINA_API_KEY` is configured; deterministic parsing is only for safety validation and repair prompts, not for direct player-facing routing.
- If `MINA_API_KEY` is not configured, the sidecar returns a configuration error instead of attempting local chat, memory, search, command, or observation fallbacks.
- `/v1/action-results` remains for Fabric command callbacks. `/v1/observations` and `/v1/tasks` are not part of the runtime API.

Fabric config is generated at runtime in:

```sh
run/config/mina.json
```

Important defaults:

- Sidecar URL: `http://127.0.0.1:18911`
- Companion tick: disabled by default via `enableCompanion=false`
- Companion tick interval when enabled: `200` ticks
- Action permission policy: OP or `actionAllowlist`
- Denied server commands include `op`, `deop`, `stop`, `ban`, `whitelist`, and save-control commands.

## Runtime Dependencies

Production runtime requires Fabric API for Minecraft `1.21.11`.

The live E2E harness still installs Fabric Language Kotlin and PuppetPlayers `1.3.1+1.21.11` so `/mina-test` can create the headless requester player `mina_tester`. That dependency is test harness infrastructure, not an agent control surface.

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

## Test And Verification

Baseline Java verification:

```sh
GRADLE_USER_HOME=$PWD/.gradle ./gradlew build --no-daemon
```

Python sidecar tests:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test pytest -q
```

Live real-game E2E:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite live --require-live-model
```

Useful E2E commands:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite live --list-scenarios
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite safety --require-live-model
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --scenario read_only_time_command_live_model --require-live-model
```

The E2E runner loads `agent_service/.env`, requires a real DeepSeek `MINA_API_KEY`, refuses loopback/mock DeepSeek endpoints, starts the real `mina_agent.app` sidecar, starts a deterministic SearXNG-compatible search fixture unless `--searxng-url` is provided, and starts a dedicated Fabric server in `build/e2e/server`. Built-in scenarios cover LLM-mediated player/world observation, read-only command tool selection, web-search tool use and filtering, memory tool use, companion tick alerts, smalltalk, and write-command refusal.

Each run writes artifacts to `build/e2e/runs/<timestamp>/`: `run_manifest.json`, root `summary.json`, `trace-summary.json`, root `trace.jsonl`, `scenario_summaries.jsonl`, `server.log`, `sidecar.log`, `sidecar-stdout.log`, per-scenario `manifest.json`, per-scenario `summary.json`, `final_snapshot.json`, `trace.json`, `trace.jsonl`, and `model_calls.jsonl`. The sidecar exposes `/v1/model-calls`, `/v1/tool-calls`, `/v1/action-events`, and `/v1/traces/{request_id}` for focused debugging.

Declarative scenario schema highlights:

- Required: `name`, `fixture`, `steps`, and a human-readable `rubric`.
- Supported fixture names: `default_world` and `tree_world`.
- Supported step kinds: `request`, `companion_tick`, `world_mutate`, and `assert`.
- `request` and `companion_tick` steps require a unique `request_id`; `/v1/traces/{request_id}` is the trace join key.
- Trace and response assertions: `expected_tools`, `forbidden_tools`, `expected_actions`, `forbidden_actions`, `forbidden_model_tools`, `expected_model`, `expected_response_contains`, and `forbidden_response_contains`.
- World assertions run `/mina-test assert <name>` after scenario steps.
- Built-in safe world assertions include `target_log_present`, `upper_log_present`, and `low_health`.

## Iteration Workflow

The working target is a usable LLM-first Minecraft text agent that can answer knowledge questions through sidecar tools, maintain useful agent memory, run tightly constrained read-only Minecraft commands, and answer player/world state questions from Fabric snapshots. The model should choose when to answer from context versus when to call a safe tool.

Mina memory should follow the same design spirit as Codex `AGENTS.md` and Claude Code `CLAUDE.md`: it serves the agent by preserving stable instructions, player preferences, world facts, plans, promises, and lessons that should influence future turns. Do not require player prompts to mention tool names just to recall normal memory. Do not build hidden keyword classifiers for recall; load a small scoped memory context each turn and let the model decide whether to use `memory_search`.

Allowed read-only Minecraft command forms are intentionally narrow: `seed`, `time query daytime|gametime|day`, `weather query`, `list`, `list uuids`, `locate structure <identifier>`, and `locate biome <identifier>`. These are selected through the model-facing `run_read_only_command` tool and then validated by sidecar/Fabric policy; write commands must remain rejected before Fabric execution.

For each iteration, use this workflow:

1. Review the current repository state before choosing work. Check `git status`, recent commits, relevant changed files, and the latest `build/e2e/runs/<timestamp>/summary.json` plus `trace-summary.json`. When failures exist, inspect per-scenario `trace.jsonl`, `server.log`, and `sidecar.log` before changing code.
2. Refresh agent-architecture context from primary sources or source-level material for Codex, Claude Code, OpenClaw, or similar modern agent systems. Capture only actionable takeaways: instruction layering, context budgeting, memory boundaries, tool policy, harness design, or prompt sectioning.
3. Refresh Minecraft-agent context when the change touches Minecraft behavior. Prefer Voyager, MineDojo, JARVIS-style papers/repos, or other concrete systems. Translate findings into Mina's current text-agent scope; do not reintroduce body control.
4. Choose one small feature, fix, or test improvement. State a concrete plan before development, keep model-facing tools high-level and safe, and avoid private Fabric action primitives, write-capable Minecraft commands, unrestricted MCP tools, or hardcoded player-intent routes.
5. Implement the focused increment. Add or update declarative E2E coverage in `agent_service/src/mina_agent/e2e/` for player-facing behavior, and use unit tests for isolated safety policy, prompt construction, parser checks, or memory behavior. Extend `/mina-test` only through safe fixture/assertion commands.
6. Run baseline checks:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test pytest -q
GRADLE_USER_HOME=$PWD/.gradle ./gradlew build --no-daemon
```

Then run relevant headless E2E scenarios with a real DeepSeek key configured in `agent_service/.env` or the environment:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite safety --require-live-model
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite live --require-live-model
```

7. Inspect new artifacts, iterate on failures, then commit after a coherent tested increment. Push only when a git remote is configured and the relevant live E2E scenarios pass; otherwise state that push was skipped because no remote exists.

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

Health check:

```sh
curl http://127.0.0.1:18911/healthz
```

## SearXNG

The sidecar expects SearXNG at:

```sh
http://127.0.0.1:8888
```

The E2E runner starts a local deterministic SearXNG-compatible fixture by default. Pass `--searxng-url http://127.0.0.1:8888` to exercise an external SearXNG instance instead.

## MCP

The sidecar includes an MCP registry boundary at `agent_service/src/mina_agent/mcp.py`.

- Default config path: `agent_service/config/mcp.json`
- Override config path with `MINA_MCP_CONFIG_PATH`.
- Default state: no MCP servers configured.
- Config may use either `{"servers": {...}}` or the common `{"mcpServers": {...}}` shape.
- Supported transports are one-request stdio and simple JSON-RPC HTTP/streamable HTTP.
- `mcp_call` is model-facing for configured non-Minecraft-write tools.
- Do not grant MCP tools Minecraft write permissions directly.

## Commands

Player command:

```text
/mina <content>
```

Admin commands:

```text
/mina-admin status
/mina-admin reload
/mina-admin allow <player-or-uuid>
/mina-admin deny <player-or-uuid>
```

Only OP players can use `/mina-admin`. High-impact tools are limited to OP players or entries in `actionAllowlist`.

## Run Client

```sh
./gradlew runClient
```

The runtime directory is `run/`, which is ignored by git.

## Run Server

```sh
GRADLE_USER_HOME=$PWD/.gradle ./gradlew runServer --no-daemon
```

For real DeepSeek-backed testing, start the sidecar first and set `MINA_API_KEY`.

## Development Notes

- Keep Java source compatible with Java 21.
- Keep the mod id as `mina` unless metadata, packages, assets, and Gradle config are updated together.
- Keep DeepSeek model defaults on `deepseek-v4-flash`.
- Keep Minecraft mutations on the server thread.
- Keep LLM calls, search, memory, and MCP work in the sidecar.
- If adding tests or game tests, document the new command in this file and keep `./gradlew build` as the baseline verification step.
- Do not commit generated files from `.gradle/`, `build/`, `run/`, `.uv-cache/`, `.pytest_cache/`, `agent_service/.venv/`, or `agent_service/data/`.
