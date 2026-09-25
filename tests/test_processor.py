"""Unit and integration tests for ULPProcessor."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.processor import ULPProcessor
from src.storage import QueuedFile, storage_manager


def test_full_pipeline():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        chat_id = 99999

        # Create two sample input files with duplicates, valid lines, and errors
        f1_path = tmp_path / "batch1.txt"
        f1_content = (
            "https://site1.com/login:user1:pass1\n"
            "https://site2.com:user2:pass2\n"
            "https://site1.com/login:user1:pass1\n"  # Duplicate in same file
            "invalid_line_no_url:only_two_fields\n"  # Error line
            "https://emptyuser.com::mypass\n"         # Error line
        )
        f1_path.write_text(f1_content, encoding="utf-8")

        f2_path = tmp_path / "batch2.txt"
        f2_content = (
            "https://site2.com:user2:pass2\n"       # Duplicate from f1
            "https://site3.com:8080:user3:pass3\n"
            "https://emptypass.com:user4:\n"        # Error line
        )
        f2_path.write_text(f2_content, encoding="utf-8")

        # Create QueuedFiles
        q1 = storage_manager.add_queued_file(chat_id, f1_path, "batch1.txt", f1_path.stat().st_size, "id1")
        q2 = storage_manager.add_queued_file(chat_id, f2_path, "batch2.txt", f2_path.stat().st_size, "id2")

        queued = storage_manager.get_queued_files(chat_id)
        assert len(queued) == 2

        # Run processor
        proc = ULPProcessor(temp_dir=tmp_path / "temp")
        report = proc.process(chat_id, queued)

        # Assertions
        assert report.total_files == 2
        assert report.total_raw_lines == 8
        assert report.unique_lines == 6  # 2 duplicates removed: site1:user1:pass1 and site2:user2:pass2
        assert report.duplicates_dropped == 2
        assert report.valid_lines == 3   # site1, site2, site3
        assert report.error_lines == 3   # invalid_line_no_url, emptyuser, emptypass

        # Check that original source files were DELETED
        assert not f1_path.exists(), "Source file 1 was not deleted!"
        assert not f2_path.exists(), "Source file 2 was not deleted!"
        assert report.source_files_deleted == 2

        # Check clean file contents
        assert report.clean_file_path is not None and report.clean_file_path.exists()
        clean_lines = report.clean_file_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(clean_lines) == 3
        assert "https://site1.com/login:user1:pass1" in clean_lines
        assert "https://site2.com:user2:pass2" in clean_lines
        assert "https://site3.com:8080:user3:pass3" in clean_lines

        # Check errors file contents
        assert report.error_file_path is not None and report.error_file_path.exists()
        err_text = report.error_file_path.read_text(encoding="utf-8")
        assert "TOO_FEW_FIELDS" in err_text or "INVALID_URL" in err_text
        assert "EMPTY_USER" in err_text
        assert "EMPTY_PASSWORD" in err_text

        print("Full pipeline test passed successfully!")


if __name__ == "__main__":
    test_full_pipeline()
