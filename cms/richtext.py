from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

SCHEMA = "MYCELIA_RICHTEXT"
VERSION = 1
PROFILES = {"compact", "standard", "document"}
ALLOWED_MARKS = {"bold", "italic", "underline", "strike", "code"}
ALLOWED_TONES = {"accent", "muted", "warning"}
ALLOWED_SIZES = {"small", "large"}
ALLOWED_ALIGNS = {"left", "center", "right"}
BLOCKS_BY_PROFILE = {
    "compact": {"paragraph", "quote", "bullet_list", "ordered_list", "code"},
    "standard": {"paragraph", "heading", "quote", "bullet_list", "ordered_list", "code", "divider"},
    "document": {"paragraph", "heading", "quote", "bullet_list", "ordered_list", "code", "divider", "table", "button_link"},
}
MAX_BLOCKS = 1000
MAX_RUNS_PER_BLOCK = 500
MAX_TABLE_ROWS = 100
MAX_TABLE_COLS = 20
MAX_LINK_LEN = 2048
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class RichTextError(ValueError):
    pass


def _clean_text(value: Any, *, max_len: int | None = None) -> str:
    if not isinstance(value, str):
        raise RichTextError("RichText-Text muss eine Zeichenkette sein")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if _CONTROL_RE.search(value):
        raise RichTextError("Nicht erlaubte Steuerzeichen im RichText")
    if max_len is not None and len(value) > max_len:
        raise RichTextError("RichText-Teil ist zu lang")
    return value


def validate_link(href: Any) -> str:
    href = _clean_text(href, max_len=MAX_LINK_LEN).strip()
    if not href:
        raise RichTextError("Leerer Link ist nicht erlaubt")
    if href.startswith("/") and not href.startswith("//"):
        return href
    parsed = urlsplit(href)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise RichTextError("Links dürfen nur relative interne Pfade oder HTTPS-Ziele verwenden")
    if parsed.username or parsed.password:
        raise RichTextError("Links mit eingebetteten Zugangsdaten sind nicht erlaubt")
    return href


def _normalize_marks(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RichTextError("RichText-Marks müssen eine Liste sein")
    out: list[str] = []
    for mark in value:
        if not isinstance(mark, str) or mark not in ALLOWED_MARKS:
            raise RichTextError("Nicht erlaubte Textformatierung")
        if mark not in out:
            out.append(mark)
    return out


def _normalize_run(run: Any) -> dict[str, Any]:
    if not isinstance(run, dict):
        raise RichTextError("Ungültiger RichText-Run")
    out: dict[str, Any] = {
        "text": _clean_text(run.get("text", ""), max_len=100_000),
        "marks": _normalize_marks(run.get("marks", [])),
    }
    link = run.get("link")
    if link is not None:
        out["link"] = validate_link(link)
    tone = run.get("tone")
    if tone is not None:
        if tone not in ALLOWED_TONES:
            raise RichTextError("Nicht erlaubte Textfarbe")
        out["tone"] = tone
    size = run.get("size")
    if size is not None:
        if size not in ALLOWED_SIZES:
            raise RichTextError("Nicht erlaubte Textgröße")
        out["size"] = size
    return out


def _normalize_runs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise RichTextError("RichText-Runs müssen eine Liste sein")
    if len(value) > MAX_RUNS_PER_BLOCK:
        raise RichTextError("Zu viele Textsegmente in einem Block")
    out = [_normalize_run(x) for x in value]
    # Merge adjacent runs with the same formatting to keep the representation canonical.
    merged: list[dict[str, Any]] = []
    for run in out:
        if merged and merged[-1].get("marks") == run.get("marks") and merged[-1].get("link") == run.get("link") and merged[-1].get("tone") == run.get("tone") and merged[-1].get("size") == run.get("size"):
            merged[-1]["text"] += run["text"]
        else:
            merged.append(run)
    return merged or [{"text": "", "marks": []}]


def _normalize_block(block: Any, profile: str) -> dict[str, Any]:
    if not isinstance(block, dict):
        raise RichTextError("Ungültiger RichText-Block")
    kind = block.get("type")
    if not isinstance(kind, str) or kind not in BLOCKS_BY_PROFILE[profile]:
        raise RichTextError("Blocktyp ist in diesem Editorprofil nicht erlaubt")

    if kind in {"paragraph", "quote"}:
        out = {"type": kind, "runs": _normalize_runs(block.get("runs", []))}
        align = block.get("align")
        if align is not None:
            if align not in ALLOWED_ALIGNS:
                raise RichTextError("Nicht erlaubte Textausrichtung")
            out["align"] = align
        return out
    if kind == "heading":
        level = block.get("level")
        if level not in {2, 3}:
            raise RichTextError("Nur Überschrift 2 und 3 sind erlaubt")
        out = {"type": kind, "level": level, "runs": _normalize_runs(block.get("runs", []))}
        align = block.get("align")
        if align is not None:
            if align not in ALLOWED_ALIGNS:
                raise RichTextError("Nicht erlaubte Textausrichtung")
            out["align"] = align
        return out
    if kind in {"bullet_list", "ordered_list"}:
        items = block.get("items")
        if not isinstance(items, list) or len(items) > 200:
            raise RichTextError("Ungültige oder zu lange Liste")
        return {"type": kind, "items": [_normalize_runs(item) for item in items]}
    if kind == "code":
        language = block.get("language", "text")
        if language not in {"text", "cpp", "python", "javascript", "json", "html", "css", "bash", "powershell"}:
            raise RichTextError("Nicht erlaubte Code-Sprache")
        return {"type": kind, "language": language, "text": _clean_text(block.get("text", ""), max_len=100_000)}
    if kind == "divider":
        return {"type": kind}
    if kind == "button_link":
        return {
            "type": kind,
            "text": _clean_text(block.get("text", ""), max_len=200).strip(),
            "href": validate_link(block.get("href", "")),
        }
    if kind == "table":
        rows = block.get("rows")
        if not isinstance(rows, list) or not rows or len(rows) > MAX_TABLE_ROWS:
            raise RichTextError("Ungültige Tabelle")
        width: int | None = None
        clean_rows: list[list[list[dict[str, Any]]]] = []
        for row in rows:
            if not isinstance(row, list) or not row or len(row) > MAX_TABLE_COLS:
                raise RichTextError("Ungültige Tabellenzeile")
            if width is None:
                width = len(row)
            if len(row) != width:
                raise RichTextError("Alle Tabellenzeilen müssen gleich viele Spalten haben")
            clean_rows.append([_normalize_runs(cell) for cell in row])
        return {"type": kind, "rows": clean_rows}
    raise RichTextError("Unbekannter RichText-Block")


def plain_document(text: str, profile: str = "document") -> dict[str, Any]:
    if profile not in PROFILES:
        raise RichTextError("Unbekanntes RichText-Profil")
    text = _clean_text(text)
    blocks: list[dict[str, Any]] = []
    # Preserve old plaintext content without interpreting any markup.
    for paragraph in re.split(r"\n{2,}", text):
        if paragraph or not blocks:
            blocks.append({"type": "paragraph", "runs": [{"text": paragraph, "marks": []}]})
    return {"schema": SCHEMA, "version": VERSION, "profile": profile, "blocks": blocks}


def normalize_document(value: str | dict[str, Any] | None, profile: str = "document", *, max_chars: int = 524_288) -> dict[str, Any]:
    if profile not in PROFILES:
        raise RichTextError("Unbekanntes RichText-Profil")
    if value is None:
        raw: Any = plain_document("", profile)
    elif isinstance(value, dict):
        raw = value
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{"):
            try:
                candidate = json.loads(stripped)
            except json.JSONDecodeError:
                candidate = None
            if isinstance(candidate, dict) and candidate.get("schema") == SCHEMA:
                raw = candidate
            else:
                raw = plain_document(value, profile)
        else:
            raw = plain_document(value, profile)
    else:
        raise RichTextError("Ungültiger RichText-Wert")

    if raw.get("schema") != SCHEMA or raw.get("version") != VERSION:
        raise RichTextError("Nicht unterstütztes RichText-Schema")
    incoming_profile = raw.get("profile", profile)
    if incoming_profile != profile:
        # The server decides which profile is allowed at this field.
        incoming_profile = profile
    blocks = raw.get("blocks")
    if not isinstance(blocks, list) or len(blocks) > MAX_BLOCKS:
        raise RichTextError("Ungültige Anzahl RichText-Blöcke")
    normalized = [_normalize_block(block, profile) for block in blocks]
    if not normalized:
        normalized = [{"type": "paragraph", "runs": [{"text": "", "marks": []}]}]
    out = {"schema": SCHEMA, "version": VERSION, "profile": incoming_profile, "blocks": normalized}
    if len(plain_text(out)) > max_chars:
        raise RichTextError(f"RichText ist zu lang (maximal {max_chars} Zeichen Text)")
    return out


def canonical_json(value: str | dict[str, Any] | None, profile: str = "document", *, max_chars: int = 524_288) -> str:
    doc = normalize_document(value, profile, max_chars=max_chars)
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"))


def validate_richtext(value: str, profile: str, *, max_chars: int, required: bool = True) -> str:
    result = canonical_json(value, profile, max_chars=max_chars)
    if required and not plain_text(result).strip():
        raise RichTextError("Das Feld darf nicht leer sein")
    return result


def plain_text(value: str | dict[str, Any] | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped.startswith("{"):
            return value
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError:
            return value
    else:
        raw = value
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return value if isinstance(value, str) else ""
    chunks: list[str] = []
    for block in raw.get("blocks", []):
        kind = block.get("type")
        if kind in {"paragraph", "heading", "quote"}:
            chunks.append("".join(str(r.get("text", "")) for r in block.get("runs", [])))
        elif kind in {"bullet_list", "ordered_list"}:
            for item in block.get("items", []):
                chunks.append("".join(str(r.get("text", "")) for r in item))
        elif kind == "code":
            chunks.append(str(block.get("text", "")))
        elif kind == "button_link":
            chunks.append(str(block.get("text", "")))
        elif kind == "table":
            for row in block.get("rows", []):
                chunks.append(" ".join("".join(str(r.get("text", "")) for r in cell) for cell in row))
    return "\n\n".join(chunks)


def excerpt(value: str | dict[str, Any] | None, length: int = 220) -> str:
    text = " ".join(plain_text(value).split())
    return text if len(text) <= length else text[: max(0, length - 1)].rstrip() + "…"
