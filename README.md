# mina

Minecraft 1.21.11 Fabric mod plus Python sidecar agent service for the in-game agent `mina`.

Use `/mina <content>` in game. Mina sends player/world context to the sidecar, calls DeepSeek `deepseek-v4-flash`, can search through local SearXNG, stores local SQLite memory, and can execute tightly constrained read-only Minecraft commands.

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

The E2E runner loads `agent_service/.env`, requires a real DeepSeek `MINA_API_KEY`, refuses loopback/mock DeepSeek endpoints, validates selected manifests before server startup, starts the real sidecar, a deterministic SearXNG-compatible search fixture, and a headless Fabric server. It drives declarative `/mina-test` scenarios for local player/world observation, read-only command routing, search-result filtering, companion alerts, smalltalk through the live model, and write-command refusal. Artifacts are written under `build/e2e/runs/`.

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

See `AGENTS.md` for architecture, commands, and verification details.
