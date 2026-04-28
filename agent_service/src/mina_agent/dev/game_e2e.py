from __future__ import annotations

import argparse
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
            "task_status",
            "stop_follow",
            "replace_follow_with_chop",
            "body_unavailable",
            "offline_knowledge_query",
            "offline_read_only_command",
            "offline_chop_tree",
            "offline_follow",
        ],
    )
    parser.add_argument("--sidecar", default="scripted", choices=["scripted", "service"])
    parser.add_argument("--port", type=int, default=18911)
    parser.add_argument("--server-port", type=int, default=25566)
    parser.add_argument("--search-port", type=int, default=18888)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    prepare_runtime(args.port, args.server_port, enable_body=args.scenario != "body_unavailable")
    if not args.skip_build:
        run_checked([str(ROOT / "gradlew"), "build", "--no-daemon"], cwd=ROOT)

    offline_service_scenarios = {"offline_follow", "offline_read_only_command", "offline_knowledge_query", "offline_chop_tree"}
    fake_search = start_fake_search(args.search_port) if args.scenario == "offline_knowledge_query" else None
    sidecar_mode = "service" if args.scenario in offline_service_scenarios else args.sidecar
    sidecar = start_sidecar(
        args.port,
        sidecar_mode,
        force_offline=args.scenario in offline_service_scenarios,
        searxng_url=f"http://127.0.0.1:{args.search_port}" if fake_search is not None else None,
    )
    server = None
    try:
        if fake_search is not None:
            wait_http(f"http://127.0.0.1:{args.search_port}/healthz", timeout=20, proc=fake_search)
        wait_http(f"http://127.0.0.1:{args.port}/healthz", timeout=20, proc=sidecar)
        server = start_server()
        output = OutputReader(server)
        output.start()
        output.wait_for("Done", timeout=args.timeout)
        setup_scenario = (
            "chop_tree"
            if args.scenario in {"replace_follow_with_chop", "banned_command", "offline_chop_tree"}
            else "follow_player"
            if args.scenario in {
                "read_only_command",
                "knowledge_query",
                "task_status",
                "stop_follow",
                "body_unavailable",
                "offline_follow",
                "offline_read_only_command",
                "offline_knowledge_query",
            }
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
        elif args.scenario == "task_status":
            run_task_status(server, output)
        elif args.scenario == "stop_follow":
            run_stop_follow(server, output, args.timeout)
        elif args.scenario == "replace_follow_with_chop":
            run_replace_follow_with_chop(server, output, args.timeout)
        elif args.scenario == "body_unavailable":
            run_body_unavailable(server, output)
        elif args.scenario == "offline_knowledge_query":
            run_knowledge_query(server, output)
        elif args.scenario == "offline_read_only_command":
            run_read_only_command(server, output)
        elif args.scenario == "offline_chop_tree":
            run_chop_tree(server, output, args.timeout)
        elif args.scenario == "offline_follow":
            run_follow_player(server, output, args.timeout)
        write_trace_summary(args.port)
        return 0
    finally:
        if server is not None:
            stop_process(server, command="stop")
        stop_process(sidecar)
        if fake_search is not None:
            stop_process(fake_search)


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


def start_sidecar(port: int, mode: str, force_offline: bool = False, searxng_url: str | None = None) -> subprocess.Popen[str]:
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


def run_chop_tree(proc: subprocess.Popen[str], output: "OutputReader", timeout: float) -> None:
    send(proc, "mina-test request 砍树")
    poll_command(
        proc,
        output,
        "mina-test assert chop_tree",
        success="Mina test chop_tree passed",
        pending=["Mina test chop_tree failed"],
        timeout=timeout,
        interval=2.0,
    )


def run_follow_player(proc: subprocess.Popen[str], output: "OutputReader", timeout: float) -> None:
    send(proc, "mina-test request 跟随我")
    output.wait_for("我开始跟随你", timeout=30)
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


def run_read_only_command(proc: subprocess.Popen[str], output: "OutputReader") -> None:
    send(proc, "mina-test request 查询时间")
    found = output.wait_for_any(["我来查询当前游戏时间", "我会执行这个只读查询"], timeout=30)
    if not found:
        raise TimeoutError("read-only command acknowledgement")
    output.wait_for("The time is", timeout=30)


def run_knowledge_query(proc: subprocess.Popen[str], output: "OutputReader") -> None:
    send(proc, "mina-test request 查资料 Minecraft Wiki")
    found = output.wait_for_any(["搜索结果：Minecraft Wiki", "联网知识查询链路可用"], timeout=30)
    if not found:
        raise TimeoutError("knowledge query result")


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


def run_task_status(proc: subprocess.Popen[str], output: "OutputReader") -> None:
    send(proc, "mina-test request 状态")
    output.wait_for("当前没有正在执行的身体任务", timeout=30)
    send(proc, "mina-test request 跟随我")
    output.wait_for("我开始跟随你", timeout=30)
    send(proc, "mina-test request 状态")
    output.wait_for("当前任务：follow_player", timeout=30)
    output.wait_for("状态：active", timeout=30)


def run_stop_follow(proc: subprocess.Popen[str], output: "OutputReader", timeout: float) -> None:
    send(proc, "mina-test request 跟随我")
    output.wait_for("我开始跟随你", timeout=30)
    output.wait_for("mina monitor start", timeout=30)
    send(proc, "mina-test request 停止跟随")
    output.wait_for("我已经停止当前身体任务", timeout=30)
    output.wait_for("mina action start name=body_stop", timeout=30)
    send(proc, "mina-test move_requester_far")
    output.wait_for("Mina test requester moved far", timeout=10)
    time.sleep(min(6.0, max(1.0, timeout / 20)))
    send(proc, "mina-test assert follow_player")
    found = output.wait_for_any(["Mina test follow_player failed", "Mina test follow_player passed"], timeout=10)
    if found != "Mina test follow_player failed":
        raise AssertionError("follow task still appears active after stop")


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
    output.wait_for("跟随连续失败", timeout=30)


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
    trace = ROOT / "build" / "e2e" / "trace-summary.json"
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_trace_jsonl(port, payload)


def write_trace_jsonl(port: int, tasks_payload: dict[str, Any]) -> None:
    trace_id = f"e2e-{int(time.time())}"
    records: list[dict[str, Any]] = []
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
                    "payload": payload,
                }
            )
    trace = ROOT / "build" / "e2e" / "trace.jsonl"
    trace.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


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
