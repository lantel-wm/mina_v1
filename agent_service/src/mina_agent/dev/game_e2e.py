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
    parser.add_argument("--scenario", default="chop_tree", choices=["chop_tree", "follow_player", "read_only_command"])
    parser.add_argument("--sidecar", default="scripted", choices=["scripted"])
    parser.add_argument("--port", type=int, default=18911)
    parser.add_argument("--server-port", type=int, default=25566)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    prepare_runtime(args.port, args.server_port)
    if not args.skip_build:
        run_checked([str(ROOT / "gradlew"), "build", "--no-daemon"], cwd=ROOT)

    sidecar = start_sidecar(args.port)
    server = None
    try:
        wait_http(f"http://127.0.0.1:{args.port}/healthz", timeout=20, proc=sidecar)
        server = start_server()
        output = OutputReader(server)
        output.start()
        output.wait_for("Done", timeout=args.timeout)
        setup_scenario = "follow_player" if args.scenario == "read_only_command" else args.scenario
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
        write_trace_summary(args.port)
        return 0
    finally:
        if server is not None:
            stop_process(server, command="stop")
        stop_process(sidecar)


def prepare_runtime(port: int, server_port: int) -> None:
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
                "enableBody": True,
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


def start_sidecar(port: int) -> subprocess.Popen[str]:
    pythonpath = str(ROOT / "agent_service" / "src")
    env = {
        **os.environ,
        "MINA_DB_PATH": str(ROOT / "build" / "e2e" / "mina-scripted.sqlite3"),
        "PYTHONPATH": pythonpath + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "mina_agent.dev.scripted_sidecar:app", "--host", "127.0.0.1", "--port", str(port)],
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
    output.wait_for("我来查询当前游戏时间", timeout=30)
    output.wait_for("The time is", timeout=30)


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
