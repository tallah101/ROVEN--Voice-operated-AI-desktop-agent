"""Find, open, read, create, move and rename files inside the user's home folder.
No permanent deletion: removal goes to the Recycle Bin and always needs confirmation."""
from __future__ import annotations

import os
import time
from pathlib import Path

from core.text_match import match_score
from security.action_validator import safe_user_path

SKIP_DIRS = {"node_modules", ".git", "__pycache__", "appdata", ".venv", "venv", "$recycle.bin"}
MAX_SCAN = 60000


def _default_roots() -> list[Path]:
    home = Path.home()
    names = ["Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music"]
    roots = [home / n for n in names] + [home / "OneDrive" / n for n in names]
    return [r for r in roots if r.exists()]


def find_files(query: str = "", extensions: list[str] | None = None, modified_within_days: float | None = None,
               folder: str | None = None, limit: int = 15) -> dict:
    roots = [safe_user_path(folder)] if folder else _default_roots()
    exts = {e.lower() if e.startswith(".") else "." + e.lower() for e in (extensions or [])}
    cutoff = time.time() - modified_within_days * 86400 if modified_within_days else None
    hits, scanned = [], 0
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                scanned += 1
                if scanned > MAX_SCAN:
                    break
                p = Path(dirpath) / fn
                if exts and p.suffix.lower() not in exts:
                    continue
                try:
                    mtime = p.stat().st_mtime
                except OSError:
                    continue
                if cutoff and mtime < cutoff:
                    continue
                score = max(match_score(query, p.stem), match_score(query, fn)) if query else 1.0
                if score >= 0.5:
                    hits.append((score, mtime, p))
    hits.sort(key=lambda h: (round(h[0], 2), h[1]), reverse=True)
    return {"results": [{"path": str(p), "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(m))}
                        for _, m, p in hits[:limit]],
            "scanned_files": min(scanned, MAX_SCAN)}


def open_path(path: str) -> dict:
    p = safe_user_path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    os.startfile(str(p))  # type: ignore[attr-defined]
    return {"opened": str(p)}


def read_document(path: str, max_chars: int = 15000) -> dict:
    p = safe_user_path(path)
    text = extract_text(p)
    return {"path": str(p), "characters": len(text), "truncated": len(text) > max_chars, "text": text[:max_chars]}


def extract_text(p: Path) -> str:
    """Text from a document. Callers are responsible for path checks."""
    suffix = p.suffix.lower()
    if suffix in (".txt", ".md", ".csv", ".json", ".log", ".py", ".html", ".xml"):
        text = p.read_text(encoding="utf-8", errors="replace")
    elif suffix == ".pdf":
        from pypdf import PdfReader
        text = "\n".join((page.extract_text() or "") for page in PdfReader(str(p)).pages)
    elif suffix == ".docx":
        import docx
        text = "\n".join(par.text for par in docx.Document(str(p)).paragraphs)
    elif suffix == ".xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(str(p), read_only=True, data_only=True)
        rows = []
        for ws in wb.worksheets:
            rows.append(f"# Sheet: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                rows.append("\t".join("" if v is None else str(v) for v in row))
        text = "\n".join(rows)
    elif suffix == ".pptx":
        from pptx import Presentation
        parts = []
        for i, slide in enumerate(Presentation(str(p)).slides, 1):
            parts.append(f"# Slide {i}")
            parts += [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame]
        text = "\n".join(parts)
    else:
        raise ValueError(f"Reading {suffix} files is not supported.")
    return text


def create_folder(path: str) -> dict:
    p = safe_user_path(path)
    p.mkdir(parents=True, exist_ok=False)
    return {"created": str(p), "verified": p.is_dir()}


def move_path(path: str, destination_folder: str) -> dict:
    src, dst_dir = safe_user_path(path), safe_user_path(destination_folder)
    dst = dst_dir / src.name
    if dst.exists():
        raise FileExistsError(f"{dst} already exists; not overwriting.")
    dst_dir.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return {"moved_to": str(dst), "verified": dst.exists() and not src.exists()}


def rename_path(path: str, new_name: str) -> dict:
    src = safe_user_path(path)
    if any(c in new_name for c in '\\/:*?"<>|'):
        raise ValueError("The new name contains characters Windows doesn't allow.")
    dst = src.with_name(new_name)
    if dst.exists():
        raise FileExistsError(f"{dst} already exists; not overwriting.")
    src.rename(dst)
    return {"renamed_to": str(dst), "verified": dst.exists()}


def move_to_recycle_bin(path: str) -> dict:
    from send2trash import send2trash
    p = safe_user_path(path)
    send2trash(str(p))
    return {"recycled": str(p), "verified": not p.exists()}
