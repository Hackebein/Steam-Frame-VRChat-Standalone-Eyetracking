#!/usr/bin/env python3
import fcntl
import json
import os
import pathlib
import signal
import subprocess
import threading
import time

from runtime import CONTAINER, Runtime


def log(event, **details):
    print(json.dumps(dict(event=event, **details)), flush=True)


class Supervisor:
    def __init__(self):
        self.runtime = Runtime()
        self.ready_id = None
        self.sender_pid = None
        self.last_attempt = -5
        self.last_health = 0
        self.last_error = None
        self.last_error_at = 0

    def stop_eyes(self):
        self.runtime.stop_eyes()
        if self.sender_pid:
            log("eye_sender_stopped")
        self.sender_pid = None

    def step(self):
        result = self.runtime.run(
            ["podman", "inspect", "--format", "{{.Id}} {{.State.Running}}", CONTAINER],
            check=False,
            timeout=5,
        )
        fields = result.stdout.split()
        if len(fields) != 2 or fields[1] != "true":
            if result.returncode and "no such" not in result.stderr.lower():
                raise RuntimeError(
                    result.stderr.strip() or "Cannot inspect the VRChat container."
                )
            if self.ready_id:
                log("vrchat_closed")
            self.ready_id = None
            self.stop_eyes()
            return 30.0

        current_id = fields[0]
        self.runtime.container = current_id
        now = time.monotonic()
        if self.ready_id != current_id:
            self.stop_eyes()
            activity = self.runtime.android(["service", "check", "activity"], timeout=3)
            if ": found" not in activity.stdout:
                return 0.15
            before = self.runtime.android(
                ["pidof", "com.vrchat.android"], check=False
            ).stdout.strip()
            existing = self.runtime.service_found()
            if not existing:
                self.runtime.start_helper()
            self.ready_id = current_id
            self.last_health = now
            log(
                "discovery_ready",
                source="existing" if existing else "helper",
                before_vrchat=not bool(before),
            )
            if before and not existing:
                log(
                    "restart_note",
                    message="If OSC does not work, fully close and reopen VRChat once.",
                )

        if now - self.last_health >= 10:
            if not self.runtime.service_found():
                self.runtime.start_helper()
                log("discovery_restored")
            self.last_health = time.monotonic()

        probe = self.runtime.android(
            [
                "/system/bin/sh",
                "-c",
                "pidof com.vrchat.android && cat /proc/net/udp /proc/net/udp6",
            ],
            check=False,
        )
        lines = probe.stdout.splitlines()
        pids = lines[0].split() if lines else []
        game = bool(pids) and all(pid.isdigit() for pid in pids)
        osc = any(
            len(fields) > 1 and fields[1].rsplit(":", 1)[-1].upper() == "2328"
            for fields in (line.split() for line in lines[1:])
        )
        if not game or not osc:
            self.stop_eyes()
        else:
            pid = self.runtime.eye_pid()
            if not pid and now - self.last_attempt >= 5:
                self.last_attempt = now
                self.runtime.start_eyes()
                pid = self.runtime.eye_pid()
            if pid and pid != self.sender_pid:
                self.sender_pid = pid
                log("eye_sender_running", pid=pid)
        self.last_error = None
        return 2.0

    def report_error(self, error):
        message = str(error)
        now = time.monotonic()
        if message != self.last_error or now - self.last_error_at >= 30:
            log("retry", error=message)
            self.last_error = message
            self.last_error_at = now


class Events:
    def __init__(self, wake):
        self.wake = wake
        self.process = None
        self.retry_at = 0
        self.started_at = 0
        self.failed = False

    def alive(self):
        return self.process is not None and self.process.poll() is None

    def ensure(self):
        now = time.monotonic()
        if self.alive():
            if self.failed and now - self.started_at >= 2:
                log("events_recovered")
                self.failed = False
            return
        if self.process is not None and not self.failed:
            log(
                "events_unavailable",
                exit_code=self.process.returncode,
                message="Using two-second polling while the event stream is unavailable.",
            )
            self.failed = True
        if now < self.retry_at:
            return
        self.retry_at = now + 5
        if self.process:
            self.process.wait()
        self.process = subprocess.Popen(
            [
                "podman",
                "events",
                "--format=json",
                "--filter",
                "type=container",
                "--filter",
                "container=" + CONTAINER,
                "--filter",
                "event=start",
                "--filter",
                "event=stop",
                "--filter",
                "event=died",
                "--filter",
                "event=remove",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self.started_at = now

        def read(process):
            try:
                for _line in process.stdout:
                    self.wake.set()
            finally:
                process.stdout.close()
                self.wake.set()

        threading.Thread(target=read, args=(self.process,), daemon=True).start()

    def close(self):
        if self.process:
            if self.alive():
                self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


def main():
    runtime_dir = pathlib.Path(os.environ["XDG_RUNTIME_DIR"]) / "frame-vrchat-tracking"
    runtime_dir.mkdir(mode=0o700, exist_ok=True)
    with (runtime_dir / "daemon.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("A Frame VRChat Tracking watcher is already running.")
        wake = threading.Event()
        stopping = threading.Event()

        def stop(_number, _frame):
            stopping.set()
            wake.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        events = Events(wake)
        supervisor = Supervisor()
        log("watcher_started")
        try:
            while not stopping.is_set():
                wake.clear()
                try:
                    events.ensure()
                    delay = supervisor.step()
                except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                    supervisor.report_error(error)
                    delay = 1.0
                if not events.alive():
                    delay = 2.0
                wake.wait(delay)
        finally:
            events.close()
            supervisor.stop_eyes()
            supervisor.runtime.close()
            log("watcher_stopped")


if __name__ == "__main__":
    main()
