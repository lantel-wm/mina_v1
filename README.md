# mina

Minecraft 1.21.11 Fabric mod plus Python sidecar agent service for the in-game agent `mina`.

Use `/mina <content>` in game. Mina sends player/world context to the sidecar, calls DeepSeek `deepseek-v4-flash`, can search through local SearXNG, stores local SQLite memory, and can execute approved Minecraft actions through PuppetPlayers.

## Build

```sh
GRADLE_USER_HOME=$PWD/.gradle ./gradlew build --no-daemon
```

## Test

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test pytest -q
GRADLE_USER_HOME=$PWD/.gradle ./gradlew build --no-daemon
```

Live agent E2E gate:

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service --extra test python -m mina_agent.e2e --suite live --require-live-model
```

The E2E runner loads `agent_service/.env`, requires a real DeepSeek `MINA_API_KEY`, refuses loopback/mock DeepSeek endpoints, starts the real sidecar, a deterministic SearXNG-compatible search fixture, and a headless Fabric/PuppetPlayers server, drives declarative `/mina-test` scenarios, and writes trace artifacts plus model token totals under `build/e2e/runs/`. Per-scenario `trace.jsonl` includes sidecar model/tool/action records and structured harness events for server stdin commands, matched stdout, and poll attempts. Pass `--manifest path/to/scenarios.json` to load additional scenario manifests, or `--searxng-url` to point the run at an external SearXNG instance. The sidecar exposes `/v1/model-calls`, `/v1/tool-calls`, `/v1/action-events`, `/v1/tasks`, and `/v1/traces/{request_id}` for debugging failed runs.

## Run Sidecar

```sh
UV_CACHE_DIR=$PWD/.uv-cache uv run --project agent_service python -m mina_agent
```

Configure `agent_service/.env` from `agent_service/.env.example`; set `MINA_API_KEY` for DeepSeek.

## Run Server

```sh
GRADLE_USER_HOME=$PWD/.gradle ./gradlew runServer --no-daemon
```

## Run Client

```sh
./gradlew runClient
```

See `AGENTS.md` for deployment notes, PuppetPlayers dependencies, commands, and verification details.
