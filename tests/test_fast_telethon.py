"""Tests for fast_telethon parallel transfer module."""

import io
from pathlib import Path
import pytest
from src.fast_telethon import ParallelTransferrer, _stream_file


def test_get_connection_count():
    # Small files (<= 1MB) use 1 connection
    assert ParallelTransferrer._get_connection_count(500 * 1024) == 1
    assert ParallelTransferrer._get_connection_count(1024 * 1024) == 1

    # Medium files scale
    mid_conn = ParallelTransferrer._get_connection_count(5 * 1024 * 1024)
    assert 2 <= mid_conn <= 8

    # Big files (>= 20MB) max out connections
    assert ParallelTransferrer._get_connection_count(25 * 1024 * 1024) == 8
    assert ParallelTransferrer._get_connection_count(500 * 1024 * 1024) == 8


def test_stream_file():
    data = b"abcdefghijklmnopqrstuvwxyz" * 100
    bio = io.BytesIO(data)
    chunks = list(_stream_file(bio, chunk_size=64))

    assert len(chunks) > 1
    assert b"".join(chunks) == data
