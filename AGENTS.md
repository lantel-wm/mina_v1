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

Headless real-game E2E:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario chop_tree --sidecar scripted
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario follow_player --sidecar scripted
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario read_only_command --sidecar scripted
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario knowledge_query --sidecar scripted
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario banned_command --sidecar scripted
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_banned_command --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario task_status --sidecar scripted
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario stop_follow --sidecar scripted
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario replace_follow_with_chop --sidecar scripted
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario body_unavailable --sidecar scripted
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_chop_tree --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_replace_follow_with_chop --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_action_barrier --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_read_only_command --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_knowledge_query --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_task_status --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_stop_follow --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_permission_denied --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_body_unavailable --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario offline_body_unavailable --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario offline_knowledge_query --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario offline_read_only_command --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario offline_chop_tree --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario offline_follow --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario offline_task_status --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario offline_stop_follow --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario offline_replace_follow_with_chop --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario offline_permission_denied --sidecar service
```

This starts a sidecar and a dedicated Fabric server in `build/e2e/server`, downloads PuppetPlayers/Fabric Language Kotlin into that runtime if missing, and drives the test-only `/mina-test` commands. `/mina-test` is registered only when the server runs with `-Dmina.testHarness=true` through the `runE2eServer` Gradle task. Most scenarios use the deterministic scripted sidecar. The `model_chop_tree`, `model_replace_follow_with_chop`, `model_banned_command`, `model_action_barrier`, `model_read_only_command`, `model_knowledge_query`, `model_task_status`, `model_stop_follow`, `model_permission_denied`, and `model_body_unavailable` scenarios use the real `mina_agent.app` sidecar with local fake DeepSeek/SearXNG servers to verify configured-model body, command, knowledge, status, stop, permission-denied, and body-unavailable tool loops without live API keys. The `offline_follow`, `offline_chop_tree`, `offline_task_status`, `offline_stop_follow`, `offline_replace_follow_with_chop`, `offline_body_unavailable`, `offline_permission_denied`, `offline_read_only_command`, and `offline_knowledge_query` scenarios use the real `mina_agent.app` sidecar with `MINA_API_KEY` forced empty, then verify the no-key fallback can still start, continue, report status, stop, replace, or reject body tasks, execute a constrained read-only command, and call a test SearXNG-compatible search server. The `chop_tree` scenario requires `/mina-test ready` before the request and passes only after the target log is observed as air. The `follow_player` scenario starts the follow skill, moves the requester, and passes only after Mina's body returns within the allowed follow distance. The `read_only_command` scenario verifies that a model-side command request is constrained to `run_read_only_command` and that Fabric returns the command output. The `banned_command` scenario verifies Fabric-side defense in depth by sending a write command through the read-only action path and asserting the target block is unchanged; `model_banned_command` verifies the sidecar rejects the same write command before scheduling any Fabric action. The `knowledge_query` scenario verifies the `/mina` knowledge-answer path with a deterministic scripted search-style response; real-sidecar knowledge scenarios also assert that the sidecar records a successful `web_search` tool call. The `task_status` scenario verifies current-task status queries without requiring the model to know a task id. The `stop_follow` and `replace_follow_with_chop` scenarios verify task cancellation, body stop, and late monitor-result handling. The `body_unavailable` scenario runs with Mina body actions disabled and verifies that Fabric action failure flows back through the skill runtime instead of hanging. The task summary is written to `build/e2e/trace-summary.json`; tool calls plus task/action/result events, including non-task read-only commands, are written to `build/e2e/trace.jsonl`. Trace outputs store large snapshots as `snapshot_hash` plus a small `snapshot_summary`, not raw world snapshots.

## Iteration Workflow

The working target is a usable Minecraft agent that can answer knowledge questions through sidecar tools, run tightly constrained read-only Minecraft commands, and control the PuppetPlayers body for simple verified tasks such as following a player and chopping a tree.

For every behavior change:

1. Keep model-facing tools high-level and safe. Minecraft mutations must go through Fabric actions and monitors; do not expose raw movement, attack, write-command, or unrestricted MCP tools to the model.
2. Add or update a deterministic scripted test before relying on live model behavior. Prefer extending `agent_service/dev/game_e2e.py` and `/mina-test` so failures reproduce without a GUI client or API key.
3. Run the baseline checks:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test pytest -q
GRADLE_USER_HOME=$PWD/.gradle ./gradlew build --no-daemon
```

4. Run the relevant headless E2E scenarios. At minimum, keep `chop_tree` passing before committing body-control changes:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario chop_tree --sidecar scripted
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario follow_player --sidecar scripted
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario read_only_command --sidecar scripted
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario knowledge_query --sidecar scripted
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario banned_command --sidecar scripted
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_banned_command --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario task_status --sidecar scripted
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario stop_follow --sidecar scripted
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario replace_follow_with_chop --sidecar scripted
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario body_unavailable --sidecar scripted
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_chop_tree --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_replace_follow_with_chop --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_action_barrier --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_read_only_command --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_knowledge_query --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_task_status --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_stop_follow --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_permission_denied --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario model_body_unavailable --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario offline_body_unavailable --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario offline_knowledge_query --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario offline_read_only_command --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario offline_chop_tree --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario offline_follow --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario offline_task_status --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario offline_stop_follow --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario offline_replace_follow_with_chop --sidecar service
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.dev.game_e2e --scenario offline_permission_denied --sidecar service
```

5. Inspect `build/e2e/trace-summary.json` and `build/e2e/trace.jsonl` when an E2E scenario fails. The real sidecar also exposes `/v1/tool-calls`, `/v1/action-events`, `/v1/tasks`, and `/v1/tasks/{task_id}/events` for focused debugging. Fix the policy, monitor, or skill runtime first; do not compensate by letting the model directly call lower-level body primitives.
6. Commit after a coherent, tested increment. Push only when a git remote is configured and all relevant scripted E2E scenarios pass. Live DeepSeek E2E is optional and should be gated by `MINA_API_KEY`/explicit opt-in so default CI remains deterministic.

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
