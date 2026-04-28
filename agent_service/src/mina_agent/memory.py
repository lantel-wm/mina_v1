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
                create table if not exists task_events (
                    id integer primary key autoincrement,
                    task_id text not null,
                    event_type text not null,
                    payload_json text not null,
                    created_at real not null
                );
                create table if not exists action_events (
                    id integer primary key autoincrement,
                    request_id text not null,
                    action_id text not null,
                    task_id text not null,
                    step_id text not null,
                    action_name text not null,
                    event_type text not null,
                    payload_json text not null,
                    created_at real not null
                );
                create table if not exists skill_reflections (
                    id integer primary key autoincrement,
                    skill_name text not null,
                    reflection text not null,
                    payload_json text not null,
                    created_at real not null
                );
                create virtual table if not exists memory_fts using fts5(
                    kind,
                    scope_id,
                    label,
                    content,
                    content='',
                    tokenize='unicode61'
                );
                create virtual table if not exists memory_fts_v2 using fts5(
                    kind,
                    scope_id,
                    label,
                    content,
                    tokenize='unicode61'
                );
                """
            )
            if conn.execute("select count(*) from memory_fts_v2").fetchone()[0] == 0:
                self._backfill_fts_v2(conn)

    def _backfill_fts_v2(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            insert into memory_fts_v2(kind, scope_id, label, content)
            select 'conversation', player_id, role, content
            from conversations;

            insert into memory_fts_v2(kind, scope_id, label, content)
            select 'event', player_id, event_type, payload_json
            from events;

            insert into memory_fts_v2(kind, scope_id, label, content)
            select 'task_event', task_id, event_type, payload_json
            from task_events;

            insert into memory_fts_v2(kind, scope_id, label, content)
            select 'action_event', request_id, event_type, payload_json
            from action_events;

            insert into memory_fts_v2(kind, scope_id, label, content)
            select 'skill_reflection', skill_name, skill_name, reflection
            from skill_reflections;
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
            conn.execute(
                "insert into memory_fts_v2(kind, scope_id, label, content) values(?, ?, ?, ?)",
                ("conversation", player_id, role, content),
            )

    def add_event(self, player_id: str, event_type: str, payload: dict[str, Any], importance: int = 1) -> None:
        with self._connect() as conn:
            conn.execute(
                "insert into events(player_id, event_type, payload_json, importance, created_at) values(?, ?, ?, ?, ?)",
                (player_id, event_type, json.dumps(payload, ensure_ascii=False), importance, time.time()),
            )
            conn.execute(
                "insert into memory_fts_v2(kind, scope_id, label, content) values(?, ?, ?, ?)",
                ("event", player_id, event_type, json.dumps(payload, ensure_ascii=False)),
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

    def record_task_event(self, task_id: str, event_type: str, payload: dict[str, Any]) -> None:
        content = json.dumps(payload, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                "insert into task_events(task_id, event_type, payload_json, created_at) values(?, ?, ?, ?)",
                (task_id, event_type, content, time.time()),
            )
            conn.execute(
                "insert into memory_fts_v2(kind, scope_id, label, content) values(?, ?, ?, ?)",
                ("task_event", task_id, event_type, content),
            )

    def record_action_event(self, request_id: str, event_type: str, payload: dict[str, Any]) -> None:
        content = json.dumps(payload, ensure_ascii=False)
        action_id = str(payload.get("action_id") or payload.get("id") or "")
        task_id = str(payload.get("task_id") or "")
        step_id = str(payload.get("step_id") or "")
        action_name = str(payload.get("name") or payload.get("action_name") or "")
        with self._connect() as conn:
            conn.execute(
                """
                insert into action_events(request_id, action_id, task_id, step_id, action_name, event_type, payload_json, created_at)
                values(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (request_id, action_id, task_id, step_id, action_name, event_type, content, time.time()),
            )
            conn.execute(
                "insert into memory_fts_v2(kind, scope_id, label, content) values(?, ?, ?, ?)",
                ("action_event", request_id, event_type, content),
            )

    def add_skill_reflection(self, skill_name: str, reflection: str, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "insert into skill_reflections(skill_name, reflection, payload_json, created_at) values(?, ?, ?, ?)",
                (skill_name, reflection, json.dumps(payload, ensure_ascii=False), time.time()),
            )
            conn.execute(
                "insert into memory_fts_v2(kind, scope_id, label, content) values(?, ?, ?, ?)",
                ("skill_reflection", skill_name, skill_name, reflection),
            )

    def recent_task_events(self, task_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select task_id, event_type, payload_json, created_at
                from task_events
                where task_id = ?
                order by id desc
                limit ?
                """,
                (task_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def recent_action_events(self, request_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if request_id:
                rows = conn.execute(
                    """
                    select request_id, action_id, task_id, step_id, action_name, event_type, payload_json, created_at
                    from action_events
                    where request_id = ?
                    order by id desc
                    limit ?
                    """,
                    (request_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    select request_id, action_id, task_id, step_id, action_name, event_type, payload_json, created_at
                    from action_events
                    order by id desc
                    limit ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def recent_skill_reflections(self, skill_name: str, limit: int = 6) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select skill_name, reflection, payload_json, created_at
                from skill_reflections
                where skill_name = ?
                order by id desc
                limit ?
                """,
                (skill_name, limit),
            ).fetchall()
        return [dict(row) for row in rows]

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
            try:
                fts_rows = conn.execute(
                    """
                    select kind, label, content, bm25(memory_fts_v2) as score
                    from memory_fts_v2
                    where memory_fts_v2 match ?
                      and (
                        (kind in ('conversation', 'event') and scope_id = ?)
                        or kind = 'skill_reflection'
                      )
                    order by score
                    limit ?
                    """,
                    (_fts_query(query), player_id, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                fts_rows = []
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
        merged = [dict(row) for row in fts_rows + conversations + events]
        return merged[:limit]


def _fts_query(query: str) -> str:
    terms = [term.replace('"', "").strip() for term in query.split() if term.strip()]
    if not terms:
        return '""'
    return " OR ".join(f'"{term}"' for term in terms[:8])
