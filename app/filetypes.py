"""تشخیصِ نوعِ فایل از پیامِ تلگرام."""
from __future__ import annotations

from dataclasses import dataclass

from aiogram.types import Message

ARCHIVE_EXT = (
    ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".zst",
)
ARCHIVE_MIME = (
    "application/zip",
    "application/x-rar",
    "application/vnd.rar",
    "application/x-7z-compressed",
    "application/x-tar",
    "application/gzip",
    "application/x-bzip2",
    "application/x-xz",
)


@dataclass(slots=True)
class FileInfo:
    kind: str  # document | image | video | audio | archive
    file_id: str
    file_unique_id: str
    name: str | None
    size: int | None
    mime: str | None


def _document_kind(mime: str | None, name: str | None) -> str:
    m = (mime or "").lower()
    n = (name or "").lower()
    if n.endswith(ARCHIVE_EXT) or any(m.startswith(a) for a in ARCHIVE_MIME):
        return "archive"
    if m.startswith("image/"):
        return "image"
    if m.startswith("video/"):
        return "video"
    if m.startswith("audio/"):
        return "audio"
    return "document"


def detect(message: Message) -> FileInfo | None:
    if message.document:
        d = message.document
        return FileInfo(
            _document_kind(d.mime_type, d.file_name),
            d.file_id, d.file_unique_id, d.file_name, d.file_size, d.mime_type,
        )
    if message.photo:
        p = message.photo[-1]
        return FileInfo("image", p.file_id, p.file_unique_id, None, p.file_size, "image/jpeg")
    if message.video:
        v = message.video
        return FileInfo("video", v.file_id, v.file_unique_id, v.file_name, v.file_size, v.mime_type)
    if message.audio:
        a = message.audio
        name = a.file_name or " - ".join(x for x in (a.performer, a.title) if x) or None
        return FileInfo("audio", a.file_id, a.file_unique_id, name, a.file_size, a.mime_type)
    if message.voice:
        v = message.voice
        return FileInfo("audio", v.file_id, v.file_unique_id, None, v.file_size, v.mime_type)
    if message.animation:
        a = message.animation
        return FileInfo("video", a.file_id, a.file_unique_id, a.file_name, a.file_size, a.mime_type)
    if message.video_note:
        v = message.video_note
        return FileInfo("video", v.file_id, v.file_unique_id, None, v.file_size, "video/mp4")
    if message.sticker:
        s = message.sticker
        return FileInfo("image", s.file_id, s.file_unique_id, None, s.file_size, "image/webp")
    return None


def human_size(n: int | None) -> str:
    if not n:
        return "—"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
