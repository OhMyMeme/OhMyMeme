"""图片导入应用服务。"""

import hashlib
import io
import os
import sqlite3
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image

from .config import _IMPORT_MAX_BYTES, _IMPORT_MAX_PX


class MemeRepository(Protocol):
    def get_by_hash(self, file_hash: str) -> dict | None: ...

    def add_meme(
        self,
        filename: str,
        file_hash: str,
        width: int,
        height: int,
        file_size: int,
        mime_type: str,
        original_name: str,
        stego_of_hash: str | None = None,
        from_stego: int = 0,
    ) -> int: ...

    def delete_meme(self, meme_id: int) -> None: ...


@dataclass(frozen=True, slots=True)
class ImportBytes:
    data: bytes
    original_name: str


@dataclass(frozen=True, slots=True)
class ImportPath:
    path: Path
    original_name: str


ImportRequest = ImportBytes | ImportPath


@dataclass(frozen=True, slots=True)
class ImportResult:
    imported_ids: tuple[int, ...]
    rejected: int


@dataclass(frozen=True, slots=True)
class _ValidatedImage:
    data: bytes
    extension: str
    width: int
    height: int
    file_hash: str
    original_name: str
    from_stego: int


_MAGIC_EXTENSIONS = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"BM", ".bmp"),
)


def _magic_extension(data: bytes) -> str:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    for magic, extension in _MAGIC_EXTENSIONS:
        if data.startswith(magic):
            return extension
    return ""


class ImageImportService:
    """原子接收图片并同步缓存、数据库和 manifest。"""

    def __init__(
        self,
        db: MemeRepository,
        cache_dir: Path,
        build_manifest: Callable[[], None],
        stego_decoder: Callable[[Path], Path | None] | None = None,
    ) -> None:
        self._db = db
        self._cache_dir = cache_dir
        self._build_manifest = build_manifest
        self._stego_decoder = stego_decoder

    def import_path(self, request: ImportPath) -> ImportResult:
        return self.import_batch((request,))

    def import_bytes(self, request: ImportBytes) -> ImportResult:
        return self.import_batch((request,))

    def register_existing_path(self, request: ImportPath) -> ImportResult:
        validated = self._validate(request)
        if validated is None:
            return ImportResult((), 1)
        if self._db.get_by_hash(validated.file_hash) is not None:
            return ImportResult((), 0)
        try:
            meme_id = self._db.add_meme(
                filename=request.path.name,
                file_hash=validated.file_hash,
                width=validated.width,
                height=validated.height,
                file_size=len(validated.data),
                mime_type=f"image/{validated.extension[1:]}",
                original_name=validated.original_name,
                from_stego=validated.from_stego,
            )
        except (OSError, RuntimeError, sqlite3.Error):
            raise
        return ImportResult((meme_id,), 0)

    def import_batch(self, requests: Sequence[ImportRequest]) -> ImportResult:
        created_paths: list[Path] = []
        created_ids: list[int] = []
        imported_ids: list[int] = []
        rejected = 0
        try:
            for request in requests:
                validated = self._validate(request)
                if validated is None:
                    rejected += 1
                    continue
                existing = self._db.get_by_hash(validated.file_hash)
                if existing is not None:
                    continue
                destination = self._cache_dir / (
                    f"{validated.file_hash[:16]}{validated.extension}"
                )
                created = not destination.exists()
                if created:
                    self._install(destination, validated.data)
                    created_paths.append(destination)
                meme_id = self._db.add_meme(
                    filename=destination.name,
                    file_hash=validated.file_hash,
                    width=validated.width,
                    height=validated.height,
                    file_size=len(validated.data),
                    mime_type=f"image/{validated.extension[1:]}",
                    original_name=validated.original_name,
                    from_stego=validated.from_stego,
                )
                created_ids.append(meme_id)
                imported_ids.append(meme_id)
            if imported_ids:
                self._build_manifest()
        except (OSError, RuntimeError, sqlite3.Error):
            self._compensate(created_ids, created_paths)
            raise
        return ImportResult(tuple(imported_ids), rejected)

    def _validate(self, request: ImportRequest) -> _ValidatedImage | None:
        match request:
            case ImportBytes(data=data, original_name=original_name):
                return self._validate_data(data, original_name)
            case ImportPath(path=path, original_name=original_name):
                return self._validate_path(path, original_name)

    def _validate_path(self, path: Path, original_name: str) -> _ValidatedImage | None:
        try:
            data = path.read_bytes()
        except OSError:
            return None
        is_stego = _magic_extension(data) == ".gif" and b"STG3" in data
        if self._stego_decoder is None or not is_stego:
            return self._validate_data(data, original_name)
        decoded = self._stego_decoder(path)
        if decoded is None:
            return self._validate_data(data, original_name)
        try:
            restored = decoded.read_bytes()
        finally:
            try:
                decoded.unlink()
            except OSError:
                pass
        validated = self._validate_data(restored, original_name)
        if validated is None:
            return None
        return _ValidatedImage(
            validated.data,
            validated.extension,
            validated.width,
            validated.height,
            validated.file_hash,
            validated.original_name,
            1,
        )

    def _validate_data(self, data: bytes, original_name: str) -> _ValidatedImage | None:
        extension = _magic_extension(data)
        if not extension or len(data) > _IMPORT_MAX_BYTES:
            return None
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
        except (OSError, SyntaxError):
            return None
        if width <= 0 or height <= 0 or max(width, height) > _IMPORT_MAX_PX:
            return None
        return _ValidatedImage(
            data,
            extension,
            width,
            height,
            hashlib.sha256(data).hexdigest(),
            Path(original_name).stem,
            0,
        )

    def _install(self, destination: Path, data: bytes) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".import-", suffix=".tmp", dir=destination.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, destination)
        except OSError:
            temporary_path.unlink(missing_ok=True)
            raise

    def _compensate(
        self, created_ids: Sequence[int], created_paths: Sequence[Path]
    ) -> None:
        for meme_id in reversed(created_ids):
            self._db.delete_meme(meme_id)
        for path in reversed(created_paths):
            path.unlink(missing_ok=True)
