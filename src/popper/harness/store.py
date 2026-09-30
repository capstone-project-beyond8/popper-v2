"""Write-once run directory."""

import json
import secrets
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path


class RunStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def create(cls, runs_dir: Path, brief: Path, data: Path) -> "RunStore":
        run_id = f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        store = cls(runs_dir / run_id)
        store.root.mkdir(parents=True)
        shutil.copyfile(brief, store.root / "brief.md")
        (store.root / "data").mkdir()
        shutil.copyfile(data, store.root / "data" / "raw.csv")
        (store.root / "data" / "raw.csv").chmod(stat.S_IREAD)
        return store

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def write_text(self, rel: str, text: str) -> Path:
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as f:
            f.write(text)
        return target

    def write_json(self, rel: str, obj: object) -> Path:
        return self.write_text(rel, json.dumps(obj, indent=2, default=str))
