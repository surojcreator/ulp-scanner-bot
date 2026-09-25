"""Parallel high-speed file transfer utility for Telethon.
Spawns multiple parallel MTProto connections to download and upload large files
at maximum multi-threaded speed (bypassing single-connection throttling).
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import logging
import math
import os
from pathlib import Path
from typing import (
    AsyncGenerator,
    Awaitable,
    BinaryIO,
    Callable,
    List,
    Optional,
    Tuple,
    Union,
)

from telethon import TelegramClient, helpers, utils
from telethon.crypto import AuthKey
from telethon.network import MTProtoSender
from telethon.tl.alltlobjects import LAYER
from telethon.tl.functions import InvokeWithLayerRequest
from telethon.tl.functions.auth import (
    ExportAuthorizationRequest,
    ImportAuthorizationRequest,
)
from telethon.tl.functions.upload import (
    GetFileRequest,
    SaveBigFilePartRequest,
    SaveFilePartRequest,
)
from telethon.tl.types import (
    Document,
    InputDocumentFileLocation,
    InputFile,
    InputFileBig,
    InputFileLocation,
    InputPeerPhotoFileLocation,
    InputPhotoFileLocation,
    TypeInputFile,
)

log: logging.Logger = logging.getLogger("telethon.fast")

TypeLocation = Union[
    Document,
    InputDocumentFileLocation,
    InputPeerPhotoFileLocation,
    InputFileLocation,
    InputPhotoFileLocation,
]


class DownloadSender:
    client: TelegramClient
    sender: MTProtoSender
    request: GetFileRequest
    remaining: int
    stride: int

    def __init__(
        self,
        client: TelegramClient,
        sender: MTProtoSender,
        file: TypeLocation,
        offset: int,
        limit: int,
        stride: int,
        count: int,
    ) -> None:
        self.sender = sender
        self.client = client
        self.request = GetFileRequest(file, offset=offset, limit=limit)
        self.stride = stride
        self.remaining = count

    async def next(self) -> Optional[bytes]:
        if self.remaining <= 0:
            return None
        for attempt in range(3):
            try:
                result = await self.client._call(self.sender, self.request)
                if not result or not result.bytes:
                    self.remaining = 0
                    return None
                self.remaining -= 1
                self.request.offset += self.stride
                return result.bytes
            except Exception as e:
                log.warning(f"DownloadSender error (attempt {attempt + 1}/3): {e}")
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))

    def disconnect(self) -> Awaitable[None]:
        return self.sender.disconnect()


class UploadSender:
    client: TelegramClient
    sender: MTProtoSender
    request: Union[SaveFilePartRequest, SaveBigFilePartRequest]
    part_count: int
    stride: int
    previous: Optional[asyncio.Task]
    loop: asyncio.AbstractEventLoop

    def __init__(
        self,
        client: TelegramClient,
        sender: MTProtoSender,
        file_id: int,
        part_count: int,
        big: bool,
        index: int,
        stride: int,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.client = client
        self.sender = sender
        self.part_count = part_count
        if big:
            self.request = SaveBigFilePartRequest(file_id, index, part_count, b"")
        else:
            self.request = SaveFilePartRequest(file_id, index, b"")
        self.stride = stride
        self.previous = None
        self.loop = loop

    async def next(self, data: bytes) -> None:
        if self.previous:
            await self.previous
        self.previous = self.loop.create_task(self._next(data))

    async def _next(self, data: bytes) -> None:
        self.request.bytes = data
        for attempt in range(3):
            try:
                await self.client._call(self.sender, self.request)
                self.request.file_part += self.stride
                return
            except Exception as e:
                log.warning(f"UploadSender error (attempt {attempt + 1}/3): {e}")
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))

    async def disconnect(self) -> None:
        if self.previous:
            await self.previous
        return await self.sender.disconnect()


class ParallelTransferrer:
    client: TelegramClient
    loop: asyncio.AbstractEventLoop
    dc_id: int
    senders: Optional[List[Union[DownloadSender, UploadSender]]]
    auth_key: AuthKey
    upload_ticker: int

    def __init__(self, client: TelegramClient, dc_id: Optional[int] = None) -> None:
        self.client = client
        self.loop = self.client.loop
        self.dc_id = dc_id or self.client.session.dc_id
        self.auth_key = (
            None
            if dc_id and self.client.session.dc_id != dc_id
            else self.client.session.auth_key
        )
        self.senders = None
        self.upload_ticker = 0

    async def _cleanup(self) -> None:
        if self.senders:
            await asyncio.gather(*[sender.disconnect() for sender in self.senders], return_exceptions=True)
        self.senders = None

    @staticmethod
    def _get_connection_count(
        file_size: int, max_count: int = 8, full_size: int = 20 * 1024 * 1024
    ) -> int:
        if file_size <= 1024 * 1024:
            return 1
        if file_size >= full_size:
            return max_count
        return max(2, min(max_count, math.ceil((file_size / full_size) * max_count)))

    async def _init_download(
        self, connections: int, file: TypeLocation, part_count: int, part_size: int
    ) -> None:
        minimum, remainder = divmod(part_count, connections)

        def get_part_count() -> int:
            nonlocal remainder
            if remainder > 0:
                remainder -= 1
                return minimum + 1
            return minimum

        # The first cross-DC sender will export+import auth
        first_count = get_part_count()
        first_sender = await self._create_download_sender(
            file, 0, part_size, connections * part_size, first_count
        )
        if connections > 1:
            other_senders = await asyncio.gather(
                *[
                    self._create_download_sender(
                        file, i, part_size, connections * part_size, get_part_count()
                    )
                    for i in range(1, connections)
                ]
            )
            self.senders = [first_sender, *other_senders]
        else:
            self.senders = [first_sender]

    async def _create_download_sender(
        self, file: TypeLocation, index: int, part_size: int, stride: int, part_count: int
    ) -> DownloadSender:
        return DownloadSender(
            self.client,
            await self._create_sender(),
            file,
            index * part_size,
            part_size,
            stride,
            part_count,
        )

    async def _init_upload(
        self, connections: int, file_id: int, part_count: int, big: bool
    ) -> None:
        first_sender = await self._create_upload_sender(file_id, part_count, big, 0, connections)
        if connections > 1:
            other_senders = await asyncio.gather(
                *[
                    self._create_upload_sender(file_id, part_count, big, i, connections)
                    for i in range(1, connections)
                ]
            )
            self.senders = [first_sender, *other_senders]
        else:
            self.senders = [first_sender]

    async def _create_upload_sender(
        self, file_id: int, part_count: int, big: bool, index: int, stride: int
    ) -> UploadSender:
        return UploadSender(
            self.client,
            await self._create_sender(),
            file_id,
            part_count,
            big,
            index,
            stride,
            loop=self.loop,
        )

    async def _create_sender(self) -> MTProtoSender:
        dc = await self.client._get_dc(self.dc_id)
        sender = MTProtoSender(self.auth_key, loggers=self.client._log)
        await sender.connect(
            self.client._connection(
                dc.ip_address,
                dc.port,
                dc.id,
                loggers=self.client._log,
                proxy=self.client._proxy,
            )
        )
        if not self.auth_key:
            auth = await self.client(ExportAuthorizationRequest(self.dc_id))
            init_req = copy.copy(self.client._init_request)
            init_req.query = ImportAuthorizationRequest(
                id=auth.id, bytes=auth.bytes
            )
            req = InvokeWithLayerRequest(LAYER, init_req)
            await sender.send(req)
            self.auth_key = sender.auth_key
        return sender

    async def init_upload(
        self,
        file_id: int,
        file_size: int,
        part_size_kb: Optional[float] = None,
        connection_count: Optional[int] = None,
    ) -> Tuple[int, int, bool]:
        connection_count = connection_count or self._get_connection_count(file_size)
        if part_size_kb is not None:
            part_size = int(part_size_kb * 1024)
        else:
            part_size = 512 * 1024 if file_size >= 1024 * 1024 else int(utils.get_appropriated_part_size(file_size) * 1024)
        part_count = max(1, (file_size + part_size - 1) // part_size)
        is_large = file_size > 10 * 1024 * 1024
        connection_count = min(connection_count, part_count)
        await self._init_upload(connection_count, file_id, part_count, is_large)
        return part_size, part_count, is_large

    async def upload(self, part: bytes) -> None:
        await self.senders[self.upload_ticker].next(part)
        self.upload_ticker = (self.upload_ticker + 1) % len(self.senders)

    async def finish_upload(self) -> None:
        await self._cleanup()

    async def download(
        self,
        file: TypeLocation,
        file_size: int,
        part_size_kb: Optional[float] = None,
        connection_count: Optional[int] = None,
    ) -> AsyncGenerator[bytes, None]:
        if file_size <= 0:
            return

        if part_size_kb is not None:
            part_size = int(part_size_kb * 1024)
        else:
            part_size = 512 * 1024 if file_size >= 1024 * 1024 else int(utils.get_appropriated_part_size(file_size) * 1024)

        part_count = math.ceil(file_size / part_size)
        connection_count = min(connection_count or self._get_connection_count(file_size), max(1, part_count))
        await self._init_download(connection_count, file, part_count, part_size)

        part = 0
        while part < part_count:
            active_senders = [s for s in self.senders if s.remaining > 0]
            if not active_senders:
                break
            tasks = [self.loop.create_task(s.next()) for s in active_senders]
            for task in tasks:
                data = await task
                if not data:
                    break
                yield data
                part += 1

        await self._cleanup()


def _stream_file(file_obj: BinaryIO, chunk_size=1024 * 512):
    while True:
        data = file_obj.read(chunk_size)
        if not data:
            break
        yield data


async def fast_download_file(
    client: TelegramClient,
    location: TypeLocation,
    out: Union[BinaryIO, Path, str],
    file_size: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> None:
    """Downloads a file using parallel MTProto connections at maximum speed."""
    if file_size is None:
        file_size = getattr(location, "size", 0)

    dc_id, input_location = utils.get_input_location(location)
    downloader = ParallelTransferrer(client, dc_id)

    async def _write_stream(target_io: BinaryIO):
        downloaded = downloader.download(input_location, file_size)
        async for chunk in downloaded:
            target_io.write(chunk)
            if progress_callback and file_size > 0:
                res = progress_callback(target_io.tell(), file_size)
                if inspect.isawaitable(res):
                    await res

    try:
        if isinstance(out, (str, Path)):
            with open(out, "wb") as f:
                await _write_stream(f)
        else:
            await _write_stream(out)
    finally:
        await downloader._cleanup()


async def fast_upload_file(
    client: TelegramClient,
    file_path: Union[Path, str],
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> TypeInputFile:
    """Uploads a file using parallel MTProto connections at maximum speed."""
    file_path = Path(file_path)
    file_size = file_path.stat().st_size
    file_id = helpers.generate_random_long()

    hash_md5 = hashlib.md5()
    uploader = ParallelTransferrer(client)
    part_size, part_count, is_large = await uploader.init_upload(file_id, file_size)

    buffer = bytearray()
    try:
        with open(file_path, "rb") as f:
            for data in _stream_file(f, chunk_size=part_size):
                if progress_callback:
                    res = progress_callback(f.tell(), file_size)
                    if inspect.isawaitable(res):
                        await res
                if not is_large:
                    hash_md5.update(data)
                if len(buffer) == 0 and len(data) == part_size:
                    await uploader.upload(data)
                    continue
                new_len = len(buffer) + len(data)
                if new_len >= part_size:
                    cutoff = part_size - len(buffer)
                    buffer.extend(data[:cutoff])
                    await uploader.upload(bytes(buffer))
                    buffer.clear()
                    buffer.extend(data[cutoff:])
                else:
                    buffer.extend(data)
            if len(buffer) > 0:
                await uploader.upload(bytes(buffer))
    finally:
        await uploader.finish_upload()

    if is_large:
        return InputFileBig(file_id, part_count, file_path.name)
    return InputFile(file_id, part_count, file_path.name, hash_md5.hexdigest())
