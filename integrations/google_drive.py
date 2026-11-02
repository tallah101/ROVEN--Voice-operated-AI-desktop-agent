"""Google Drive (read-only): search, read (Docs/Sheets/Slides exported to text; PDFs/Office parsed), download."""
from __future__ import annotations

from pathlib import Path

from config import APP_DIR
from integrations.base import RestClient

EXPORTS = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
    "application/vnd.google-apps.presentation": ("text/plain", ".txt"),
}
OFFICE_EXPORTS = {
    "application/vnd.google-apps.document": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}
FIELDS = "id,name,mimeType,modifiedTime,size,webViewLink,owners(displayName)"


def drive_query(text: str) -> str:
    esc = text.replace("\\", "\\\\").replace("'", "\\'")
    return f"(name contains '{esc}' or fullText contains '{esc}') and trashed = false"


class GoogleDrive:
    def __init__(self, auth, http: RestClient | None = None) -> None:
        self.http = http or RestClient("Google Drive", "https://www.googleapis.com/drive/v3/", auth.session)

    def search(self, query: str, max_results: int = 10) -> dict:
        data = self.http.request("GET", "files", params={"q": drive_query(query), "pageSize": max_results,
                                                         "orderBy": "modifiedTime desc", "fields": f"files({FIELDS})"})
        return {"query": query, "files": data.get("files", [])}

    def _meta(self, file_id: str) -> dict:
        return self.http.request("GET", f"files/{file_id}", params={"fields": FIELDS})

    def read(self, file_id: str, max_chars: int = 15000) -> dict:
        from automation.file_manager import extract_text
        meta = self._meta(file_id)
        mime = meta["mimeType"]
        if mime in EXPORTS:
            export_mime, _ = EXPORTS[mime]
            text = self.http.request("GET", f"files/{file_id}/export", params={"mimeType": export_mime}, raw=True).text
        else:
            if int(meta.get("size") or 0) > 30 * 1024 * 1024:
                raise ValueError("File is larger than 30 MB; download it instead.")
            cache = APP_DIR / "cache"
            cache.mkdir(parents=True, exist_ok=True)
            tmp = cache / f"drive_{file_id}{Path(meta['name']).suffix}"
            tmp.write_bytes(self.http.request("GET", f"files/{file_id}", params={"alt": "media"}, raw=True).content)
            try:
                text = extract_text(tmp)
            finally:
                tmp.unlink(missing_ok=True)
        return {"name": meta["name"], "link": meta.get("webViewLink"), "characters": len(text),
                "truncated": len(text) > max_chars, "text": text[:max_chars]}

    def download(self, file_id: str, folder: str) -> dict:
        from automation.documents import unique_path
        from security.action_validator import safe_user_path
        meta = self._meta(file_id)
        dest_dir = safe_user_path(folder)
        dest_dir.mkdir(parents=True, exist_ok=True)
        if meta["mimeType"] in OFFICE_EXPORTS:
            export_mime, suffix = OFFICE_EXPORTS[meta["mimeType"]]
            resp = self.http.request("GET", f"files/{file_id}/export", params={"mimeType": export_mime}, raw=True)
            dest = unique_path(dest_dir / (meta["name"] + suffix))
        else:
            resp = self.http.request("GET", f"files/{file_id}", params={"alt": "media"}, raw=True)
            dest = unique_path(dest_dir / meta["name"])
        dest.write_bytes(resp.content)
        return {"saved": str(dest), "verified": dest.exists()}
