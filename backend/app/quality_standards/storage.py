from __future__ import annotations

from pathlib import Path


def store_document(storage_dir: Path, file_hash: str, suffix: str, content: bytes) -> tuple[Path, bool]:
    storage_dir.mkdir(parents=True, exist_ok=True)
    destination = storage_dir / f"{file_hash}{suffix.lower()}"
    try:
        with destination.open("xb") as output:
            output.write(content)
    except FileExistsError:
        return destination, False
    return destination, True


def delete_document(path: Path, storage_dir: Path) -> None:
    root, candidate = _validated_path(path, storage_dir)
    candidate.unlink(missing_ok=True)
    if root.exists() and not any(root.iterdir()):
        root.rmdir()


def restore_document(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def read_document(path: Path, storage_dir: Path) -> bytes:
    _, candidate = _validated_path(path, storage_dir)
    return candidate.read_bytes()


def _validated_path(path: Path, storage_dir: Path) -> tuple[Path, Path]:
    root = storage_dir.resolve()
    candidate = path.resolve()
    if not candidate.is_relative_to(root) or candidate.parent != root:
        raise ValueError("文件路径不在质量标准存储目录中，已拒绝操作")
    return root, candidate
