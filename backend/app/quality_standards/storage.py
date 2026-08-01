from __future__ import annotations

from pathlib import Path


def store_document(storage_dir: Path, file_hash: str, suffix: str, content: bytes) -> tuple[Path, bool]:
    storage_dir.mkdir(parents=True, exist_ok=True)
    destination = storage_dir / f"{file_hash}{suffix.lower()}"
    if destination.exists():
        return destination, False
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination, True


def delete_document(path: Path, storage_dir: Path) -> None:
    path.unlink(missing_ok=True)
    if storage_dir.exists() and not any(storage_dir.iterdir()):
        storage_dir.rmdir()
