"""Per-chat file queue and storage management."""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.config import INCOMING_DIR, OUTPUT_DIR, TEMP_DIR


@dataclass
class QueuedFile:
    file_id: str
    path: Path
    original_name: str
    size_bytes: int
    added_at: float = field(default_factory=time.time)

    @property
    def human_size(self) -> str:
        size = float(self.size_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"


class FileStorageManager:
    """Manages files queued for processing per chat/user."""

    def __init__(self) -> None:
        self._queues: Dict[int, List[QueuedFile]] = {}

    def get_chat_incoming_dir(self, chat_id: int) -> Path:
        chat_dir = INCOMING_DIR / str(chat_id)
        chat_dir.mkdir(parents=True, exist_ok=True)
        return chat_dir

    def get_chat_output_dir(self, chat_id: int) -> Path:
        chat_dir = OUTPUT_DIR / str(chat_id)
        chat_dir.mkdir(parents=True, exist_ok=True)
        return chat_dir

    def get_chat_temp_dir(self, chat_id: int) -> Path:
        chat_dir = TEMP_DIR / str(chat_id)
        chat_dir.mkdir(parents=True, exist_ok=True)
        return chat_dir

    def add_queued_file(
        self,
        chat_id: int,
        path: Path,
        original_name: str,
        size_bytes: int,
        file_id: str
    ) -> QueuedFile:
        queued = QueuedFile(
            file_id=file_id,
            path=path,
            original_name=original_name,
            size_bytes=size_bytes
        )
        if chat_id not in self._queues:
            self._queues[chat_id] = []
        self._queues[chat_id].append(queued)
        return queued

    def get_queued_files(self, chat_id: int) -> List[QueuedFile]:
        """Returns all valid existing files queued for a chat."""
        files = self._queues.get(chat_id, [])
        # Filter out any files that were deleted or missing
        valid = [f for f in files if f.path.exists()]
        self._queues[chat_id] = valid
        return list(valid)

    def get_queue_stats(self, chat_id: int) -> Tuple[int, int, str]:
        """Returns (count, total_bytes, human_size)."""
        files = self.get_queued_files(chat_id)
        count = len(files)
        total_bytes = sum(f.size_bytes for f in files)
        size = float(total_bytes)
        human_size = "0 B"
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024.0:
                human_size = f"{size:.2f} {unit}"
                break
            size /= 1024.0
        return count, total_bytes, human_size

    def clear_queue(self, chat_id: int) -> int:
        """Deletes all queued files for this chat from disk and clears the queue."""
        files = self._queues.pop(chat_id, [])
        deleted = 0
        for f in files:
            try:
                if f.path.exists():
                    f.path.unlink()
                    deleted += 1
            except Exception:
                pass
        
        # Also clean the incoming directory for this chat
        chat_dir = INCOMING_DIR / str(chat_id)
        if chat_dir.exists():
            for item in chat_dir.glob("*"):
                try:
                    if item.is_file():
                        item.unlink()
                        deleted += 1
                except Exception:
                    pass
        return deleted

    def delete_source_files(self, files: List[QueuedFile]) -> int:
        """Deletes specific processed source files from disk."""
        deleted_count = 0
        for f in files:
            try:
                if f.path.exists():
                    f.path.unlink()
                    deleted_count += 1
            except Exception:
                pass
        return deleted_count


# Global singleton instance
storage_manager = FileStorageManager()
