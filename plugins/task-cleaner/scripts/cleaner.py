#!/usr/bin/env python3
"""Track and remove disposable files for completed Codex tasks."""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
import uuid


class Refused(RuntimeError):
    pass


def private_dir(path):
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise Refused("The directory type or owner is incorrect.")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise Refused("The directory must have mode 0700.")


def read_json(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise Refused("The record must be a regular file with one link.")
        return json.load(stream)


def write_json(path, value):
    temporary = path.with_name(".record-" + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def digest(value):
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise Refused("A nonempty session or turn identifier is required.")
    return hashlib.sha256(value.encode()).hexdigest()


def open_files(path):
    executable = shutil.which("lsof")
    if not executable:
        raise Refused("lsof is unavailable. Keep the temporary files.")
    try:
        result = subprocess.run(
            [executable, "-nP", "+D", str(path), "-Fp"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refused("The open-file check failed. Keep the temporary files.") from error
    if result.stderr.strip() or result.returncode not in (0, 1):
        raise Refused("The open-file check was incomplete. Keep the temporary files.")
    if result.stdout.strip() or result.returncode == 0:
        raise Refused("A process uses the temporary directory. Keep its files.")


class Store:
    def __init__(self, root=None):
        # A fixed private root excludes arbitrary cleanup paths.
        self.root = root or Path("/private/tmp" if sys.platform == "darwin" else "/tmp") / (
            "codex-task-cleaner-" + str(os.getuid())
        )
        private_dir(self.root)

    @contextmanager
    def locked(self):
        fd = os.open(self.root / ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise Refused("The lock file is invalid.")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def location(self, task):
        if not re.fullmatch(r"[a-f0-9]{64}", task):
            raise Refused("The task identifier is invalid.")
        folder = self.root / task
        info = folder.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise Refused("The task directory is invalid.")
        if stat.S_IMODE(info.st_mode) != 0o700:
            raise Refused("The task directory must have mode 0700.")
        return folder

    def record(self, task):
        data = read_json(self.location(task) / "record.json")
        if data.get("version") != 1 or data.get("task") != task:
            raise Refused("The task record is invalid.")
        return data

    def start(self, session, turn):
        session_key = digest(session)
        task = digest(session_key + ":" + digest(turn))
        folder = self.root / task
        if folder.exists() or folder.is_symlink():
            data = self.record(task)
            if data["status"] == "removed":
                raise Refused("This turn was already cleaned. Start a new turn.")
            self.work(task, data)
            return data
        private_dir(folder)
        work = folder / "work"
        private_dir(work)
        info = work.lstat()
        data = {"version": 1, "task": task, "session": session_key,
                "status": "active", "created": time.time(),
                "device": info.st_dev, "inode": info.st_ino}
        write_json(folder / "record.json", data)
        return data

    def work(self, task, data):
        work = self.location(task) / "work"
        info = work.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or (info.st_dev, info.st_ino) != (data["device"], data["inode"])):
            raise Refused("The temporary directory was replaced. Keep its files.")
        return work

    def status(self, task, status):
        data = self.record(task)
        if data["status"] == "removed":
            raise Refused("This directory was already removed.")
        self.work(task, data)
        data["status"] = status
        write_json(self.location(task) / "record.json", data)
        return data

    def records(self):
        for path in sorted(self.root.iterdir()):
            if re.fullmatch(r"[a-f0-9]{64}", path.name):
                yield self.record(path.name)

    def clean(self, task, apply=False):
        data = self.record(task)
        if data["status"] == "removed":
            return {"task": task, "status": "already removed"}
        work = self.work(task, data)
        if data["status"] != "ready":
            raise Refused("The task is not ready for cleanup.")
        if not shutil.rmtree.avoids_symlink_attacks:
            raise Refused("This Python build cannot remove directories safely.")
        size, count = 0, 0
        for directory, folders, files in os.walk(work, followlinks=False):
            for name in folders + files:
                info = (Path(directory) / name).lstat()
                if info.st_dev != data["device"]:
                    raise Refused("A mounted filesystem is inside the task directory.")
                if stat.S_ISREG(info.st_mode):
                    if info.st_nlink != 1:
                        raise Refused("A file has multiple hard links. Keep its files.")
                    count += 1
                    size += info.st_size
                elif not (stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)):
                    raise Refused("A special file is inside the task directory.")
        open_files(work)
        self.work(task, data)
        report = {"task": task, "path": str(work), "files": count,
                  "bytes": size, "status": "preview"}
        if apply:
            shutil.rmtree(work)
            data["status"] = "removed"
            data["removed"] = time.time()
            data["bytes"] = size
            write_json(self.location(task) / "record.json", data)
            report["status"] = "removed"
        return report


def format_size(size):
    if size < 1024:
        return f"{size} B"
    for unit in ("KiB", "MiB", "GiB", "TiB", "PiB"):
        size /= 1024
        if size < 1024 or unit == "PiB":
            return f"{size:.1f} {unit}"


def hook(store, payload):
    event = payload.get("hook_event_name")
    if event == "UserPromptSubmit":
        data = store.start(payload.get("session_id"), payload.get("turn_id"))
        path = store.work(data["task"], data)
        helper = "python3 " + shlex.quote(str(Path(__file__).resolve()))
        context = (
            f"Task Cleaner temporary directory: {path}\n"
            f"Store disposable task files here. Set TMPDIR, TMP, and TEMP to this path "
            "for commands that create temporary files. Keep deliverables outside it. "
            "Before the final response for completed work, move needed outputs to a permanent "
            "location and wait for all processes and agents that use this directory. Then run:\n"
            f"{helper} ready {data['task']}\n"
            "The Stop hook will remove ready directories from this session. Do not mark ready "
            "when waiting for user input or when files are needed later. "
            f"Use `{helper} list` to inspect older tasks and `{helper} hold TASK_ID` to retain one."
        )
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}
    if event == "Stop":
        session = digest(payload.get("session_id"))
        reports, skipped = [], []
        deadline = time.monotonic() + 20
        for data in store.records():
            if data["session"] != session or data["status"] != "ready":
                continue
            if time.monotonic() > deadline:
                skipped.append("More ready directories remain. Use the cleanup command later.")
                break
            try:
                reports.append(store.clean(data["task"], apply=True))
            except (Refused, OSError) as error:
                skipped.append(str(error))
        messages = []
        if reports:
            directories = len(reports)
            files = sum(report["files"] for report in reports)
            size = sum(report["bytes"] for report in reports)
            noun = "directory" if directories == 1 else "directories"
            message = f"Removed {directories} task {noun}"
            if files:
                noun = "file" if files == 1 else "files"
                message += f" and {files} {noun} ({format_size(size)})"
            messages.append(message + ".")
        if skipped:
            messages.append("Cleanup incomplete.")
            messages.extend(dict.fromkeys(skipped))
        if messages:
            return {"systemMessage": "Task Cleaner: " + " ".join(messages)}
    return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("hook")
    commands.add_parser("list")
    for name in ("ready", "hold", "clean"):
        command = commands.add_parser(name)
        command.add_argument("task")
        if name == "clean":
            command.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        store = Store()
        with store.locked():
            if args.command == "hook":
                result = hook(store, json.load(sys.stdin))
            elif args.command == "list":
                result = list(store.records())
            elif args.command == "clean":
                result = store.clean(args.task, args.apply)
            else:
                result = store.status(args.task, "ready" if args.command == "ready" else "held")
        print(json.dumps(result))
    except (Refused, OSError, ValueError, KeyError, TypeError) as error:
        if args.command == "hook":
            print(json.dumps({"systemMessage": "Task Cleaner kept files: " + str(error)}))
        else:
            print(str(error), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
