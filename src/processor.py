"""Stream-based merger, deduplicator, file-cleaner, and ULP error-checker."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Generator, Iterator, List, Optional, Set, Tuple

from src.config import CHUNK_SIZE_LINES, TEMP_DIR
from src.storage import QueuedFile, storage_manager
from src.validator import ValidationResult, validate_ulp_line


@dataclass
class ProcessingReport:
    total_files: int
    source_filenames: List[str]
    total_raw_lines: int
    unique_lines: int
    duplicates_dropped: int
    valid_lines: int
    error_lines: int
    error_breakdown: Dict[str, int]
    clean_file_path: Optional[Path] = None
    clean_file_size: int = 0
    error_file_path: Optional[Path] = None
    error_file_size: int = 0
    duration_seconds: float = 0.0
    source_files_deleted: int = 0

    @property
    def human_clean_size(self) -> str:
        size = float(self.clean_file_size)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"

    @property
    def human_error_size(self) -> str:
        size = float(self.error_file_size)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"


def _read_lines_from_file(file_path: Path) -> Generator[str, None, None]:
    """Yields lines from a text file or inside a zip archive."""
    if not file_path.exists():
        return

    # Check if the file is a zip archive
    if zipfile.is_zipfile(file_path):
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                for member in zf.infolist():
                    if member.is_dir():
                        continue
                    # Read text-like files inside zip
                    try:
                        with zf.open(member, "r") as entry_file:
                            text_stream = io.TextIOWrapper(
                                entry_file,
                                encoding="utf-8",
                                errors="replace",
                                newline=None
                            )
                            for line in text_stream:
                                yield line
                    except Exception:
                        continue
            return
        except Exception:
            pass

    # Standard plain text file
    with open(file_path, "r", encoding="utf-8", errors="replace", newline=None) as f:
        for line in f:
            yield line


class ULPProcessor:
    """Orchestrates:
    1. Merge lines from all queued files.
    2. Deduplicate lines.
    3. Delete original files from disk.
    4. Validate and check lines for errors (url:user:password).
    """

    def __init__(self, temp_dir: Path = TEMP_DIR) -> None:
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def process(
        self,
        chat_id: int,
        files: List[QueuedFile],
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> ProcessingReport:
        start_time = time.time()
        source_names = [f.original_name for f in files]
        total_files = len(files)

        if not files:
            return ProcessingReport(
                total_files=0,
                source_filenames=[],
                total_raw_lines=0,
                unique_lines=0,
                duplicates_dropped=0,
                valid_lines=0,
                error_lines=0,
                error_breakdown={},
                duration_seconds=0.0
            )

        chat_out_dir = storage_manager.get_chat_output_dir(chat_id)
        chat_temp_dir = storage_manager.get_chat_temp_dir(chat_id)
        timestamp = int(time.time())

        temp_merged_path = chat_temp_dir / f"merged_raw_{timestamp}.tmp"
        clean_out_path = chat_out_dir / f"cleaned_ulp_{timestamp}.txt"
        errors_out_path = chat_out_dir / f"errors_ulp_{timestamp}.txt"

        # -------------------------------------------------------------
        # STEP 1 & 2: STREAMING MERGE & DEDUPLICATION
        # -------------------------------------------------------------
        if progress_callback:
            progress_callback("🔄 Step 1/3: Merging files and deduplicating lines...")

        total_raw_lines = 0
        seen_hashes: Set[int] = set()
        unique_lines = 0

        # We use a fast 64-bit hash (blake2b 8-byte digest) for memory-efficient deduplication
        with open(temp_merged_path, "w", encoding="utf-8", errors="replace") as out_merged:
            for file_idx, qfile in enumerate(files, 1):
                if progress_callback and (file_idx == 1 or file_idx % 3 == 0 or file_idx == total_files):
                    progress_callback(
                        f"🔄 Step 1/3: Reading and deduplicating file {file_idx}/{total_files} ({qfile.original_name})..."
                    )
                
                for line in _read_lines_from_file(qfile.path):
                    total_raw_lines += 1
                    clean_line = line.strip()
                    if not clean_line:
                        continue
                    
                    # Compute 64-bit hash
                    h = int.from_bytes(hashlib.blake2b(clean_line.encode("utf-8", "replace"), digest_size=8).digest(), "little")
                    if h in seen_hashes:
                        continue
                    seen_hashes.add(h)
                    unique_lines += 1
                    out_merged.write(clean_line + "\n")

        duplicates_dropped = total_raw_lines - unique_lines
        # Free hash set memory
        del seen_hashes

        # -------------------------------------------------------------
        # STEP 3: DELETE THE ORIGINAL FILES FROM DISK
        # "and deltes duplictes and the files them self"
        # -------------------------------------------------------------
        if progress_callback:
            progress_callback("🗑 Step 2/3: Cleaning up original source files...")

        deleted_count = storage_manager.delete_source_files(files)
        # Also clear the chat's queue in the storage manager
        storage_manager.clear_queue(chat_id)

        # -------------------------------------------------------------
        # STEP 4: ERROR CHECKING FOR URL:USER:PASSWORD
        # "and then cheches for errors"
        # -------------------------------------------------------------
        if progress_callback:
            progress_callback(f"🔍 Step 3/3: Checking {unique_lines:,} lines for syntax & format errors...")

        valid_lines = 0
        error_lines = 0
        error_breakdown: Dict[str, int] = {}

        has_clean_lines = False
        has_error_lines = False

        with open(temp_merged_path, "r", encoding="utf-8", errors="replace") as in_merged, \
             open(clean_out_path, "w", encoding="utf-8") as out_clean, \
             open(errors_out_path, "w", encoding="utf-8") as out_err:

            line_number = 0
            for line in in_merged:
                line_number += 1
                raw = line.rstrip("\r\n")
                if not raw:
                    continue

                res: ValidationResult = validate_ulp_line(raw)
                if res.is_valid:
                    valid_lines += 1
                    out_clean.write(res.formatted_line() + "\n")
                    has_clean_lines = True
                else:
                    error_lines += 1
                    err_code = res.error_code or "UNKNOWN_ERROR"
                    error_breakdown[err_code] = error_breakdown.get(err_code, 0) + 1
                    out_err.write(f"[Line {line_number}] [{err_code}] {res.error_detail} -> {raw}\n")
                    has_error_lines = True

                if progress_callback and line_number % 250000 == 0:
                    progress_callback(f"🔍 Validated {line_number:,}/{unique_lines:,} lines ({valid_lines:,} valid, {error_lines:,} errors)...")

        # Cleanup temp merged file
        try:
            if temp_merged_path.exists():
                temp_merged_path.unlink()
        except Exception:
            pass

        duration = round(time.time() - start_time, 2)

        # Finalize file paths
        final_clean_path: Optional[Path] = clean_out_path if has_clean_lines and clean_out_path.exists() else None
        clean_size = final_clean_path.stat().st_size if final_clean_path else 0

        final_err_path: Optional[Path] = errors_out_path if has_error_lines and errors_out_path.exists() else None
        error_size = final_err_path.stat().st_size if final_err_path else 0

        # Remove empty output files if no lines
        if not has_clean_lines and clean_out_path.exists():
            clean_out_path.unlink(missing_ok=True)
        if not has_error_lines and errors_out_path.exists():
            errors_out_path.unlink(missing_ok=True)

        return ProcessingReport(
            total_files=total_files,
            source_filenames=source_names,
            total_raw_lines=total_raw_lines,
            unique_lines=unique_lines,
            duplicates_dropped=duplicates_dropped,
            valid_lines=valid_lines,
            error_lines=error_lines,
            error_breakdown=error_breakdown,
            clean_file_path=final_clean_path,
            clean_file_size=clean_size,
            error_file_path=final_err_path,
            error_file_size=error_size,
            duration_seconds=duration,
            source_files_deleted=deleted_count
        )


# Global singleton instance
processor = ULPProcessor()
