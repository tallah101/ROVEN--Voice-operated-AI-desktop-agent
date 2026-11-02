"""Create reports and documents: Markdown, Word (.docx), PDF (via installed Office), Excel."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from security.action_validator import safe_user_path

_SAFE_NAME = re.compile(r'[\\/:*?"<>|]+')


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    for i in range(2, 1000):
        cand = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not cand.exists():
            return cand
    raise FileExistsError(str(p))


def _add_runs(paragraph, text: str) -> None:
    for part in re.split(r"(\*\*[^*]+\*\*)", text):
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            paragraph.add_run(part[2:-2]).bold = True
        elif part:
            paragraph.add_run(part)


def markdown_to_docx(markdown: str, path: Path, title: str | None = None) -> Path:
    import docx
    doc = docx.Document()
    if title:
        doc.add_heading(title, level=0)
    table_rows: list[list[str]] = []

    def flush_table():
        if not table_rows:
            return
        cols = max(len(r) for r in table_rows)
        table = doc.add_table(rows=len(table_rows), cols=cols)
        table.style = "Table Grid"
        for i, row in enumerate(table_rows):
            for j, cell in enumerate(row):
                table.cell(i, j).text = cell
                if i == 0:
                    for run in table.cell(i, j).paragraphs[0].runs:
                        run.bold = True
        table_rows.clear()

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                table_rows.append(cells)
            continue
        flush_table()
        if not stripped:
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", stripped)
        if m:
            doc.add_heading(m.group(2), level=len(m.group(1)))
        elif re.match(r"^[-*•]\s+", stripped):
            _add_runs(doc.add_paragraph(style="List Bullet"), re.sub(r"^[-*•]\s+", "", stripped))
        elif re.match(r"^\d+[.)]\s+", stripped):
            _add_runs(doc.add_paragraph(style="List Number"), re.sub(r"^\d+[.)]\s+", "", stripped))
        else:
            _add_runs(doc.add_paragraph(), stripped)
    flush_table()
    doc.save(str(path))
    return path


def convert_to_pdf(path: str) -> dict:
    """Uses installed Microsoft Office through COM (Word/PowerPoint/Excel 'Export as PDF')."""
    import pythoncom
    import win32com.client
    src = safe_user_path(path)
    dest = unique_path(src.with_suffix(".pdf"))
    suffix = src.suffix.lower()
    pythoncom.CoInitialize()
    try:
        if suffix in (".docx", ".doc", ".rtf", ".txt", ".md"):
            app = win32com.client.DispatchEx("Word.Application")
            app.Visible = False
            try:
                d = app.Documents.Open(str(src), ReadOnly=True)
                d.ExportAsFixedFormat(str(dest), 17)          # wdExportFormatPDF
                d.Close(False)
            finally:
                app.Quit()
        elif suffix in (".pptx", ".ppt"):
            app = win32com.client.DispatchEx("PowerPoint.Application")
            try:
                pres = app.Presentations.Open(str(src), WithWindow=False)
                pres.SaveAs(str(dest), 32)                   # ppSaveAsPDF
                pres.Close()
            finally:
                app.Quit()
        elif suffix in (".xlsx", ".xls", ".csv"):
            app = win32com.client.DispatchEx("Excel.Application")
            app.Visible = False
            try:
                wb = app.Workbooks.Open(str(src), ReadOnly=True)
                wb.ExportAsFixedFormat(0, str(dest))         # xlTypePDF
                wb.Close(False)
            finally:
                app.Quit()
        else:
            raise ValueError(f"Can't convert {suffix} to PDF.")
    except Exception as exc:
        if "Invalid class string" in str(exc):
            raise RuntimeError("Microsoft Office isn't installed, so PDF conversion isn't available.") from exc
        raise
    finally:
        pythoncom.CoUninitialize()
    return {"pdf": str(dest), "verified": dest.exists()}


def save_document(title: str, content: str, folder: str = "~/Documents/ROVEN Reports", format: str = "docx") -> dict:
    out_dir = safe_user_path(folder)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _SAFE_NAME.sub("-", title).strip() or "ROVEN report"
    if format == "md":
        dest = unique_path(out_dir / f"{stem}.md")
        dest.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
    else:
        dest = markdown_to_docx(content, unique_path(out_dir / f"{stem}.docx"), title)
        if format == "pdf":
            pdf = convert_to_pdf(str(dest))
            return {"saved": pdf["pdf"], "also_saved": str(dest), "verified": pdf["verified"]}
    return {"saved": str(dest), "verified": dest.exists(), "created": datetime.now().strftime("%H:%M")}


def create_spreadsheet(path: str, sheets: dict) -> dict:
    """sheets: {"Sheet name": [[header...], [row...], ...]}"""
    import openpyxl
    from openpyxl.styles import Font
    dest = safe_user_path(path)
    if dest.suffix.lower() != ".xlsx":
        dest = dest.with_suffix(".xlsx")
    dest = unique_path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(_SAFE_NAME.sub("-", name)[:31] or "Sheet")
        for row in rows:
            ws.append(row)
        if rows:
            for cell in ws[1]:
                cell.font = Font(bold=True)
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(60, max(10, width + 2))
    wb.save(str(dest))
    return {"saved": str(dest), "sheets": list(sheets), "verified": dest.exists()}
