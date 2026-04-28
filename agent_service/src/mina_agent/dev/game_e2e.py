from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
SERVER_DIR = ROOT / "build" / "e2e" / "server"
PUPPET_VERSION_ID = "VccNE5wh"
KOTLIN_VERSION = "1.13.11+kotlin.2.3.21"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Mina headless game E2E scenarios.")
    parser.add_argument(
        "--scenario",
        default="chop_tree",
        choices=[
            "chop_tree",
            "follow_player",
            "read_only_command",
            "knowledge_query",
            "banned_command",
            "model_banned_command",
            "model_private_body_tool",
            "task_status",
            "stop_follow",
            "replace_follow_with_chop",
            "body_unavailable",
            "model_chop_tree",
            "model_chop_then_status",
            "model_chop_target_disappears",
            "model_unreachable_chop_tree",
            "model_replace_follow_with_chop",
            "model_follow_player",
            "model_spawn_body_follow",
            "model_follow_heartbeat",
            "model_multi_body_action_barrier",
            "model_action_barrier",
            "model_read_only_command",
            "model_knowledge_query",
            "model_memory_roundtrip",
            "model_task_status",
            "model_stop_follow",
            "model_permission_denied",
            "model_body_unavailable",
            "offline_body_unavailable",
            "offline_knowledge_query",
            "offline_read_only_command",
            "offline_chop_tree",
            "offline_follow",
            "offline_task_status",
            "offline_stop_follow",
            "offline_replace_follow_with_chop",
            "offline_permission_denied",
        ],
    )
    parser.add_argument("--sidecar", default="scripted", choices=["scripted", "service"])
    parser.add_argument("--port", type=int, default=18911)
    parser.add_argument("--server-port", type=int, default=25566)
    parser.add_argument("--search-port", type=int, default=18888)
    parser.add_argument("--deepseek-port", type=int, default=18889)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    prepare_runtime(
        args.port,
        args.server_port,
        enable_body=args.scenario not in {"body_unavailable", "offline_body_unavailable", "model_body_unavailable"},
    )
    if not args.skip_build:
        run_checked([str(ROOT / "gradlew"), "build", "--no-daemon"], cwd=ROOT)

    offline_service_scenarios = {
        "offline_follow",
        "offline_read_only_command",
        "offline_knowledge_query",
        "offline_chop_tree",
        "offline_body_unavailable",
        "offline_stop_follow",
        "offline_task_status",
        "offline_replace_follow_with_chop",
        "offline_permission_denied",
    }
    fake_deepseek_scenarios = {
        "model_chop_tree",
        "model_chop_then_status",
        "model_chop_target_disappears",
        "model_unreachable_chop_tree",
        "model_replace_follow_with_chop",
        "model_follow_player",
        "model_spawn_body_follow",
        "model_follow_heartbeat",
        "model_multi_body_action_barrier",
        "model_banned_command",
        "model_private_body_tool",
        "model_action_barrier",
        "model_read_only_command",
        "model_knowledge_query",
        "model_memory_roundtrip",
        "model_task_status",
        "model_stop_follow",
        "model_permission_denied",
        "model_body_unavailable",
    }
    service_scenarios = {*offline_service_scenarios, *fake_deepseek_scenarios}
    fake_search = start_fake_search(args.search_port) if args.scenario in {"offline_knowledge_query", "model_knowledge_query"} else None
    fake_deepseek = start_fake_deepseek(args.deepseek_port) if args.scenario in fake_deepseek_scenarios else None
    sidecar_mode = "service" if args.scenario in service_scenarios else args.sidecar
    reset_sidecar_db(sidecar_mode)
    sidecar = start_sidecar(
        args.port,
        sidecar_mode,
        force_offline=args.scenario in offline_service_scenarios,
        searxng_url=f"http://127.0.0.1:{args.search_port}" if fake_search is not None else None,
        deepseek_url=f"http://127.0.0.1:{args.deepseek_port}" if fake_deepseek is not None else None,
    )
    server = None
    try:
        if fake_search is not None:
            wait_http(f"http://127.0.0.1:{args.search_port}/healthz", timeout=20, proc=fake_search)
        if fake_deepseek is not None:
            wait_http(f"http://127.0.0.1:{args.deepseek_port}/healthz", timeout=20, proc=fake_deepseek)
        wait_http(f"http://127.0.0.1:{args.port}/healthz", timeout=20, proc=sidecar)
        server = start_server()
        output = OutputReader(server)
        output.start()
        output.wait_for("Done", timeout=args.timeout)
        setup_scenario = (
            "chop_tree"
            if args.scenario
            in {
                "replace_follow_with_chop",
                "banned_command",
                "model_banned_command",
                "model_chop_tree",
                "model_chop_then_status",
                "model_chop_target_disappears",
                "model_replace_follow_with_chop",
                "offline_chop_tree",
                "offline_replace_follow_with_chop",
            }
            else "follow_player"
            if args.scenario in {
                "read_only_command",
                "knowledge_query",
                "task_status",
                "stop_follow",
                "body_unavailable",
                "model_follow_player",
                "model_spawn_body_follow",
                "model_follow_heartbeat",
                "model_multi_body_action_barrier",
                "model_action_barrier",
                "model_read_only_command",
                "model_knowledge_query",
                "model_memory_roundtrip",
                "model_task_status",
                "model_stop_follow",
                "model_permission_denied",
                "model_body_unavailable",
                "model_private_body_tool",
                "offline_body_unavailable",
                "offline_follow",
                "offline_task_status",
                "offline_stop_follow",
                "offline_read_only_command",
                "offline_knowledge_query",
                "offline_permission_denied",
            }
            else "blocked_chop_tree"
            if args.scenario == "model_unreachable_chop_tree"
            else args.scenario
        )
        send(server, f"mina-test setup {setup_scenario}")
        output.wait_for(f"Mina test {setup_scenario} setup complete", timeout=30)
        poll_command(
            server,
            output,
            "mina-test ready",
            success="Mina test ready",
            pending=["Mina test not ready"],
            timeout=60,
        )
        if args.scenario == "chop_tree":
            run_chop_tree(server, output, args.timeout)
        elif args.scenario == "follow_player":
            run_follow_player(server, output, args.timeout)
        elif args.scenario == "read_only_command":
            run_read_only_command(server, output)
        elif args.scenario == "knowledge_query":
            run_knowledge_query(server, output)
        elif args.scenario == "banned_command":
            run_banned_command(server, output)
        elif args.scenario == "model_banned_command":
            run_model_banned_command(server, output, args.port, args.deepseek_port)
        elif args.scenario == "model_private_body_tool":
            run_model_private_body_tool(server, output, args.port, args.deepseek_port)
        elif args.scenario == "task_status":
            run_task_status(server, output)
        elif args.scenario == "stop_follow":
            run_stop_follow(server, output, args.timeout)
        elif args.scenario == "replace_follow_with_chop":
            run_replace_follow_with_chop(server, output, args.timeout)
        elif args.scenario == "body_unavailable":
            run_body_unavailable(server, output)
        elif args.scenario == "model_chop_tree":
            run_model_chop_tree(server, output, args.timeout, args.port, args.deepseek_port)
        elif args.scenario == "model_chop_then_status":
            run_model_chop_then_status(server, output, args.timeout, args.port, args.deepseek_port)
        elif args.scenario == "model_chop_target_disappears":
            run_model_chop_target_disappears(server, output, args.timeout, args.port, args.deepseek_port)
        elif args.scenario == "model_unreachable_chop_tree":
            run_model_unreachable_chop_tree(server, output, args.port, args.deepseek_port)
        elif args.scenario == "model_replace_follow_with_chop":
            run_model_replace_follow_with_chop(server, output, args.timeout, args.port, args.deepseek_port)
        elif args.scenario == "model_follow_player":
            run_model_follow_player(server, output, args.timeout, args.port, args.deepseek_port)
        elif args.scenario == "model_spawn_body_follow":
            run_model_spawn_body_follow(server, output, args.timeout, args.port, args.deepseek_port)
        elif args.scenario == "model_follow_heartbeat":
            run_model_follow_heartbeat(server, output, args.timeout, args.port, args.deepseek_port)
        elif args.scenario == "model_multi_body_action_barrier":
            run_model_multi_body_action_barrier(server, output, args.port, args.deepseek_port)
        elif args.scenario == "model_action_barrier":
            run_model_action_barrier(server, output, args.timeout, args.port, args.deepseek_port)
        elif args.scenario == "model_read_only_command":
            run_model_read_only_command(server, output, args.port, args.deepseek_port)
        elif args.scenario == "model_knowledge_query":
            run_model_knowledge_query(server, output, args.port, args.deepseek_port)
        elif args.scenario == "model_memory_roundtrip":
            run_model_memory_roundtrip(server, output, args.port, args.deepseek_port)
        elif args.scenario == "model_task_status":
            run_model_task_status(server, output, args.timeout, args.port, args.deepseek_port)
        elif args.scenario == "model_stop_follow":
            run_model_stop_follow(server, output, args.timeout, args.port, args.deepseek_port)
        elif args.scenario == "model_permission_denied":
            run_model_permission_denied(server, output, args.port, args.deepseek_port)
        elif args.scenario == "model_body_unavailable":
            run_model_body_unavailable(server, output, args.port, args.deepseek_port)
        elif args.scenario == "offline_body_unavailable":
            run_body_unavailable(server, output)
        elif args.scenario == "offline_knowledge_query":
            run_knowledge_query(server, output, args.port)
        elif args.scenario == "offline_read_only_command":
            run_read_only_command(server, output, args.port)
        elif args.scenario == "offline_chop_tree":
            run_chop_tree(server, output, args.timeout, args.port)
        elif args.scenario == "offline_follow":
            run_follow_player(server, output, args.timeout, args.port)
        elif args.scenario == "offline_task_status":
            run_task_status(server, output, args.port)
        elif args.scenario == "offline_stop_follow":
            run_stop_follow(server, output, args.timeout, args.port)
        elif args.scenario == "offline_replace_follow_with_chop":
            run_replace_follow_with_chop(server, output, args.timeout)
        elif args.scenario == "offline_permission_denied":
            run_permission_denied(server, output, args.port)
        write_trace_summary(args.port)
        return 0
    finally:
        if server is not None:
            stop_process(server, command="stop")
        stop_process(sidecar)
        if fake_search is not None:
            stop_process(fake_search)
        if fake_deepseek is not None:
            stop_process(fake_deepseek)


def prepare_runtime(port: int, server_port: int, enable_body: bool = True) -> None:
    world_dir = SERVER_DIR / "world"
    if world_dir.exists():
        shutil.rmtree(world_dir)
    (SERVER_DIR / "mods").mkdir(parents=True, exist_ok=True)
    (SERVER_DIR / "config").mkdir(parents=True, exist_ok=True)
    (SERVER_DIR / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    (SERVER_DIR / "server.properties").write_text(
        "\n".join(
            [
                "online-mode=false",
                f"server-port={server_port}",
                "enable-command-block=true",
                "gamemode=survival",
                "difficulty=peaceful",
                "spawn-protection=0",
                "level-name=world",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (SERVER_DIR / "config" / "mina.json").write_text(
        json.dumps(
            {
                "sidecarBaseUrl": f"http://127.0.0.1:{port}",
                "sidecarTimeoutMs": 60000,
                "enabled": True,
                "enableCompanion": False,
                "allowedOperatorsOnlyForActions": True,
                "actionAllowlist": ["mina_tester"],
                "bodyUsername": "mina",
                "enableBody": enable_body,
                "snapshotIntervalTicks": 40,
                "companionCooldownSeconds": 300,
                "nearbyEntityRadius": 32,
                "maxInventorySlotsReported": 46,
                "maxNearbyEntitiesReported": 40,
                "dangerousCommandDenylist": ["op", "deop", "stop", "ban", "ban-ip", "pardon", "pardon-ip", "whitelist", "save-all", "save-off", "save-on"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (SERVER_DIR / "config" / "puppet-player-config.json").write_text(
        json.dumps({"reload_puppet_players": True, "operator_required_for_puppets": True}, indent=2),
        encoding="utf-8",
    )
    download_puppet_players(SERVER_DIR / "mods")
    download_kotlin(SERVER_DIR / "mods")


def download_puppet_players(mods_dir: Path) -> None:
    existing = list(mods_dir.glob("PuppetPlayers-1.3.1+1.21.11.jar"))
    if existing:
        return
    with urllib.request.urlopen(f"https://api.modrinth.com/v2/version/{PUPPET_VERSION_ID}", timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    files = payload.get("files") or []
    primary = next((item for item in files if item.get("primary")), files[0])
    url = primary["url"]
    target = mods_dir / primary["filename"]
    download(url, target)


def download_kotlin(mods_dir: Path) -> None:
    filename = f"fabric-language-kotlin-{KOTLIN_VERSION}.jar"
    target = mods_dir / filename
    if target.exists():
        return
    local = ROOT / "run" / "mods" / filename
    if local.exists():
        shutil.copy2(local, target)
        return
    encoded_version = KOTLIN_VERSION.replace("+", "%2B")
    url = (
        "https://maven.fabricmc.net/net/fabricmc/fabric-language-kotlin/"
        f"{encoded_version}/fabric-language-kotlin-{encoded_version}.jar"
    )
    download(url, target)


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with urllib.request.urlopen(url, timeout=60) as response:
        tmp.write_bytes(response.read())
    tmp.replace(target)


def start_sidecar(
    port: int,
    mode: str,
    force_offline: bool = False,
    searxng_url: str | None = None,
    deepseek_url: str | None = None,
) -> subprocess.Popen[str]:
    pythonpath = str(ROOT / "agent_service" / "src")
    env = {
        **os.environ,
        "MINA_DB_PATH": str(ROOT / "build" / "e2e" / f"mina-{mode}.sqlite3"),
        "MINA_LOG_PATH": str(ROOT / "build" / "e2e" / f"mina-{mode}.log"),
        "PYTHONPATH": pythonpath + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    if force_offline:
        env["MINA_API_KEY"] = ""
    if searxng_url:
        env["MINA_SEARXNG_URL"] = searxng_url
    if deepseek_url:
        env["MINA_BASE_URL"] = deepseek_url
        env["MINA_API_KEY"] = "fake-deepseek-key"
        env["MINA_MODEL"] = "mina-fake-deepseek"
        env["MINA_THINKING"] = "disabled"
    module = "mina_agent.dev.scripted_sidecar:app" if mode == "scripted" else "mina_agent.app:app"
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", module, "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def reset_sidecar_db(mode: str) -> None:
    base = ROOT / "build" / "e2e" / f"mina-{mode}.sqlite3"
    for path in (base, base.with_name(base.name + "-wal"), base.with_name(base.name + "-shm")):
        path.unlink(missing_ok=True)


def start_fake_deepseek(port: int) -> subprocess.Popen[str]:
    pythonpath = str(ROOT / "agent_service" / "src")
    env = {
        **os.environ,
        "PYTHONPATH": pythonpath + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "mina_agent.dev.fake_deepseek:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def start_fake_search(port: int) -> subprocess.Popen[str]:
    pythonpath = str(ROOT / "agent_service" / "src")
    env = {
        **os.environ,
        "PYTHONPATH": pythonpath + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "mina_agent.dev.fake_searxng:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def start_server() -> subprocess.Popen[str]:
    env = {**os.environ, "GRADLE_USER_HOME": str(ROOT / ".gradle")}
    return subprocess.Popen(
        [str(ROOT / "gradlew"), "runE2eServer", "--no-daemon"],
        cwd=ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def run_checked(cmd: list[str], cwd: Path) -> None:
    env = {**os.environ, "GRADLE_USER_HOME": str(ROOT / ".gradle")}
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def wait_http(url: str, timeout: float, proc: subprocess.Popen[str] | None = None) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            output = ""
            if proc.stdout is not None:
                output = proc.stdout.read()
            raise RuntimeError(f"process exited while waiting for {url}:\n{output}")
        try:
            with urlopen_no_proxy(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for {url}")


def send(proc: subprocess.Popen[str], command: str) -> None:
    if proc.stdin is None:
        raise RuntimeError("process stdin is unavailable")
    proc.stdin.write(command + "\n")
    proc.stdin.flush()


def poll_command(
    proc: subprocess.Popen[str],
    output: "OutputReader",
    command: str,
    success: str,
    pending: list[str],
    timeout: float,
    interval: float = 1.0,
) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        send(proc, command)
        found = output.wait_for_any([success, *pending], timeout=5)
        if found == success:
            return
        time.sleep(interval)
    raise TimeoutError(f"{command} did not report {success!r} before timeout")


def run_chop_tree(proc: subprocess.Popen[str], output: "OutputReader", timeout: float, sidecar_port: int | None = None) -> None:
    send(proc, "mina-test request 砍树")
    assert_body_task_tool_call(sidecar_port, "chop_tree")
    poll_command(
        proc,
        output,
        "mina-test assert chop_tree",
        success="Mina test chop_tree passed",
        pending=["Mina test chop_tree failed"],
        timeout=timeout,
        interval=2.0,
    )


def run_follow_player(proc: subprocess.Popen[str], output: "OutputReader", timeout: float, sidecar_port: int | None = None) -> None:
    send(proc, "mina-test request 跟随我")
    output.wait_for("我开始跟随你", timeout=30)
    assert_body_task_tool_call(sidecar_port, "follow_player")
    poll_command(
        proc,
        output,
        "mina-test assert follow_player",
        success="Mina test follow_player passed",
        pending=["Mina test follow_player failed"],
        timeout=30,
        interval=1.0,
    )
    send(proc, "mina-test move_requester_far")
    output.wait_for("Mina test requester moved far", timeout=10)
    poll_command(
        proc,
        output,
        "mina-test assert follow_player",
        success="Mina test follow_player passed",
        pending=["Mina test follow_player failed"],
        timeout=timeout,
        interval=2.0,
    )


def run_read_only_command(proc: subprocess.Popen[str], output: "OutputReader", sidecar_port: int | None = None) -> None:
    send(proc, "mina-test request 查询时间")
    found = output.wait_for_any(["我来查询当前游戏时间", "我会执行这个只读查询"], timeout=30)
    if not found:
        raise TimeoutError("read-only command acknowledgement")
    output.wait_for("The time is", timeout=30)
    if sidecar_port is not None:
        call = wait_tool_call(
            sidecar_port,
            lambda item: item.get("tool_name") == "run_read_only_command"
            and item.get("status") == "ok"
            and "time query daytime" in str(item.get("args_json") or ""),
            timeout=10,
        )
        if not call:
            raise AssertionError("read-only command did not record a run_read_only_command tool call")
        event = wait_action_event(
            sidecar_port,
            lambda item: item.get("event_type") == "action_result"
            and item.get("action_name") == "run_read_only_command"
            and "The time is" in str(item.get("payload_json") or ""),
            timeout=10,
        )
        if not event:
            raise AssertionError("read-only command action_result was not recorded in the sidecar action journal")


def run_knowledge_query(proc: subprocess.Popen[str], output: "OutputReader", sidecar_port: int | None = None) -> None:
    send(proc, "mina-test request 查资料 Minecraft Wiki")
    found = output.wait_for_any(["搜索结果：Minecraft Wiki", "联网知识查询链路可用"], timeout=30)
    if not found:
        raise TimeoutError("knowledge query result")
    if sidecar_port is not None:
        call = wait_tool_call(
            sidecar_port,
            lambda item: item.get("tool_name") == "web_search"
            and item.get("status") == "ok"
            and "Minecraft Wiki" in str(item.get("result_json") or ""),
            timeout=10,
        )
        if not call:
            raise AssertionError("knowledge query did not record a successful web_search tool call")


def run_banned_command(proc: subprocess.Popen[str], output: "OutputReader") -> None:
    send(proc, "mina-test request 尝试作弊 setblock")
    output.wait_for("我会测试写命令拒绝路径", timeout=30)
    output.wait_for("mina read-only command refused command=setblock 2 80 0 minecraft:air", timeout=30)
    output.wait_for("Only read-only Minecraft commands are allowed", timeout=30)
    poll_command(
        proc,
        output,
        "mina-test assert target_log_present",
        success="Mina test target_log_present passed",
        pending=["Mina test target_log_present failed"],
        timeout=30,
        interval=1.0,
    )


def run_model_banned_command(
    proc: subprocess.Popen[str],
    output: "OutputReader",
    sidecar_port: int,
    deepseek_port: int,
) -> None:
    send(proc, "mina-test request 尝试作弊 setblock")
    output.wait_for("拒绝执行写命令", timeout=30)
    call = wait_tool_call(
        sidecar_port,
        lambda item: item.get("tool_name") == "run_read_only_command"
        and item.get("status") == "error"
        and "setblock 2 80 0 minecraft:air" in str(item.get("args_json") or "")
        and "Only read-only commands are allowed" in str(item.get("result_json") or ""),
        timeout=10,
    )
    if not call:
        raise AssertionError("model banned command did not record a rejected run_read_only_command tool call")
    events = read_json(f"http://127.0.0.1:{sidecar_port}/v1/action-events", timeout=5)
    if events.get("events"):
        raise AssertionError(f"model banned command should not schedule Fabric actions: {events!r}")
    poll_command(
        proc,
        output,
        "mina-test assert target_log_present",
        success="Mina test target_log_present passed",
        pending=["Mina test target_log_present failed"],
        timeout=30,
        interval=1.0,
    )
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 2:
        raise AssertionError(f"fake DeepSeek should have two calls for rejected command tool loop, got {calls!r}")


def run_model_private_body_tool(proc: subprocess.Popen[str], output: "OutputReader", sidecar_port: int, deepseek_port: int) -> None:
    send(proc, "mina-test request 请调用低层身体工具 body_chain")
    output.wait_for("拒绝低层身体工具", timeout=30)
    call = wait_tool_call(
        sidecar_port,
        lambda item: item.get("tool_name") == "body_chain"
        and item.get("status") == "error"
        and "private executor primitive" in str(item.get("result_json") or ""),
        timeout=10,
    )
    if not call:
        raise AssertionError("private body tool request did not record a rejected body_chain tool call")
    events = read_json(f"http://127.0.0.1:{sidecar_port}/v1/action-events", timeout=5).get("events", [])
    if events:
        raise AssertionError(f"private body tool request should not schedule Fabric actions: {events!r}")
    tasks = read_json(f"http://127.0.0.1:{sidecar_port}/v1/tasks", timeout=5).get("tasks", [])
    if tasks:
        raise AssertionError(f"private body tool request should not create body tasks: {tasks!r}")
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 2:
        raise AssertionError(f"fake DeepSeek should have two calls for rejected private body tool loop, got {calls!r}")


def run_task_status(proc: subprocess.Popen[str], output: "OutputReader", sidecar_port: int | None = None) -> None:
    send(proc, "mina-test request 状态")
    output.wait_for("当前没有正在执行的身体任务", timeout=30)
    if sidecar_port is not None:
        call = wait_tool_call(
            sidecar_port,
            lambda item: item.get("tool_name") == "task_status" and "task not found" in str(item.get("result_json") or ""),
            timeout=10,
        )
        if not call:
            raise AssertionError("initial status request did not record a task_status tool call")
    send(proc, "mina-test request 跟随我")
    output.wait_for("我开始跟随你", timeout=30)
    assert_body_task_tool_call(sidecar_port, "follow_player")
    send(proc, "mina-test request 状态")
    output.wait_for("当前任务：follow_player", timeout=30)
    output.wait_for("状态：active", timeout=30)
    if sidecar_port is not None:
        call = wait_tool_call(
            sidecar_port,
            lambda item: item.get("tool_name") == "task_status" and "follow_player" in str(item.get("result_json") or ""),
            timeout=10,
        )
        if not call:
            raise AssertionError("active status request did not record a task_status tool call")


def run_stop_follow(proc: subprocess.Popen[str], output: "OutputReader", timeout: float, sidecar_port: int | None = None) -> None:
    send(proc, "mina-test request 跟随我")
    output.wait_for("我开始跟随你", timeout=30)
    output.wait_for("mina monitor start", timeout=30)
    send(proc, "mina-test request 停止跟随")
    output.wait_for("我已经停止当前身体任务", timeout=30)
    output.wait_for("mina action start name=body_stop", timeout=30)
    output.wait_for("mina monitor cancelled", timeout=30)
    send(proc, "mina-test move_requester_far")
    output.wait_for("Mina test requester moved far", timeout=10)
    time.sleep(min(6.0, max(1.0, timeout / 20)))
    send(proc, "mina-test assert follow_player")
    found = output.wait_for_any(["Mina test follow_player failed", "Mina test follow_player passed"], timeout=10)
    if found != "Mina test follow_player failed":
        raise AssertionError("follow task still appears active after stop")
    if sidecar_port is not None:
        call = wait_tool_call(
            sidecar_port,
            lambda item: item.get("tool_name") == "stop_body_task" and item.get("status") == "ok",
            timeout=10,
        )
        if not call:
            raise AssertionError("stop_follow did not record a stop_body_task tool call")
        events = read_json(f"http://127.0.0.1:{sidecar_port}/v1/action-events", timeout=5).get("events", [])
        follow_ups = [
            event for event in events
            if isinstance(event, dict)
            and event.get("event_type") == "action_scheduled"
            and event.get("step_id") == "follow:2"
        ]
        if follow_ups:
            raise AssertionError(f"stop_follow should not schedule follow:2 after stop: {follow_ups!r}")


def run_replace_follow_with_chop(proc: subprocess.Popen[str], output: "OutputReader", timeout: float) -> None:
    send(proc, "mina-test request 跟随我")
    output.wait_for("我开始跟随你", timeout=30)
    send(proc, "mina-test request 砍树")
    output.wait_for("mina action start name=body_stop", timeout=30)
    poll_command(
        proc,
        output,
        "mina-test assert chop_tree",
        success="Mina test chop_tree passed",
        pending=["Mina test chop_tree failed"],
        timeout=timeout,
        interval=2.0,
    )


def run_body_unavailable(proc: subprocess.Popen[str], output: "OutputReader") -> None:
    send(proc, "mina-test request 跟随我")
    output.wait_for("我开始跟随你", timeout=30)
    output.wait_for("mina body unavailable enableBody=false", timeout=30)
    found = output.wait_for_any(["身体执行不可用", "跟随连续失败"], timeout=30)
    if not found:
        raise TimeoutError("body unavailable failure message")


def run_model_chop_tree(
    proc: subprocess.Popen[str],
    output: "OutputReader",
    timeout: float,
    sidecar_port: int,
    deepseek_port: int,
) -> None:
    run_chop_tree(proc, output, timeout, sidecar_port)
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 1:
        raise AssertionError(f"fake DeepSeek should have one call before chop_tree dispatch, got {calls!r}")


def run_model_chop_then_status(
    proc: subprocess.Popen[str],
    output: "OutputReader",
    timeout: float,
    sidecar_port: int,
    deepseek_port: int,
) -> None:
    run_model_chop_tree(proc, output, timeout, sidecar_port, deepseek_port)
    send(proc, "mina-test request 状态")
    output.wait_for("当前没有正在执行的身体任务", timeout=30)
    call = wait_tool_call(
        sidecar_port,
        lambda item: item.get("tool_name") == "task_status"
        and item.get("status") == "error"
        and "task not found" in str(item.get("result_json") or ""),
        timeout=10,
    )
    if not call:
        raise AssertionError("completed chop status request did not record an empty task_status tool call")
    tasks = read_json(f"http://127.0.0.1:{sidecar_port}/v1/tasks", timeout=5).get("tasks", [])
    completed = [
        task for task in tasks
        if isinstance(task, dict)
        and task.get("type") == "chop_tree"
        and task.get("status") == "completed"
        and task.get("stage") == "done"
    ]
    active = [task for task in tasks if isinstance(task, dict) and task.get("status") == "active"]
    if not completed or active:
        raise AssertionError(f"expected completed chop_tree and no active tasks after chop status query: {tasks!r}")
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 3:
        raise AssertionError(f"fake DeepSeek should have three calls for chop then status tool loop, got {calls!r}")


def run_model_chop_target_disappears(
    proc: subprocess.Popen[str],
    output: "OutputReader",
    timeout: float,
    sidecar_port: int,
    deepseek_port: int,
) -> None:
    send(proc, "mina-test move_body_far")
    output.wait_for("Mina test body moved far", timeout=10)
    send(proc, "mina-test request 砍树")
    output.wait_for("我开始砍树", timeout=30)
    assert_body_task_tool_call(sidecar_port, "chop_tree")
    output.wait_for("mina action start name=body_move_to_position", timeout=30)
    send(proc, "mina-test remove_target_log")
    output.wait_for("Mina test target log removed", timeout=10)
    poll_command(
        proc,
        output,
        "mina-test assert upper_log_absent",
        success="Mina test upper_log_absent passed",
        pending=["Mina test upper_log_absent failed"],
        timeout=timeout,
        interval=2.0,
    )
    tasks = read_json(f"http://127.0.0.1:{sidecar_port}/v1/tasks", timeout=5).get("tasks", [])
    completed = [
        task for task in tasks
        if isinstance(task, dict)
        and task.get("type") == "chop_tree"
        and task.get("status") == "completed"
        and task.get("last_error") == "target disappeared before attack"
    ]
    if not completed:
        raise AssertionError(f"expected completed recovered chop task after target disappearance: {tasks!r}")
    task_id = str(completed[0].get("task_id") or "")
    events = read_json(f"http://127.0.0.1:{sidecar_port}/v1/tasks/{task_id}/events", timeout=5).get("events", [])
    disappeared = [
        event for event in events
        if isinstance(event, dict)
        and event.get("event_type") == "target_disappeared"
    ]
    if not disappeared:
        raise AssertionError(f"expected target_disappeared task event for recovered chop task: {events!r}")
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 1:
        raise AssertionError(f"fake DeepSeek should have one call before recovered chop dispatch, got {calls!r}")


def run_model_unreachable_chop_tree(
    proc: subprocess.Popen[str],
    output: "OutputReader",
    sidecar_port: int,
    deepseek_port: int,
) -> None:
    send(proc, "mina-test request 砍树")
    output.wait_for("附近没有可安全接近的原木", timeout=30)
    send(proc, "mina-test assert target_log_present")
    output.wait_for("Mina test target_log_present passed", timeout=10)
    call = wait_tool_call(
        sidecar_port,
        lambda item: item.get("tool_name") == "start_body_task"
        and item.get("status") == "error"
        and "no log target" in str(item.get("result_json") or ""),
        timeout=10,
    )
    if not call:
        raise AssertionError("unreachable chop did not record a failed start_body_task tool call")
    events = read_json(f"http://127.0.0.1:{sidecar_port}/v1/action-events", timeout=5).get("events", [])
    if events:
        raise AssertionError(f"unreachable chop should not schedule Fabric actions: {events!r}")
    tasks = read_json(f"http://127.0.0.1:{sidecar_port}/v1/tasks", timeout=5).get("tasks", [])
    failed = [
        task for task in tasks
        if isinstance(task, dict)
        and task.get("type") == "chop_tree"
        and task.get("status") == "failed"
        and "no log target" in str(task.get("last_error") or "")
    ]
    if not failed:
        raise AssertionError(f"expected failed unreachable chop task: {tasks!r}")
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 2:
        raise AssertionError(f"fake DeepSeek should have two calls for unreachable chop tool loop, got {calls!r}")


def run_model_replace_follow_with_chop(
    proc: subprocess.Popen[str],
    output: "OutputReader",
    timeout: float,
    sidecar_port: int,
    deepseek_port: int,
) -> None:
    run_replace_follow_with_chop(proc, output, timeout)
    assert_body_task_tool_call(sidecar_port, "follow_player")
    assert_body_task_tool_call(sidecar_port, "chop_tree")
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 2:
        raise AssertionError(f"fake DeepSeek should have two calls for follow then chop_tree, got {calls!r}")


def run_model_action_barrier(
    proc: subprocess.Popen[str],
    output: "OutputReader",
    timeout: float,
    sidecar_port: int,
    deepseek_port: int,
) -> None:
    send(proc, "mina-test request 跟随我")
    output.wait_for("我开始跟随你", timeout=30)
    assert_body_task_tool_call(sidecar_port, "follow_player")
    poll_command(
        proc,
        output,
        "mina-test assert follow_player",
        success="Mina test follow_player passed",
        pending=["Mina test follow_player failed"],
        timeout=timeout,
        interval=2.0,
    )
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 1:
        raise AssertionError(f"fake DeepSeek should have one call before Fabric dispatch, got {calls!r}")


def run_model_follow_player(
    proc: subprocess.Popen[str],
    output: "OutputReader",
    timeout: float,
    sidecar_port: int,
    deepseek_port: int,
) -> None:
    run_follow_player(proc, output, timeout, sidecar_port)
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 1:
        raise AssertionError(f"fake DeepSeek should have one call before follow_player dispatch, got {calls!r}")


def run_model_spawn_body_follow(
    proc: subprocess.Popen[str],
    output: "OutputReader",
    timeout: float,
    sidecar_port: int,
    deepseek_port: int,
) -> None:
    send(proc, "mina-test leave_body")
    output.wait_for("Mina test body left.", timeout=10)
    send(proc, "mina-test request 跟随我")
    output.wait_for("我开始跟随你", timeout=30)
    assert_body_task_tool_call(sidecar_port, "follow_player")
    spawn = wait_action_event(
        sidecar_port,
        lambda item: item.get("event_type") == "action_scheduled" and item.get("action_name") == "body_spawn",
        timeout=10,
    )
    if not spawn:
        raise AssertionError("offline body follow did not schedule body_spawn")
    move = wait_action_event(
        sidecar_port,
        lambda item: item.get("event_type") == "action_scheduled" and item.get("action_name") == "body_move_to_requester",
        timeout=30,
    )
    if not move:
        raise AssertionError("offline body follow did not continue with body_move_to_requester")
    poll_command(
        proc,
        output,
        "mina-test assert follow_player",
        success="Mina test follow_player passed",
        pending=["Mina test follow_player failed"],
        timeout=timeout,
        interval=2.0,
    )
    send(proc, "mina-test move_requester_far")
    output.wait_for("Mina test requester moved far", timeout=10)
    poll_command(
        proc,
        output,
        "mina-test assert follow_player",
        success="Mina test follow_player passed",
        pending=["Mina test follow_player failed"],
        timeout=timeout,
        interval=2.0,
    )
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 1:
        raise AssertionError(f"fake DeepSeek should have one call before spawn-and-follow dispatch, got {calls!r}")


def run_model_follow_heartbeat(
    proc: subprocess.Popen[str],
    output: "OutputReader",
    timeout: float,
    sidecar_port: int,
    deepseek_port: int,
) -> None:
    send(proc, "mina-test request 跟随我")
    output.wait_for("我开始跟随你", timeout=30)
    assert_body_task_tool_call(sidecar_port, "follow_player")
    first = wait_action_event(
        sidecar_port,
        lambda item: item.get("event_type") == "action_scheduled"
        and item.get("action_name") == "body_move_to_requester"
        and item.get("step_id") == "follow:1",
        timeout=10,
    )
    if not first:
        raise AssertionError("follow heartbeat scenario did not schedule follow:1")
    second = wait_action_event(
        sidecar_port,
        lambda item: item.get("event_type") == "action_scheduled"
        and item.get("action_name") == "body_move_to_requester"
        and item.get("step_id") == "follow:2",
        timeout=min(timeout, 30),
    )
    if not second:
        raise AssertionError("follow heartbeat did not schedule follow:2 after monitor heartbeat")
    tasks = read_json(f"http://127.0.0.1:{sidecar_port}/v1/tasks", timeout=5).get("tasks", [])
    active = [
        task for task in tasks
        if isinstance(task, dict)
        and task.get("type") == "follow_player"
        and task.get("status") == "active"
        and int(task.get("cycles") or 0) >= 2
    ]
    if not active:
        raise AssertionError(f"expected active follow task with at least two cycles: {tasks!r}")
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 1:
        raise AssertionError(f"fake DeepSeek should have one call before follow heartbeat dispatch, got {calls!r}")


def run_model_multi_body_action_barrier(
    proc: subprocess.Popen[str],
    output: "OutputReader",
    sidecar_port: int,
    deepseek_port: int,
) -> None:
    send(proc, "mina-test request 请同时跟随我并砍树")
    output.wait_for("我开始跟随你", timeout=30)
    call = wait_tool_call(
        sidecar_port,
        lambda item: item.get("tool_name") == "start_body_task"
        and item.get("status") == "ok"
        and f'"task_type": "follow_player"' in str(item.get("args_json") or ""),
        timeout=10,
    )
    if not call:
        raise AssertionError("multi body action barrier did not record the first follow tool call")
    tool_calls = read_json(f"http://127.0.0.1:{sidecar_port}/v1/tool-calls", timeout=5).get("tool_calls", [])
    if len(tool_calls) != 1:
        raise AssertionError(f"multi body action barrier should record only the first action tool call: {tool_calls!r}")
    if "chop_tree" in str(tool_calls):
        raise AssertionError(f"multi body action barrier should not process the second chop_tree call: {tool_calls!r}")
    events = read_json(f"http://127.0.0.1:{sidecar_port}/v1/action-events", timeout=5).get("events", [])
    if any(isinstance(event, dict) and event.get("action_name") in {"body_move_to_position", "body_chain"} for event in events):
        raise AssertionError(f"multi body action barrier should not schedule chop_tree actions: {events!r}")
    tasks = read_json(f"http://127.0.0.1:{sidecar_port}/v1/tasks", timeout=5).get("tasks", [])
    active_follow = [
        task for task in tasks
        if isinstance(task, dict) and task.get("type") == "follow_player" and task.get("status") == "active"
    ]
    chop_tasks = [task for task in tasks if isinstance(task, dict) and task.get("type") == "chop_tree"]
    if not active_follow or chop_tasks:
        raise AssertionError(f"expected only an active follow task after multi body call barrier: {tasks!r}")
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 1:
        raise AssertionError(f"fake DeepSeek should have one call before multi body action barrier dispatch, got {calls!r}")


def assert_body_task_tool_call(sidecar_port: int | None, task_type: str) -> None:
    if sidecar_port is None:
        return
    call = wait_tool_call(
        sidecar_port,
        lambda item: item.get("tool_name") == "start_body_task"
        and item.get("status") == "ok"
        and f'"task_type": "{task_type}"' in str(item.get("args_json") or ""),
        timeout=10,
    )
    if not call:
        raise AssertionError(f"{task_type} request did not record a start_body_task tool call")


def run_model_read_only_command(proc: subprocess.Popen[str], output: "OutputReader", sidecar_port: int, deepseek_port: int) -> None:
    run_read_only_command(proc, output, sidecar_port)
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 1:
        raise AssertionError(f"fake DeepSeek should have one call before read-only command dispatch, got {calls!r}")


def run_model_knowledge_query(proc: subprocess.Popen[str], output: "OutputReader", sidecar_port: int, deepseek_port: int) -> None:
    run_knowledge_query(proc, output, sidecar_port)
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 2:
        raise AssertionError(f"fake DeepSeek should have two calls for web_search tool loop, got {calls!r}")


def run_model_memory_roundtrip(
    proc: subprocess.Popen[str],
    output: "OutputReader",
    sidecar_port: int,
    deepseek_port: int,
) -> None:
    send(proc, "mina-test request 记住我的基地在云杉树旁")
    output.wait_for("我记住了", timeout=30)
    write_call = wait_tool_call(
        sidecar_port,
        lambda item: item.get("tool_name") == "memory_write"
        and item.get("status") == "ok"
        and "云杉树旁" in str(item.get("args_json") or ""),
        timeout=10,
    )
    if not write_call:
        raise AssertionError("memory roundtrip did not record a memory_write tool call")
    send(proc, "mina-test request 回忆我的基地")
    output.wait_for("云杉树旁", timeout=30)
    search_call = wait_tool_call(
        sidecar_port,
        lambda item: item.get("tool_name") == "memory_search"
        and item.get("status") == "ok"
        and "云杉树旁" in str(item.get("result_json") or ""),
        timeout=10,
    )
    if not search_call:
        raise AssertionError("memory roundtrip did not record a memory_search result containing the remembered note")
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 4:
        raise AssertionError(f"fake DeepSeek should have four calls for memory write/search tool loops, got {calls!r}")


def run_model_task_status(
    proc: subprocess.Popen[str],
    output: "OutputReader",
    timeout: float,
    sidecar_port: int,
    deepseek_port: int,
) -> None:
    run_model_action_barrier(proc, output, timeout, sidecar_port, deepseek_port)
    send(proc, "mina-test request 状态")
    output.wait_for("当前任务：follow_player", timeout=30)
    output.wait_for("状态：active", timeout=30)
    call = wait_tool_call(
        sidecar_port,
        lambda item: item.get("tool_name") == "task_status"
        and item.get("status") == "ok"
        and "follow_player" in str(item.get("result_json") or ""),
        timeout=10,
    )
    if not call:
        raise AssertionError("model status request did not record an active task_status tool call")
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 3:
        raise AssertionError(f"fake DeepSeek should have three calls for follow plus task_status tool loop, got {calls!r}")


def run_model_stop_follow(
    proc: subprocess.Popen[str],
    output: "OutputReader",
    timeout: float,
    sidecar_port: int,
    deepseek_port: int,
) -> None:
    run_stop_follow(proc, output, timeout, sidecar_port)
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 2:
        raise AssertionError(f"fake DeepSeek should have two calls for follow plus stop, got {calls!r}")


def run_model_permission_denied(
    proc: subprocess.Popen[str],
    output: "OutputReader",
    sidecar_port: int,
    deepseek_port: int,
) -> None:
    send(proc, "mina-test deny_actions")
    output.wait_for("Mina test actions denied", timeout=10)
    send(proc, "mina-test request 跟随我")
    output.wait_for("我没有权限控制身体任务", timeout=30)
    call = wait_tool_call(
        sidecar_port,
        lambda item: item.get("tool_name") == "start_body_task"
        and item.get("status") == "error"
        and "permission denied" in str(item.get("result_json") or ""),
        timeout=10,
    )
    if not call:
        raise AssertionError("model permission denial did not record a failed start_body_task tool call")
    tasks = read_json(f"http://127.0.0.1:{sidecar_port}/v1/tasks", timeout=5)
    if tasks.get("tasks"):
        raise AssertionError(f"permission denied request should not create body tasks: {tasks!r}")
    events = read_json(f"http://127.0.0.1:{sidecar_port}/v1/action-events", timeout=5)
    if events.get("events"):
        raise AssertionError(f"permission denied request should not schedule Fabric actions: {events!r}")
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 2:
        raise AssertionError(f"fake DeepSeek should have two calls for denied follow tool loop, got {calls!r}")


def run_model_body_unavailable(
    proc: subprocess.Popen[str],
    output: "OutputReader",
    sidecar_port: int,
    deepseek_port: int,
) -> None:
    run_body_unavailable(proc, output)
    assert_body_task_tool_call(sidecar_port, "follow_player")
    calls = read_json(f"http://127.0.0.1:{deepseek_port}/calls", timeout=5)
    if calls.get("count") != 1:
        raise AssertionError(f"fake DeepSeek should have one call before body unavailable dispatch, got {calls!r}")


def run_permission_denied(proc: subprocess.Popen[str], output: "OutputReader", sidecar_port: int) -> None:
    send(proc, "mina-test deny_actions")
    output.wait_for("Mina test actions denied", timeout=10)
    send(proc, "mina-test request 跟随我")
    output.wait_for("离线模式无法完成请求：permission denied", timeout=30)
    tasks = read_json(f"http://127.0.0.1:{sidecar_port}/v1/tasks", timeout=5)
    if tasks.get("tasks"):
        raise AssertionError(f"permission denied request should not create body tasks: {tasks!r}")
    events = read_json(f"http://127.0.0.1:{sidecar_port}/v1/action-events", timeout=5)
    if events.get("events"):
        raise AssertionError(f"permission denied request should not schedule Fabric actions: {events!r}")


def stop_process(proc: subprocess.Popen[str], command: str | None = None) -> None:
    if proc.poll() is not None:
        return
    if command and proc.stdin is not None:
        try:
            send(proc, command)
            proc.wait(timeout=20)
            return
        except (BrokenPipeError, subprocess.TimeoutExpired):
            pass
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def write_trace_summary(port: int) -> None:
    try:
        with urlopen_no_proxy(f"http://127.0.0.1:{port}/v1/tasks", timeout=5) as response:
            payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except OSError:
        return
    try:
        action_events = read_json(f"http://127.0.0.1:{port}/v1/action-events", timeout=5).get("events", [])
        payload["action_events"] = compact_summary_action_events(action_events)
    except OSError:
        payload["action_events"] = []
    try:
        tool_calls = read_json(f"http://127.0.0.1:{port}/v1/tool-calls", timeout=5).get("tool_calls", [])
        payload["tool_calls"] = compact_summary_tool_calls(tool_calls)
    except OSError:
        payload["tool_calls"] = []
    trace = ROOT / "build" / "e2e" / "trace-summary.json"
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_trace_jsonl(port, payload)


def read_json(url: str, timeout: float) -> dict[str, Any]:
    with urlopen_no_proxy(url, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def wait_action_event(port: int, predicate, timeout: float) -> dict[str, Any]:  # noqa: ANN001
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = read_json(f"http://127.0.0.1:{port}/v1/action-events", timeout=5)
        for event in payload.get("events") or []:
            if isinstance(event, dict) and predicate(event):
                return event
        time.sleep(0.5)
    return {}


def wait_tool_call(port: int, predicate, timeout: float) -> dict[str, Any]:  # noqa: ANN001
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = read_json(f"http://127.0.0.1:{port}/v1/tool-calls", timeout=5)
        for call in payload.get("tool_calls") or []:
            if isinstance(call, dict) and predicate(call):
                return call
        time.sleep(0.5)
    return {}


def write_trace_jsonl(port: int, tasks_payload: dict[str, Any]) -> None:
    trace_id = f"e2e-{int(time.time())}"
    records: list[dict[str, Any]] = []
    try:
        action_events_payload = read_json(f"http://127.0.0.1:{port}/v1/action-events", timeout=5)
    except OSError:
        action_events_payload = {}
    for event in action_events_payload.get("events") or []:
        if not isinstance(event, dict):
            continue
        payload = event.get("payload_json")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                pass
        records.append(
            {
                "trace_id": trace_id,
                "request_id": event.get("request_id"),
                "task_id": event.get("task_id"),
                "step_id": event.get("step_id"),
                "action_id": event.get("action_id"),
                "action_name": event.get("action_name"),
                "event_type": event.get("event_type"),
                "created_at": event.get("created_at"),
                "payload": compact_trace_payload(payload),
            }
        )
    for call in tasks_payload.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        args = call.get("args") if "args" in call else parse_json_field(call.get("args_json"))
        result = call.get("result") if "result" in call else parse_json_field(call.get("result_json"))
        records.append(
            {
                "trace_id": trace_id,
                "request_id": call.get("request_id"),
                "tool_name": call.get("tool_name"),
                "event_type": "tool_call",
                "status": call.get("status"),
                "created_at": call.get("created_at"),
                "args": args,
                "result": result,
            }
        )
    for task in tasks_payload.get("tasks") or []:
        task_id = task.get("task_id")
        if not task_id:
            continue
        try:
            with urlopen_no_proxy(f"http://127.0.0.1:{port}/v1/tasks/{task_id}/events", timeout=5) as response:
                events: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        except OSError:
            continue
        for event in events.get("events") or []:
            payload = event.get("payload_json")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    pass
            records.append(
                {
                    "trace_id": trace_id,
                    "task_id": event.get("task_id") or task_id,
                    "event_type": event.get("event_type"),
                    "created_at": event.get("created_at"),
                    "payload": compact_trace_payload(payload),
                }
            )
    trace = ROOT / "build" / "e2e" / "trace.jsonl"
    trace.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def compact_summary_action_events(events: Any) -> list[dict[str, Any]]:
    compact_events: list[dict[str, Any]] = []
    if not isinstance(events, list):
        return compact_events
    for event in events:
        if not isinstance(event, dict):
            continue
        compact = dict(event)
        payload = compact.pop("payload_json", None)
        compact["payload"] = compact_trace_payload(parse_json_field(payload))
        compact_events.append(compact)
    return compact_events


def compact_summary_tool_calls(calls: Any) -> list[dict[str, Any]]:
    compact_calls: list[dict[str, Any]] = []
    if not isinstance(calls, list):
        return compact_calls
    for call in calls:
        if not isinstance(call, dict):
            continue
        compact = dict(call)
        compact["args"] = parse_json_field(compact.pop("args_json", None))
        compact["result"] = parse_json_field(compact.pop("result_json", None))
        compact_calls.append(compact)
    return compact_calls


def compact_trace_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = dict(payload)
    snapshot = compact.pop("snapshot", None)
    if isinstance(snapshot, dict):
        compact["snapshot_hash"] = snapshot_hash(snapshot)
        compact["snapshot_summary"] = trace_snapshot_summary(snapshot)
    return compact


def parse_json_field(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def trace_snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    player = snapshot.get("player_state") if isinstance(snapshot.get("player_state"), dict) else {}
    body = snapshot.get("body_state") if isinstance(snapshot.get("body_state"), dict) else {}
    world = snapshot.get("world_state") if isinstance(snapshot.get("world_state"), dict) else {}
    blocks = flatten_trace_blocks(snapshot.get("nearby_blocks"))
    entities = snapshot.get("nearby_entities") if isinstance(snapshot.get("nearby_entities"), list) else []
    return {
        "player": {
            "dimension": player.get("dimension"),
            "x": player.get("x"),
            "y": player.get("y"),
            "z": player.get("z"),
            "health": player.get("health"),
            "food": player.get("food"),
        },
        "body": {
            "online": body.get("online"),
            "x": body.get("x"),
            "y": body.get("y"),
            "z": body.get("z"),
            "yaw": body.get("yaw"),
            "pitch": body.get("pitch"),
            "distance_to_requester": body.get("distance_to_requester"),
            "targeted_block": body.get("targeted_block") or body.get("target_block"),
        },
        "world": {
            "day_time": world.get("day_time"),
            "difficulty": world.get("difficulty"),
            "weather": "thunder" if world.get("thundering") else "rain" if world.get("raining") else "clear",
        },
        "nearby": {
            "entities": len(entities),
            "blocks": len(blocks),
            "logs": sum(1 for block in blocks if block.get("category") == "log"),
        },
    }


def flatten_trace_blocks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        blocks: list[dict[str, Any]] = []
        for nested in value.values():
            blocks.extend(flatten_trace_blocks(nested))
        return blocks
    return []


class OutputReader:
    def __init__(self, proc: subprocess.Popen[str]):
        self.proc = proc
        self.lines: queue.Queue[str] = queue.Queue()
        self._thread = threading.Thread(target=self._read, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def wait_for(self, text: str, timeout: float) -> str:
        found = self.wait_for_any([text], timeout)
        if found != text:
            raise TimeoutError(text)
        return found

    def wait_for_any(self, texts: list[str], timeout: float) -> str:
        deadline = time.time() + timeout
        buffered: list[str] = []
        while time.time() < deadline:
            try:
                line = self.lines.get(timeout=0.25)
            except queue.Empty:
                if self.proc.poll() is not None:
                    raise RuntimeError("server exited while waiting for output:\n" + "".join(buffered[-80:]))
                continue
            buffered.append(line)
            sys.stdout.write(line)
            sys.stdout.flush()
            for text in texts:
                if text in line:
                    return text
        return ""

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.lines.put(line)


def urlopen_no_proxy(url: str, timeout: float):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(url, timeout=timeout)


if __name__ == "__main__":
    raise SystemExit(main())
