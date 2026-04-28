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

The E2E runner loads `agent_service/.env`, requires a real DeepSeek `MINA_API_KEY`, refuses loopback/mock DeepSeek endpoints, fails fast on duplicate selected `request_id` values, starts the real sidecar, a deterministic SearXNG-compatible search fixture, and a headless Fabric/PuppetPlayers server, drives declarative `/mina-test` scenarios for body control, low-health/low-hunger/nearby-hostile companion ticks, healthy-player silence, smalltalk without tool use, and model-facing tools, and writes trace artifacts plus model token totals under `build/e2e/runs/`. Use `--list-scenarios` to print selected scenario metadata and tag counts without a live API key or server startup. `run_manifest.json` records the selected scenarios, tag counts, and runner options; root `summary.json` records the git branch, commit, dirty state, tag counts, and per-scenario duration. Root `trace.jsonl` aggregates the whole run; root `scenario_summaries.jsonl` preserves one compact summary per selected scenario; per-scenario `manifest.json` preserves the executed rubric and invariants, per-scenario `summary.json` records status, duration, event/tool/action counts, exposed/requested model tool names, model token totals, and final snapshot summary, `final_snapshot.json` stores a compact final world snapshot, while per-scenario `trace.jsonl` includes sidecar model/tool/action records and structured harness events for scenario pass/fail/retry, server stdin commands, matched stdout, and poll attempts. Response-content invariants check both model traces and player-visible server output; model-facing scenarios also assert that private low-level body/Fabric tools are not exposed in model-call tool lists. Failed scenarios keep best-effort per-scenario trace artifacts; `failure.json` includes a compact `/mina-test snapshot` hash/summary when the server is still running. Pass `--manifest path/to/scenarios.json` to load additional scenario manifests, or `--searxng-url` to point the run at an external SearXNG instance. The sidecar exposes `/v1/model-calls`, `/v1/tool-calls`, `/v1/action-events`, `/v1/tasks`, and `/v1/traces/{request_id}` for debugging failed runs.

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
