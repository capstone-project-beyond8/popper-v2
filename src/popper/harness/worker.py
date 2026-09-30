"""Local Python file-access guard. Not an isolation boundary for hostile native code."""

import json
import os
import sys
from pathlib import Path
from typing import Any


def main() -> None:
    work = Path.cwd().resolve()
    inputs = {Path(p).resolve() for p in json.loads(sys.argv[1])}
    libraries = {Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()}
    if os.name == "nt":
        libraries.add(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts")
    else:
        libraries.update(Path(p) for p in ("/usr/share/fonts", "/etc/fonts", "/usr/lib", "/lib"))
    null = Path(os.devnull).resolve()
    records = {work / name for name in ("code.py", "stdout.txt", "stderr.txt")}

    def path_of(value: Any) -> Path | None:
        if isinstance(value, int) or value is None:
            return None
        return Path(os.fsdecode(value)).resolve()

    def allowed(path: Path, writing: bool = False) -> bool:
        if path == null:
            return True
        if writing:
            return path.is_relative_to(work) and path not in inputs and path not in records
        return (
            path in inputs
            or path.is_relative_to(work)
            or any(path.is_relative_to(root) for root in libraries)
        )

    def check(value: Any, writing: bool = False) -> None:
        path = path_of(value)
        if path is not None and not allowed(path, writing):
            raise PermissionError("file access denied; use mounted inputs and the execution folder")

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "open":
            mode, flags = args[1:3]
            writing = bool((flags or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            check(args[0], writing or (isinstance(mode, str) and any(c in mode for c in "wax+")))
        elif event in {"os.listdir", "os.scandir"}:
            check(args[0] or work)
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.truncate", "os.utime"}:
            check(args[0], True)
        elif event in {"os.rename", "os.link", "os.symlink"}:
            check(args[0], True)
            check(args[1], True)
        elif event == "os.chdir":
            check(args[0])
        elif event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.fork"}:
            raise PermissionError("subprocess launch denied; submit a self-contained Python script")

    # Read source before installing the guard; the source is immutable harness input.
    code = (work / "code.py").read_text("utf-8")
    sys.dont_write_bytecode = True
    sys.addaudithook(audit)
    exec(compile(code, str(work / "code.py"), "exec"), {"__name__": "__main__"})


if __name__ == "__main__":
    main()
