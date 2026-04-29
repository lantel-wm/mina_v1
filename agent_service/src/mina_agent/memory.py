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
                create table if not exists agent_memories (
                    id integer primary key autoincrement,
                    scope text not null,
                    scope_id text not null,
                    label text not null,
                    content text not null,
                    importance integer not null default 1,
                    source text not null default 'tool',
                    created_at real not null,
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
                create table if not exists model_calls (
                    id integer primary key autoincrement,
                    request_id text not null,
                    subturn integer not null,
                    model text not null,
                    messages_count integer not null,
                    tools_json text not null,
                    status text not null,
                    finish_reason text not null,
                    usage_json text not null,
                    response_json text not null,
                    error text not null,
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
            select 'action_event', request_id, event_type, payload_json
            from action_events;

            insert into memory_fts_v2(kind, scope_id, label, content)
            select 'agent_memory', scope || ':' || scope_id, label, content
            from agent_memories;
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

    def add_agent_memory(
        self,
        scope: str,
        scope_id: str,
        label: str,
        content: str,
        *,
        importance: int = 1,
        source: str = "tool",
    ) -> None:
        normalized_scope = _normalize_scope(scope)
        normalized_scope_id = str(scope_id or "*")
        normalized_label = _normalize_label(label)
        normalized_content = " ".join(str(content or "").split())
        normalized_importance = max(1, min(5, int(importance)))
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                insert into agent_memories(scope, scope_id, label, content, importance, source, created_at, updated_at)
                values(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_scope,
                    normalized_scope_id,
                    normalized_label,
                    normalized_content,
                    normalized_importance,
                    str(source or "tool"),
                    now,
                    now,
                ),
            )
            conn.execute(
                "insert into memory_fts_v2(kind, scope_id, label, content) values(?, ?, ?, ?)",
                (
                    "agent_memory",
                    _agent_scope_key(normalized_scope, normalized_scope_id),
                    normalized_label,
                    normalized_content,
                ),
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

    def recent_tool_calls(self, request_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if request_id:
                rows = conn.execute(
                    """
                    select request_id, tool_name, args_json, result_json, status, created_at
                    from tool_calls
                    where request_id = ?
                    order by id desc
                    limit ?
                    """,
                    (request_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    select request_id, tool_name, args_json, result_json, status, created_at
                    from tool_calls
                    order by id desc
                    limit ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def record_model_call(
        self,
        request_id: str,
        subturn: int,
        model: str,
        messages_count: int,
        tools: list[str],
        status: str,
        finish_reason: str = "",
        usage: dict[str, Any] | None = None,
        response: dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into model_calls(
                    request_id, subturn, model, messages_count, tools_json, status,
                    finish_reason, usage_json, response_json, error, created_at
                )
                values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    subturn,
                    model,
                    messages_count,
                    json.dumps(tools, ensure_ascii=False),
                    status,
                    finish_reason,
                    json.dumps(usage or {}, ensure_ascii=False),
                    json.dumps(response or {}, ensure_ascii=False),
                    error,
                    time.time(),
                ),
            )

    def recent_model_calls(self, request_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if request_id:
                rows = conn.execute(
                    """
                    select request_id, subturn, model, messages_count, tools_json, status,
                           finish_reason, usage_json, response_json, error, created_at
                    from model_calls
                    where request_id = ?
                    order by id desc
                    limit ?
                    """,
                    (request_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    select request_id, subturn, model, messages_count, tools_json, status,
                           finish_reason, usage_json, response_json, error, created_at
                    from model_calls
                    order by id desc
                    limit ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in reversed(rows)]

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

    def recent_action_results_for_player(self, player_id: str, limit: int = 6) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select ae.request_id, ae.action_id, ae.action_name, ae.event_type, ae.payload_json, ae.created_at
                from action_events ae
                where ae.event_type = 'action_result'
                  and exists (
                    select 1
                    from conversations c
                    where c.request_id = ae.request_id and c.player_id = ?
                  )
                order by ae.id desc
                limit ?
                """,
                (player_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

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

    def agent_context(
        self,
        player_id: str,
        *,
        world_id: str | None = None,
        limit: int = 10,
        max_chars: int = 1600,
    ) -> list[dict[str, Any]]:
        scope_filters = _agent_scope_filters(player_id, world_id)
        if not scope_filters:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select scope, scope_id, label, content, importance, updated_at
                from agent_memories
                where {_scope_where_clause(scope_filters)}
                order by importance desc, updated_at desc, id desc
                limit ?
                """,
                (*_scope_where_args(scope_filters), limit),
            ).fetchall()
        memories: list[dict[str, Any]] = []
        used_chars = 0
        for row in rows:
            item = dict(row)
            content = str(item.get("content") or "")
            used_chars += len(content)
            if used_chars > max_chars and memories:
                break
            memories.append(item)
        return memories

    def search(self, player_id: str, query: str, limit: int = 8, *, world_id: str | None = None) -> list[dict[str, Any]]:
        pattern = f"%{query[:80]}%"
        agent_scope_keys = [_agent_scope_key(scope, scope_id) for scope, scope_id in _agent_scope_filters(player_id, world_id)]
        with self._connect() as conn:
            try:
                scope_placeholders = ",".join("?" for _ in agent_scope_keys)
                agent_scope_predicate = ""
                agent_scope_args: tuple[str, ...] = ()
                if agent_scope_keys:
                    agent_scope_predicate = f"or (kind = 'agent_memory' and scope_id in ({scope_placeholders}))"
                    agent_scope_args = tuple(agent_scope_keys)
                fts_rows = conn.execute(
                    f"""
                    select kind, label, content, bm25(memory_fts_v2) as score
                    from memory_fts_v2
                    where memory_fts_v2 match ?
                      and (
                        (kind in ('conversation', 'event') and scope_id = ?)
                        {agent_scope_predicate}
                      )
                    order by score
                    limit ?
                    """,
                    (_fts_query(query), player_id, *agent_scope_args, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                fts_rows = []
            agent_memories = conn.execute(
                f"""
                select 'agent_memory' as kind, label, content, updated_at as created_at
                from agent_memories
                where {_scope_where_clause(_agent_scope_filters(player_id, world_id))}
                  and content like ?
                order by importance desc, updated_at desc, id desc
                limit ?
                """,
                (*_scope_where_args(_agent_scope_filters(player_id, world_id)), pattern, limit),
            ).fetchall()
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
            action_events = conn.execute(
                """
                select 'action_event' as kind, ae.event_type as label, ae.payload_json as content, ae.created_at
                from action_events ae
                where ae.payload_json like ?
                  and exists (
                    select 1
                    from conversations c
                    where c.request_id = ae.request_id and c.player_id = ?
                  )
                order by ae.id desc
                limit ?
                """,
                (pattern, player_id, limit),
            ).fetchall()
        merged = [dict(row) for row in fts_rows + agent_memories + conversations + events + action_events]
        return merged[:limit]


def _normalize_scope(scope: str) -> str:
    value = str(scope or "player").strip().lower()
    if value in {"global", "world", "player"}:
        return value
    return "player"


def _normalize_label(label: str) -> str:
    value = str(label or "note").strip().lower()
    return value[:80] if value else "note"


def _agent_scope_key(scope: str, scope_id: str) -> str:
    return f"{scope}:{scope_id}"


def _agent_scope_filters(player_id: str, world_id: str | None = None) -> list[tuple[str, str]]:
    filters = [("global", "*")]
    if world_id:
        filters.append(("world", str(world_id)))
    filters.append(("player", str(player_id or "unknown")))
    return filters


def _scope_where_clause(filters: list[tuple[str, str]]) -> str:
    if not filters:
        return "0"
    return " or ".join("(scope = ? and scope_id = ?)" for _ in filters)


def _scope_where_args(filters: list[tuple[str, str]]) -> tuple[str, ...]:
    args: list[str] = []
    for scope, scope_id in filters:
        args.extend([scope, scope_id])
    return tuple(args)


def _fts_query(query: str) -> str:
    terms = [term.replace('"', "").strip() for term in query.split() if term.strip()]
    if not terms:
        return '""'
    return " OR ".join(f'"{term}"' for term in terms[:8])
