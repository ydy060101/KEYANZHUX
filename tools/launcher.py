"""Portable launcher for the research assistant (T8.4 packaging).

The web application needs PostgreSQL+pgvector, Redis and the local embedding
models, so a single-file executable cannot contain the whole system. What this
program does is make the checked-out application start like a desktop app:
double-click starts the portable services (when present), the API and the
worker, then opens the built frontend served by the API.

It only uses the standard library, so PyInstaller produces a small executable
that does not pull torch or Paddle into the bundle.

Usage:
    ResearchAssistant.exe            start, then open the browser
    ResearchAssistant.exe --check    print what was detected and exit
    ResearchAssistant.exe --no-browser
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from contextlib import suppress
from pathlib import Path

PG_PORT = 55432
REDIS_PORT = 56379
API_PORT = 8000
HEALTH = f"http://127.0.0.1:{API_PORT}/healthz"
APP_URL = f"http://127.0.0.1:{API_PORT}/"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def say(message: str) -> None:
    print(f"[科研助手] {message}", flush=True)


def find_root() -> Path:
    """The directory that contains `backend/run_server.py`.

    When frozen the executable sits in `release/`; when run as a script it is
    in `tools/`. Searching upwards (and, for the frozen case, the parent)
    covers both without hard-coding an absolute path.
    """
    start = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    for base in [start, *start.parents][:4]:
        if (base / "backend" / "run_server.py").is_file():
            return base
    raise SystemExit(
        "找不到应用目录：请把 ResearchAssistant.exe 放在仓库根目录或 release/ 下，"
        "并保持 backend/ 与 frontend/ 相邻。"
    )


def find_runtime(root: Path) -> Path | None:
    """Portable PostgreSQL/Redis installed beside the project.

    The folder name is not fixed (`科研助手-runtime` on this machine), so the
    candidates are the explicit override, a `runtime/` inside the checkout,
    and every sibling directory that actually contains the binaries.
    """
    candidates = []
    if os.environ.get("RA_RUNTIME"):
        candidates.append(Path(os.environ["RA_RUNTIME"]))
    candidates.append(root / "runtime")
    if root.parent.is_dir():
        candidates.extend(sorted(path for path in root.parent.iterdir() if path.is_dir()))
    for candidate in candidates:
        if (candidate / "pgsql" / "bin" / "pg_isready.exe").is_file():
            return candidate
    return None


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:  # noqa: S310 - fixed localhost URL
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def wait_until(predicate, seconds: float, label: str) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.4)
    say(f"{label}超时")
    return False


def start_postgres(runtime: Path) -> bool:
    if port_open(PG_PORT):
        return True
    pg_ready = runtime / "pgsql" / "bin" / "pg_isready.exe"
    if subprocess.run([str(pg_ready), "-h", "127.0.0.1", "-p", str(PG_PORT)], capture_output=True).returncode == 0:
        return True
    say("启动 PostgreSQL ...")
    command = [
        str(runtime / "pgsql" / "bin" / "pg_ctl.exe"),
        "-D",
        str(runtime / "pgdata"),
        "-l",
        str(runtime / "pg.log"),
        "-o",
        f"-p {PG_PORT} -c listen_addresses=127.0.0.1",
        "start",
    ]
    result = subprocess.run(command, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if result.returncode != 0:
        say(f"PostgreSQL 启动失败：{result.stderr.strip() or result.stdout.strip()}")
        return False
    return wait_until(lambda: port_open(PG_PORT), 20, "PostgreSQL 启动")


def start_redis(runtime: Path, log_dir: Path) -> bool:
    if port_open(REDIS_PORT):
        return True
    say("启动 Redis ...")
    log = (log_dir / "redis.log").open("ab")
    subprocess.Popen(
        [
            str(runtime / "redis" / "redis-server.exe"),
            "--port",
            str(REDIS_PORT),
            "--bind",
            "127.0.0.1",
            "--save",
            "",
            "--appendonly",
            "no",
        ],
        stdout=log,
        stderr=log,
        creationflags=CREATE_NO_WINDOW,
    )
    return wait_until(lambda: port_open(REDIS_PORT), 15, "Redis 启动")


def start_process(command: list[str], cwd: Path, log_path: Path) -> tuple[subprocess.Popen[bytes], object]:
    log = log_path.open("ab")
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=log,
        stderr=log,
        creationflags=CREATE_NO_WINDOW,
    )
    return process, log


def acquire_lock(root: Path):
    """One supervisor per checkout; a second double-click only opens the page."""
    path = root / "data" / "launcher.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def kill_on_close_job():
    """A Windows job object that kills its children when this process dies.

    Closing a console window terminates the launcher without running Python's
    `finally` blocks, which would otherwise leave the API and worker running
    and make the next double-click start a second worker. The job is only
    assigned to API/worker, so PostgreSQL and Redis stay up as documented.
    """
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class BasicLimit(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class ExtendedLimit(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimit),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = ExtendedLimit()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        return None
    return kernel32, job


def assign_to_job(job, process: subprocess.Popen[bytes]) -> None:
    if job is None or os.name != "nt":
        return
    kernel32, handle = job
    kernel32.AssignProcessToJobObject(handle, int(process._handle))  # noqa: SLF001 - Popen exposes no public handle



def check(root: Path) -> int:
    runtime = find_runtime(root)
    python = root / "backend" / ".venv" / "Scripts" / "python.exe"
    dist = root / "frontend" / "dist" / "index.html"
    say(f"应用目录: {root}")
    say(f"Python:   {python} ({'存在' if python.is_file() else '缺失'})")
    say(f"前端构建: {dist} ({'存在' if dist.is_file() else '缺失'})")
    say(f"便携运行时: {runtime or '未找到（使用已有的 PostgreSQL/Redis）'}")
    say(f"端口: PostgreSQL {PG_PORT} {'占用' if port_open(PG_PORT) else '空闲'} / "
        f"Redis {REDIS_PORT} {'占用' if port_open(REDIS_PORT) else '空闲'} / "
        f"API {API_PORT} {'运行中' if http_ok(HEALTH) else '未启动'}")
    return 0 if python.is_file() and dist.is_file() else 1


def run(root: Path, *, open_browser: bool) -> int:
    runtime = find_runtime(root)
    log_dir = root / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    if runtime is not None:
        if not start_postgres(runtime):
            return 1
        if not start_redis(runtime, log_dir):
            return 1
    elif not (port_open(PG_PORT) and port_open(REDIS_PORT)):
        say("没有找到便携 PostgreSQL/Redis，请先运行 .\\tools.ps1 db-up，或设置 RA_RUNTIME。")
        return 1

    if not (root / "frontend" / "dist" / "index.html").is_file():
        say("前端尚未构建：请先运行 .\\tools.ps1 exe（会执行 npm run build）。")
        return 1

    python = root / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        say("后端虚拟环境缺失：请在 backend 下创建 .venv 并安装依赖（见 docs/RUN-EXE.md）。")
        return 1

    children: list[subprocess.Popen[bytes]] = []
    logs: list[object] = []
    own_api = False
    job = kill_on_close_job()
    try:
        if not http_ok(HEALTH):
            say("启动后端 API ...")
            api, api_log = start_process(
                [str(python), "-I", "run_server.py"], root / "backend", log_dir / "api.log"
            )
            assign_to_job(job, api)
            children.append(api)
            logs.append(api_log)
            own_api = True
            if not wait_until(lambda: http_ok(HEALTH), 90, "后端启动"):
                say(f"后端日志：{log_dir / 'api.log'}")
                return 1
        else:
            say("后端 API 已在运行，直接复用。")

        say("启动后台任务 worker ...")
        worker, worker_log = start_process(
            [str(python), "-m", "app.worker"], root / "backend", log_dir / "worker.log"
        )
        assign_to_job(job, worker)
        children.append(worker)
        logs.append(worker_log)

        say(f"就绪：{APP_URL}")
        if open_browser:
            webbrowser.open(APP_URL)
        say("关闭此窗口或按 Ctrl+C 停止本次启动的 API 与 worker（PostgreSQL/Redis 保持运行）。")

        while True:
            time.sleep(2)
            for child in children:
                if child.poll() is not None:
                    say(f"一个子进程已退出（exit {child.returncode}），日志位于 {log_dir}")
                    children.remove(child)
                    break
            if not children:
                say("所有子进程已退出。")
                return 1
    except KeyboardInterrupt:
        say("正在停止 ...")
        return 0
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        deadline = time.monotonic() + 5
        for child in children:
            try:
                child.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                child.kill()
        for log in logs:
            with suppress(OSError):
                log.close()  # type: ignore[attr-defined]
        if own_api:
            say("已停止 API 与 worker。")
        else:
            say("已停止本次启动的 worker；API 是外部进程，未停止。")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    root = find_root()
    if "--check" in sys.argv[1:]:
        return check(root)
    lock = acquire_lock(root)
    if lock is None:
        say("已有一个启动器在运行，打开页面即可。")
        webbrowser.open(APP_URL)
        return 0
    try:
        return run(root, open_browser="--no-browser" not in sys.argv[1:])
    finally:
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
