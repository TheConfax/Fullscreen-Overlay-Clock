"""config.json on disk: read, atomic write, and live reload of edits made by others."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QFileSystemWatcher, pyqtSignal

from .. import CONFIG_VERSION
from ..models.config import Config
from .paths import config_path


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ConfigStore(QObject):
    #: The new Config, when someone other than us changes the file.
    externally_changed = pyqtSignal(object)

    def __init__(self, path: Path | None = None) -> None:
        super().__init__()
        self._path = path or config_path()
        self._last_written_hash: str | None = None
        self._newer_config = False
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._watcher.directoryChanged.connect(self._on_dir_changed)
        self._watcher.addPath(str(self._path.parent))  # to see the file (re)created

    @property
    def path(self) -> Path:
        return self._path

    @property
    def newer_config(self) -> bool:
        """The file was written by a newer version of the app. From then on nothing is saved:
        rewriting it would drop the fields this version doesn't know."""
        return self._newer_config

    def load(self) -> Config:
        """The config on disk, or the defaults (written out only if the file is missing)."""
        config = Config.default()
        try:
            raw = self._path.read_bytes()
            self._last_written_hash = _hash(raw)
            config = Config.from_dict(json.loads(raw.decode("utf-8-sig")))  # BOM or not
            self._newer_config = config.version > CONFIG_VERSION
        except FileNotFoundError:
            self.save(config)  # first run ever
        except (OSError, ValueError):
            pass  # unreadable: run on defaults, leave the file as it is
        self._ensure_watched()
        return config

    def save(self, config: Config) -> None:
        """Atomic write. Never raises: a file that stays locked waits for the next save."""
        if self._newer_config:
            return
        data = json.dumps(config.to_dict(), indent=2).encode("utf-8")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        try:
            tmp.write_bytes(data)
            for _ in range(8):
                try:
                    os.replace(tmp, self._path)
                    self._last_written_hash = _hash(data)
                    break
                except PermissionError:
                    time.sleep(0.025)
        except OSError:
            pass
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        self._ensure_watched()

    def _ensure_watched(self) -> None:
        if self._path.exists() and str(self._path) not in self._watcher.files():
            self._watcher.addPath(str(self._path))

    def _on_dir_changed(self, _path: str) -> None:
        # An editor that deletes and recreates the file only reports the folder.
        if self._path.exists():
            self._on_file_changed(str(self._path))

    def _on_file_changed(self, _path: str) -> None:
        self._ensure_watched()  # editors often replace the file, which drops the watch
        try:
            raw = self._path.read_bytes()
        except (OSError, FileNotFoundError):
            return
        if _hash(raw) == self._last_written_hash:
            return  # our own write
        try:
            config = Config.from_dict(json.loads(raw.decode("utf-8-sig")))
        except ValueError:
            config = Config.default()
        self._newer_config = config.version > CONFIG_VERSION
        self._last_written_hash = _hash(raw)
        self.externally_changed.emit(config)
