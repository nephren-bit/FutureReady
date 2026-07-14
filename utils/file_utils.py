"""
utils/file_utils.py

Helper utilities for handling uploaded files:
- extension validation
- size validation
- saving to a temporary location on disk (async, non-blocking)
- cleanup of temporary files after processing

Centralizing this logic avoids duplicating the same validation code across
every router (cv, slide, audio, evaluate).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import aiofiles
from fastapi import HTTPException, UploadFile, status

from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


def validate_extension(file: UploadFile, allowed_extensions: set[str]) -> str:
    """
    Validate that the uploaded file has an allowed extension.

    Args:
        file: The uploaded file.
        allowed_extensions: Set of allowed extensions, e.g. {".pdf"}.

    Returns:
        The lower-cased file extension (including the leading dot).

    Raises:
        HTTPException: 400 if the filename is missing or the extension
            is not in `allowed_extensions`.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is missing a filename.",
        )

    extension = Path(file.filename).suffix.lower()
    if extension not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file extension '{extension}'. "
                f"Allowed extensions: {sorted(allowed_extensions)}"
            ),
        )
    return extension


async def save_upload_file(
    file: UploadFile, extension: str, max_size_bytes: int | None = None
) -> Path:
    """
    Persist an uploaded file to the configured upload directory.

    The file is streamed to disk in chunks and its size is validated while
    streaming, so oversized files are rejected without buffering the whole
    file in memory.

    Args:
        file: The uploaded file.
        extension: The validated file extension (including leading dot).
        max_size_bytes: Maximum allowed size in bytes. Defaults to
            `settings.MAX_FILE_SIZE_BYTES`; pass `settings.MAX_VIDEO_SIZE_BYTES`
            for video uploads, which are legitimately much larger.

    Returns:
        Path to the saved file on disk.

    Raises:
        HTTPException: 413 if the file exceeds the size limit.
    """
    size_limit = max_size_bytes if max_size_bytes is not None else settings.MAX_FILE_SIZE_BYTES
    size_limit_mb = round(size_limit / (1024 * 1024), 1)

    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = settings.UPLOAD_DIR / f"{uuid.uuid4().hex}{extension}"

    total_size = 0
    chunk_size = 1024 * 1024  # 1 MB

    try:
        async with aiofiles.open(destination, "wb") as out_file:
            while chunk := await file.read(chunk_size):
                total_size += len(chunk)
                if total_size > size_limit:
                    await out_file.close()
                    cleanup_file(destination)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds the maximum allowed size of {size_limit_mb} MB.",
                    )
                await out_file.write(chunk)
    finally:
        await file.close()

    logger.info("Saved upload '%s' (%d bytes) to %s", file.filename, total_size, destination)
    return destination


def cleanup_file(path: Path) -> None:
    """
    Delete a file from disk if it exists, ignoring any errors.

    Used to clean up the uploads/ directory after processing completes
    (successfully or not) so temporary files never accumulate.

    Args:
        path: Path to the file to delete.
    """
    try:
        if path.exists():
            path.unlink()
            logger.info("Cleaned up temporary file %s", path)
    except OSError as exc:
        logger.warning("Failed to clean up file %s: %s", path, exc)
