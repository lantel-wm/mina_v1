from __future__ import annotations

import hashlib
import json
import re
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def health(self) -> dict[str, Any]:
        try:
            with self._connect() as conn:
                conn.execute("select 1").fetchone()
                tables = {
                    str(row[0])
                    for row in conn.execute(
                        "select name from sqlite_master where type = 'table' and name in "
                        "('players', 'conversations', 'tool_calls', 'model_calls', 'action_events')"
                    )
                }
            missing = sorted({"players", "conversations", "tool_calls", "model_calls", "action_events"} - tables)
            if missing:
                return {"ok": False, "path": str(self.path), "error": "missing tables: " + ", ".join(missing)}
            return {"ok": True, "path": str(self.path)}
        except sqlite3.Error as exc:
            return {"ok": False, "path": str(self.path), "error": str(exc)}

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
                    messages_summary_json text not null default '[]',
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
            _ensure_column(conn, "model_calls", "messages_summary_json", "text not null default '[]'")
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
    ) -> dict[str, Any]:
        normalized_scope = _normalize_scope(scope)
        normalized_scope_id = str(scope_id or "*")
        normalized_label = _normalize_label(label)
        normalized_content = " ".join(str(content or "").split())
        normalized_importance = max(1, min(5, int(importance)))
        now = time.time()
        with self._connect() as conn:
            exact_matches = conn.execute(
                """
                select id, importance
                from agent_memories
                where scope = ? and scope_id = ? and label = ? and content = ?
                order by updated_at desc, id desc
                """,
                (normalized_scope, normalized_scope_id, normalized_label, normalized_content),
            ).fetchall()
            if exact_matches:
                existing = exact_matches[0]
                conn.execute(
                    """
                    update agent_memories
                    set importance = ?, source = ?, updated_at = ?
                    where id = ?
                    """,
                    (
                        max(int(existing["importance"]), normalized_importance),
                        str(source or "tool"),
                        now,
                        int(existing["id"]),
                    ),
                )
                if len(exact_matches) > 1:
                    conn.executemany(
                        "delete from agent_memories where id = ?",
                        [(int(row["id"]),) for row in exact_matches[1:]],
                    )
                _replace_agent_memory_fts(
                    conn,
                    normalized_scope,
                    normalized_scope_id,
                    normalized_label,
                    [normalized_content],
                    normalized_content,
                )
                return {
                    "operation": "deduplicated",
                    "updated_existing": True,
                    "duplicate_count_removed": max(0, len(exact_matches) - 1),
                }
            if _is_replaceable_agent_memory_label(normalized_label):
                same_label_matches = conn.execute(
                    """
                    select id, content, importance
                    from agent_memories
                    where scope = ? and scope_id = ? and label = ?
                    order by updated_at desc, id desc
                    """,
                    (normalized_scope, normalized_scope_id, normalized_label),
                ).fetchall()
                if same_label_matches:
                    existing = same_label_matches[0]
                    old_contents = [str(row["content"] or "") for row in same_label_matches]
                    conn.execute(
                        """
                        update agent_memories
                        set content = ?, importance = ?, source = ?, updated_at = ?
                        where id = ?
                        """,
                        (
                            normalized_content,
                            max(int(existing["importance"]), normalized_importance),
                            str(source or "tool"),
                            now,
                            int(existing["id"]),
                        ),
                    )
                    if len(same_label_matches) > 1:
                        conn.executemany(
                            "delete from agent_memories where id = ?",
                            [(int(row["id"]),) for row in same_label_matches[1:]],
                        )
                    _replace_agent_memory_fts(
                        conn,
                        normalized_scope,
                        normalized_scope_id,
                        normalized_label,
                        old_contents,
                        normalized_content,
                    )
                    return {
                        "operation": "replaced",
                        "updated_existing": True,
                        "duplicate_count_removed": max(0, len(same_label_matches) - 1),
                    }
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
            _insert_agent_memory_fts(conn, normalized_scope, normalized_scope_id, normalized_label, normalized_content)
            return {"operation": "inserted", "updated_existing": False, "duplicate_count_removed": 0}

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
        messages: list[dict[str, Any]] | None = None,
        error: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into model_calls(
                    request_id, subturn, model, messages_count, tools_json, status,
                    finish_reason, usage_json, response_json, messages_summary_json, error, created_at
                )
                values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    json.dumps(_summarize_model_messages(messages or []), ensure_ascii=False),
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
                           finish_reason, usage_json, response_json, messages_summary_json, error, created_at
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
                           finish_reason, usage_json, response_json, messages_summary_json, error, created_at
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
                select request_id, role, content, created_at from conversations
                where player_id = ?
                order by id desc
                limit ?
                """,
                (player_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def conversation_history(self, player_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select request_id, role, content, created_at from conversations
                where player_id = ?
                order by id asc
                """,
                (player_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def agent_context(
        self,
        player_id: str,
        *,
        world_id: str | None = None,
        query: str = "",
        limit: int = 10,
        max_chars: int = 1600,
    ) -> list[dict[str, Any]]:
        scope_filters = _agent_context_scope_filters(player_id)
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
            world_rows: list[sqlite3.Row] = []
            if world_id:
                world_rows = conn.execute(
                    """
                    select scope, scope_id, label, content, importance, updated_at
                    from agent_memories
                    where scope = ? and scope_id = ?
                    order by importance desc, updated_at desc, id desc
                    limit ?
                    """,
                    ("world", str(world_id), max(limit * 3, limit)),
                ).fetchall()
            known_players = _known_players(conn)
        memories: list[dict[str, Any]] = []
        used_chars = 0
        seen: set[tuple[str, str, str, str]] = set()
        candidates = [dict(row) for row in rows]
        candidates.extend(
            item
            for item in (dict(row) for row in world_rows)
            if _world_memory_is_relevant(
                item,
                query=query,
                current_player_id=player_id,
                known_players=known_players,
            )
        )
        candidates.sort(
            key=lambda item: (
                -int(item.get("importance") or 0),
                -float(item.get("updated_at") or 0.0),
            )
        )
        for item in candidates:
            if _memory_result_is_cross_player_leak(
                item,
                query=query,
                current_player_id=player_id,
                known_players=known_players,
            ):
                continue
            key = _agent_memory_key(item)
            if key in seen:
                continue
            seen.add(key)
            content = str(item.get("content") or "")
            used_chars += len(content)
            if used_chars > max_chars and memories:
                break
            memories.append(item)
        return memories

    def search(self, player_id: str, query: str, limit: int = 8, *, world_id: str | None = None) -> list[dict[str, Any]]:
        pattern = f"%{query[:80]}%"
        agent_scope_keys = [_agent_scope_key(scope, scope_id) for scope, scope_id in _agent_scope_filters(player_id, world_id)]
        scope_filters = _agent_scope_filters(player_id, world_id)
        with self._connect() as conn:
            try:
                scope_placeholders = ",".join("?" for _ in agent_scope_keys)
                if agent_scope_keys:
                    fts_scope_predicate = f"and scope_id in ({scope_placeholders})"
                    fts_scope_args: tuple[str, ...] = tuple(agent_scope_keys)
                else:
                    fts_scope_predicate = "and 0"
                    fts_scope_args = ()
                fts_rows = conn.execute(
                    f"""
                    select kind, scope_id as fts_scope_id, label, content, bm25(memory_fts_v2) as score
                    from memory_fts_v2
                    where memory_fts_v2 match ?
                      and kind = 'agent_memory'
                      {fts_scope_predicate}
                    order by score
                    limit ?
                    """,
                    (_fts_query(query), *fts_scope_args, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                fts_rows = []
            agent_memories = conn.execute(
                f"""
                select 'agent_memory' as kind, scope, scope_id, label, content, updated_at as created_at
                from agent_memories
                where {_scope_where_clause(scope_filters)}
                  and content like ?
                order by importance desc, updated_at desc, id desc
                limit ?
                """,
                (*_scope_where_args(scope_filters), pattern, limit),
            ).fetchall()
            known_players = _known_players(conn)
        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()
        for row in fts_rows + agent_memories:
            item = dict(row)
            if _memory_result_is_cross_player_leak(
                item,
                query=query,
                current_player_id=player_id,
                known_players=known_players,
            ):
                continue
            key = _agent_memory_key(item)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return merged[:limit]


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {str(row[1]) for row in conn.execute(f"pragma table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"alter table {table} add column {column} {definition}")


def _summarize_model_messages(messages: list[dict[str, Any]], *, max_preview_chars: int = 900) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        content = str(message.get("content") or "")
        item: dict[str, Any] = {
            "index": index,
            "role": role,
            "content_length": len(content),
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
            "content_preview": content[:max_preview_chars],
        }
        if len(content) > max_preview_chars:
            item["content_omitted_chars"] = len(content) - max_preview_chars
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            item["tool_call_names"] = [
                str((call.get("function") or {}).get("name") or "")
                for call in tool_calls
                if isinstance(call, dict)
            ]
        tool_call_id = message.get("tool_call_id")
        if tool_call_id:
            item["tool_call_id"] = str(tool_call_id)
        summary.append(item)
    return summary


def _normalize_scope(scope: str) -> str:
    value = str(scope or "player").strip().lower()
    if value in {"global", "world", "player"}:
        return value
    return "player"


def _normalize_label(label: str) -> str:
    value = str(label or "note").strip().lower()
    canonical = {
        "base location": "base_location",
        "base-location": "base_location",
        "基地位置": "base_location",
        "基地坐标": "base_location",
    }.get(value)
    if canonical:
        value = canonical
    return value[:80] if value else "note"


def _agent_scope_key(scope: str, scope_id: str) -> str:
    return f"{scope}:{scope_id}"


_GENERIC_AGENT_MEMORY_LABELS = {
    "fact",
    "facts",
    "global_fact",
    "lesson",
    "memory",
    "note",
    "notes",
    "plan",
    "player_fact",
    "player_preference",
    "preference",
    "preferences",
    "promise",
    "world_fact",
    "事实",
    "偏好",
    "备忘",
    "备注",
    "承诺",
    "教训",
    "计划",
    "记忆",
}


def _is_replaceable_agent_memory_label(label: str) -> bool:
    token = str(label or "").strip().lower().replace(" ", "_").replace("-", "_")
    return bool(token) and token not in _GENERIC_AGENT_MEMORY_LABELS


def _insert_agent_memory_fts(
    conn: sqlite3.Connection,
    scope: str,
    scope_id: str,
    label: str,
    content: str,
) -> None:
    conn.execute(
        "insert into memory_fts_v2(kind, scope_id, label, content) values(?, ?, ?, ?)",
        ("agent_memory", _agent_scope_key(scope, scope_id), label, content),
    )


def _replace_agent_memory_fts(
    conn: sqlite3.Connection,
    scope: str,
    scope_id: str,
    label: str,
    old_contents: list[str],
    new_content: str,
) -> None:
    scope_key = _agent_scope_key(scope, scope_id)
    for old_content in set([*old_contents, new_content]):
        conn.execute(
            """
            delete from memory_fts_v2
            where kind = ? and scope_id = ? and label = ? and content = ?
            """,
            ("agent_memory", scope_key, label, old_content),
        )
    _insert_agent_memory_fts(conn, scope, scope_id, label, new_content)


def _agent_memory_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    label = str(item.get("label") or "")
    if _is_replaceable_agent_memory_label(label):
        return (
            str(item.get("scope") or ""),
            str(item.get("scope_id") or ""),
            label,
            "",
        )
    return (
        str(item.get("scope") or ""),
        str(item.get("scope_id") or ""),
        label,
        str(item.get("content") or ""),
    )


def _agent_scope_filters(player_id: str, world_id: str | None = None) -> list[tuple[str, str]]:
    filters = [("global", "*")]
    if world_id:
        filters.append(("world", str(world_id)))
    filters.append(("player", str(player_id or "unknown")))
    return filters


def _agent_context_scope_filters(player_id: str) -> list[tuple[str, str]]:
    return [("global", "*"), ("player", str(player_id or "unknown"))]


def _scope_where_clause(filters: list[tuple[str, str]]) -> str:
    if not filters:
        return "0"
    return "(" + " or ".join("(scope = ? and scope_id = ?)" for _ in filters) + ")"


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


def _world_memory_is_relevant(
    item: dict[str, Any],
    *,
    query: str,
    current_player_id: str,
    known_players: list[dict[str, str]],
) -> bool:
    if _memory_result_is_cross_player_leak(
        item,
        query=query,
        current_player_id=current_player_id,
        known_players=known_players,
    ):
        return False
    if _query_mentions_player_named_in_item(item, query, known_players):
        return True
    return _memory_relevant_to_query(item, query)


def _memory_relevant_to_query(item: dict[str, Any], query: str) -> bool:
    query_tokens = _memory_relevance_tokens(query)
    if not query_tokens:
        return False
    memory_tokens = _memory_relevance_tokens(_memory_item_text(item))
    return bool(query_tokens & memory_tokens)


def _memory_item_text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(key) or "") for key in ("label", "content"))


def _known_players(conn: sqlite3.Connection) -> list[dict[str, str]]:
    rows = conn.execute("select player_id, name from players").fetchall()
    players: list[dict[str, str]] = []
    for row in rows:
        name = str(row["name"] or "").strip()
        if not name or name.lower() in {"mina"}:
            continue
        players.append({"player_id": str(row["player_id"] or ""), "name": name})
    return players


def _memory_result_is_cross_player_leak(
    item: dict[str, Any],
    *,
    query: str,
    current_player_id: str,
    known_players: list[dict[str, str]],
) -> bool:
    scope = _memory_result_scope(item)
    if scope not in {"world", "global"}:
        return False
    text = _memory_item_text(item)
    for player in known_players:
        player_id = str(player.get("player_id") or "")
        name = str(player.get("name") or "")
        if not name or player_id == str(current_player_id or ""):
            continue
        if not _text_mentions_player_name(text, name):
            continue
        if _text_mentions_player_name(query, name):
            return False
        return True
    return False


def _query_mentions_player_named_in_item(
    item: dict[str, Any],
    query: str,
    known_players: list[dict[str, str]],
) -> bool:
    text = _memory_item_text(item)
    for player in known_players:
        name = str(player.get("name") or "")
        if name and _text_mentions_player_name(text, name) and _text_mentions_player_name(query, name):
            return True
    return False


def _memory_result_scope(item: dict[str, Any]) -> str:
    scope = str(item.get("scope") or "")
    if scope:
        return scope
    fts_scope_id = str(item.get("fts_scope_id") or "")
    if ":" in fts_scope_id:
        return fts_scope_id.split(":", 1)[0]
    return ""


def _text_mentions_player_name(text: str, player_name: str) -> bool:
    value = str(text or "")
    name = str(player_name or "").strip()
    if not value or not name:
        return False
    if name.lower() in value.lower():
        return True
    compact_value = _compact_identity_text(value)
    compact_name = _compact_identity_text(name)
    return bool(compact_name and compact_name in compact_value)


_LATIN_MEMORY_TOKEN = re.compile(r"[a-z0-9_]{3,}", re.IGNORECASE)
_CJK_MEMORY_SEQUENCE = re.compile(r"[\u3400-\u9fff]{2,}")
_MEMORY_RELEVANCE_STOP_TOKENS = {
    "什么",
    "哪里",
    "哪儿",
    "怎么",
    "现在",
    "之前",
    "讨论",
    "我们",
    "你们",
    "他们",
    "这个",
    "那个",
    "世界",
    "记得",
    "记住",
    "多少",
    "附近",
}
_MEMORY_RELEVANCE_STOP_CHARS = set("的我你他她它这那哪什么吗呢啊吧")


def _memory_relevance_tokens(text: str) -> set[str]:
    value = str(text or "").lower()
    tokens = {match.group(0) for match in _LATIN_MEMORY_TOKEN.finditer(value)}
    for match in _CJK_MEMORY_SEQUENCE.finditer(value):
        sequence = match.group(0)
        for size in (2, 3):
            for index in range(0, max(0, len(sequence) - size + 1)):
                token = sequence[index:index + size]
                if token in _MEMORY_RELEVANCE_STOP_TOKENS:
                    continue
                if size == 2 and any(char in _MEMORY_RELEVANCE_STOP_CHARS for char in token):
                    continue
                tokens.add(token)
    return tokens


def _compact_identity_text(text: str) -> str:
    return "".join(re.findall(r"[a-z0-9\u3400-\u9fff]+", str(text or "").lower()))
