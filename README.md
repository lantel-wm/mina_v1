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
