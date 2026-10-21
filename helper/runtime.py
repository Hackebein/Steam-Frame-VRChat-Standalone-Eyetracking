import logging
import logging.handlers
import os
import pathlib
import shlex
import subprocess
import sys
import threading
import time

CONTAINER = "lepton-steamlaunch-438100"
ANDROID_DIR = "/data/local/tmp/frame-nsd-helper"
CLASS = "local.frame.nsd.FrameNsdHelper"
HERE = pathlib.Path(__file__).resolve().parent


class Runtime:
    def __init__(self):
        self.container = CONTAINER
        self.sender = None
        self.reader = None
        self.eye_logger = None
        self.eye_log_path = None

    @staticmethod
    def run(args, check=True, timeout=8):
        if args[:2] == ["podman", "exec"]:
            args = [args[0], "--events-backend=none"] + args[1:]
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if check and result.returncode:
            raise RuntimeError(
                (result.stderr or result.stdout or "Command failed").strip()
            )
        return result

    def android(self, args, **kwargs):
        return self.run(["podman", "exec", self.container] + args, **kwargs)

    def read_file(self, path):
        return self.android(["cat", path], check=False).stdout

    def owned_helper(self):
        pid = self.read_file(ANDROID_DIR + "/helper.pid").strip()
        if not pid.isdigit() or int(pid) < 2:
            return None
        args = self.read_file("/proc/" + pid + "/cmdline").split("\0")
        if CLASS not in args and "frame-nsd-helper" not in args:
            return None
        return pid

    def service_found(self):
        return (
            ": found" in self.android(["service", "check", "servicediscovery"]).stdout
        )

    def start_helper(self):
        if self.service_found():
            return
        self.stop_helper()
        self.android(["mkdir", "-p", ANDROID_DIR])
        self.android(
            ["rm", "-f", ANDROID_DIR + "/helper.log", ANDROID_DIR + "/helper.pid"]
        )
        self.run(
            [
                "podman",
                "cp",
                str(HERE / "frame-nsd-helper.jar"),
                self.container + ":" + ANDROID_DIR + "/frame-nsd-helper.jar",
            ]
        )
        environment = {}
        for number, line in enumerate(
            self.read_file("/init.environ.rc").splitlines(), 1
        ):
            try:
                fields = shlex.split(line)
            except ValueError as error:
                raise RuntimeError(
                    f"Invalid quoting in /init.environ.rc line {number}: {error}"
                ) from error
            if len(fields) == 3 and fields[0] == "export":
                environment[fields[1]] = fields[2]
        if not environment.get("SYSTEMSERVERCLASSPATH"):
            raise RuntimeError(
                "Android runtime environment is not ready or is unsupported."
            )
        environment["CLASSPATH"] = (
            ANDROID_DIR
            + "/frame-nsd-helper.jar:"
            + environment["SYSTEMSERVERCLASSPATH"]
        )
        command = ["podman", "exec", "--detach"]
        for key, value in environment.items():
            command += ["--env", key + "=" + value]
        command += [self.container]
        java = [
            "/system/bin/app_process64",
            "/system/bin",
            "--nice-name=frame-nsd-helper",
            CLASS,
        ]
        script = "echo $$ > " + ANDROID_DIR + "/helper.pid; exec "
        script += " ".join(shlex.quote(arg) for arg in java)
        script += " > " + ANDROID_DIR + "/helper.log 2>&1"
        self.run(command + ["/system/bin/sh", "-c", script])
        log = ""
        started = time.monotonic()
        seen_helper = False
        while time.monotonic() - started < 8:
            log = self.read_file(ANDROID_DIR + "/helper.log")
            if "READY:" in log and self.service_found():
                return
            if self.owned_helper():
                seen_helper = True
            elif seen_helper or time.monotonic() - started >= 1:
                if self.service_found():
                    return
                raise RuntimeError(
                    "Android NSD helper exited during startup. " + log[-2000:].strip()
                )
            time.sleep(0.25)
        self.stop_helper()
        raise RuntimeError("Android NSD helper did not become ready. " + log[-2000:])

    def stop_helper(self):
        pid = self.owned_helper()
        if pid:
            self.android(["kill", "-TERM", pid], check=False)
            for _ in range(20):
                if self.owned_helper() != pid:
                    break
                time.sleep(0.1)
            if self.owned_helper() == pid:
                raise RuntimeError("Android NSD helper did not stop.")

    def cleanup_helper(self):
        result = self.run(
            ["podman", "inspect", "--format", "{{.State.Running}}", self.container],
            check=False,
        )
        if result.returncode:
            if "no such" in result.stderr.lower():
                return
            raise RuntimeError(
                result.stderr.strip() or "Cannot inspect the VRChat container."
            )
        if result.stdout.strip() != "true":
            return
        self.stop_helper()
        self.android(
            ["rm", "-f"]
            + [
                ANDROID_DIR + "/" + name
                for name in ("frame-nsd-helper.jar", "helper.log", "helper.pid")
            ]
        )
        self.android(["rmdir", ANDROID_DIR], check=False)

    def eye_pid(self):
        if self.sender is not None and self.sender.poll() is None:
            return self.sender.pid
        return None

    def start_eyes(self):
        if self.eye_pid():
            return
        self.stop_eyes()
        if self.eye_logger is None:
            state = pathlib.Path(
                os.environ.get("XDG_STATE_HOME", pathlib.Path.home() / ".local/state")
            )
            state = state / "frame-vrchat-tracking"
            state.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.eye_log_path = state / "eyes.log"
            handler = logging.handlers.RotatingFileHandler(
                self.eye_log_path, maxBytes=131072, backupCount=1
            )
            logger = logging.getLogger("frame-eye-sender")
            logger.setLevel(logging.INFO)
            logger.propagate = False
            logger.addHandler(handler)
            self.eye_logger = logger
        self.sender = subprocess.Popen(
            [str(HERE / "frame-eyes")],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        def read_output(process):
            try:
                for line in process.stdout:
                    self.eye_logger.info(line.rstrip())
            finally:
                process.stdout.close()

        self.reader = threading.Thread(
            target=read_output, args=(self.sender,), daemon=True
        )
        self.reader.start()
        time.sleep(0.1)
        if not self.eye_pid():
            raise RuntimeError(f"Eye sender exited; see {self.eye_log_path}.")

    def stop_eyes(self):
        if self.sender is not None:
            if self.sender.poll() is None:
                self.sender.terminate()
                try:
                    self.sender.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.sender.kill()
                    self.sender.wait(timeout=2)
            else:
                self.sender.wait()
            self.sender = None
        if self.reader:
            self.reader.join(timeout=1)
            self.reader = None

    def close(self):
        self.stop_eyes()
        if self.eye_logger:
            for handler in self.eye_logger.handlers[:]:
                self.eye_logger.removeHandler(handler)
                handler.close()


if __name__ == "__main__":
    runtime = Runtime()
    try:
        if sys.argv[1:] == ["stop-helper"]:
            runtime.cleanup_helper()
        else:
            raise RuntimeError("Use stop-helper.")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
