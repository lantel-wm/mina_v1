from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class MemoryStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists players (
                    player_id text primary key,
                    name text not null,
                    first_seen real not null,
                    last_seen real not null,
                    preferences_json text not null default '{}'
                );
                create table if not exists conversations (
                    id integer primary key autoincrement,
                    request_id text not null,
                    player_id text not null,
                    role text not null,
                    content text not null,
                    created_at real not null
                );
                create table if not exists events (
                    id integer primary key autoincrement,
                    player_id text not null,
                    event_type text not null,
                    payload_json text not null,
                    importance integer not null default 1,
                    created_at real not null
                );
                create table if not exists summaries (
                    scope text not null,
                    scope_id text not null,
                    summary text not null,
                    updated_at real not null,
                    primary key (scope, scope_id)
                );
                create table if not exists world_facts (
                    id integer primary key autoincrement,
                    world_id text not null,
                    fact_type text not null,
                    payload_json text not null,
                    confidence real not null default 1.0,
                    updated_at real not null
                );
                create table if not exists tool_calls (
                    id integer primary key autoincrement,
                    request_id text not null,
                    tool_name text not null,
                    args_json text not null,
                    result_json text not null,
                    status text not null,
                    created_at real not null
                );
                """
            )

    def upsert_player(self, player: dict[str, Any]) -> None:
        player_id = str(player.get("uuid") or player.get("id") or "unknown")
        name = str(player.get("name") or player_id)
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                insert into players(player_id, name, first_seen, last_seen)
                values(?, ?, ?, ?)
                on conflict(player_id) do update set name=excluded.name, last_seen=excluded.last_seen
                """,
                (player_id, name, now, now),
            )

    def add_conversation(self, request_id: str, player_id: str, role: str, content: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "insert into conversations(request_id, player_id, role, content, created_at) values(?, ?, ?, ?, ?)",
                (request_id, player_id, role, content, time.time()),
            )

    def add_event(self, player_id: str, event_type: str, payload: dict[str, Any], importance: int = 1) -> None:
        with self._connect() as conn:
            conn.execute(
                "insert into events(player_id, event_type, payload_json, importance, created_at) values(?, ?, ?, ?, ?)",
                (player_id, event_type, json.dumps(payload, ensure_ascii=False), importance, time.time()),
            )

    def record_tool_call(
        self,
        request_id: str,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
        status: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "insert into tool_calls(request_id, tool_name, args_json, result_json, status, created_at) values(?, ?, ?, ?, ?, ?)",
                (
                    request_id,
                    tool_name,
                    json.dumps(args, ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                    status,
                    time.time(),
                ),
            )

    def recent_conversation(self, player_id: str, limit: int = 12) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select role, content, created_at from conversations
                where player_id = ?
                order by id desc
                limit ?
                """,
                (player_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def search(self, player_id: str, query: str, limit: int = 8) -> list[dict[str, Any]]:
        pattern = f"%{query[:80]}%"
        with self._connect() as conn:
            conversations = conn.execute(
                """
                select 'conversation' as kind, role as label, content, created_at
                from conversations
                where player_id = ? and content like ?
                order by id desc
                limit ?
                """,
                (player_id, pattern, limit),
            ).fetchall()
            events = conn.execute(
                """
                select 'event' as kind, event_type as label, payload_json as content, created_at
                from events
                where player_id = ? and payload_json like ?
                order by importance desc, id desc
                limit ?
                """,
                (player_id, pattern, limit),
            ).fetchall()
        return [dict(row) for row in conversations + events][:limit]

