from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Iterable

import config


TEXT_EXTS = {".txt", ".log", ".json", ".jsonl", ".xml", ".srt", ".sub"}
CSV_EXTS = {".csv"}
SUPPORTED_EXTS = TEXT_EXTS | CSV_EXTS | {".locres"}
PREFERRED_TEXT_COLUMNS = (
    "localizedstring",
    "translation",
    "text",
    "value",
    "string",
    "source",
    "sourcestring",
    "message",
    "subtitle",
)


@dataclass
class SubtitleImportResult:
    source: str
    source_type: str
    line_count: int
    preview_lines: list[str]
    lines: list[str]
    error_message: str = ""

    @property
    def ok(self) -> bool:
        return not self.error_message


def import_subtitle_resource(resource: str, preview_limit: int = 8) -> SubtitleImportResult:
    raw = (resource or "").strip()
    if not raw:
        return SubtitleImportResult(
            source=raw,
            source_type="empty",
            line_count=0,
            preview_lines=[],
            lines=[],
            error_message="Пустой путь ресурса.",
        )

    if _is_manifest_style(raw):
        return SubtitleImportResult(
            source=raw,
            source_type="manifest",
            line_count=0,
            preview_lines=[],
            lines=[],
            error_message=(
                "Указан manifest-style путь. Сначала выполните extraction шаг из pak/utoc/ucas, "
                "затем импортируйте полученный txt/csv/jsonl файл."
            ),
        )

    path = os.path.abspath(os.path.expanduser(raw))
    ext = os.path.splitext(path)[1].lower()

    if ext and ext not in SUPPORTED_EXTS:
        return SubtitleImportResult(
            source=path,
            source_type="unsupported",
            line_count=0,
            preview_lines=[],
            lines=[],
            error_message=(
                f"Неподдерживаемый формат: {ext}. Поддерживаются: "
                ".txt, .log, .json, .jsonl, .xml, .srt, .sub, .csv, .locres"
            ),
        )

    if not os.path.exists(path):
        return SubtitleImportResult(
            source=path,
            source_type="missing",
            line_count=0,
            preview_lines=[],
            lines=[],
            error_message=f"Файл не найден: {path}",
        )

    if ext in TEXT_EXTS:
        lines = _load_text_like(path, ext)
        return _make_result(path, "text", lines, preview_limit)

    if ext in CSV_EXTS:
        lines = _load_csv_like(path)
        return _make_result(path, "csv", lines, preview_limit)

    # ext == .locres
    locres_result = _load_locres_via_unreal_locres(path)
    if locres_result.error_message:
        return locres_result
    return _make_result(path, "locres", locres_result.lines, preview_limit)


def _make_result(source: str, source_type: str, lines: Iterable[str], preview_limit: int) -> SubtitleImportResult:
    cleaned = _clean_lines(lines)
    return SubtitleImportResult(
        source=source,
        source_type=source_type,
        line_count=len(cleaned),
        preview_lines=cleaned[: max(1, int(preview_limit))],
        lines=cleaned,
    )


def _is_manifest_style(raw: str) -> bool:
    if "::" not in raw:
        return False

    left = raw.split("::", 1)[0].strip()
    base = os.path.basename(left).lower()
    return base.startswith("manifest_") and base.endswith(".txt")


def _clean_lines(lines: Iterable[str]) -> list[str]:
    out = []
    for line in lines:
        text = " ".join(str(line or "").split()).strip()
        if text:
            out.append(text)
    return out


def _load_text_like(path: str, ext: str) -> list[str]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        if ext == ".json":
            return _parse_json_text(f)
        if ext == ".jsonl":
            return _parse_jsonl_lines(f)
        lines = [line.rstrip("\n\r") for line in f]
        if ext in {".srt", ".sub"}:
            return _strip_subtitle_timing_lines(lines)
        return lines


def _parse_json_text(file_obj) -> list[str]:
    raw = file_obj.read()
    if not raw.strip():
        return []

    try:
        obj = json.loads(raw)
    except Exception:
        return [line.rstrip("\n\r") for line in raw.splitlines()]

    extracted = _extract_text_values(obj)
    if extracted:
        return extracted

    return [line.rstrip("\n\r") for line in raw.splitlines()]


def _strip_subtitle_timing_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    timing_pattern = re.compile(
        r"^\s*(\d{2}:\d{2}:\d{2}[,\.]\d{1,3}|\{\d+\}\{\d+\})(\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{1,3})?\s*$"
    )

    for line in lines:
        text = (line or "").strip()
        if not text:
            out.append("")
            continue
        if text.isdigit():
            continue
        if timing_pattern.match(text):
            continue
        out.append(line)

    return out


def _parse_jsonl_lines(file_obj) -> list[str]:
    out: list[str] = []
    for raw_line in file_obj:
        line = raw_line.strip()
        if not line:
            continue

        try:
            obj = json.loads(line)
        except Exception:
            out.append(line)
            continue

        extracted = _extract_text_values(obj)
        if extracted:
            out.extend(extracted)
        else:
            out.append(line)

    return out


def _extract_text_values(obj) -> list[str]:
    if isinstance(obj, str):
        text = obj.strip()
        return [text] if text else []

    if isinstance(obj, dict):
        preferred = []
        for key in (
            "text",
            "value",
            "message",
            "subtitle",
            "localized",
            "localizedstring",
            "translation",
            "source",
            "sourcestring",
        ):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                preferred.append(val.strip())

        if preferred:
            return preferred

        out = []
        for val in obj.values():
            out.extend(_extract_text_values(val))
        return out

    if isinstance(obj, list):
        out = []
        for item in obj:
            out.extend(_extract_text_values(item))
        return out

    return []


def _load_csv_like(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return []

        fieldnames = [str(name or "").strip() for name in reader.fieldnames]
        normalized = {name: _normalize_header(name) for name in fieldnames}

        preferred_cols = []
        for name in fieldnames:
            norm = normalized[name]
            if any(token in norm for token in PREFERRED_TEXT_COLUMNS):
                preferred_cols.append(name)

        if not preferred_cols:
            preferred_cols = [
                name
                for name in fieldnames
                if not any(token in normalized[name] for token in ("id", "key", "path", "namespace", "hash"))
            ]

        lines: list[str] = []
        for row in reader:
            row_texts = []
            for col in preferred_cols:
                value = str((row or {}).get(col, "") or "").strip()
                if value:
                    row_texts.append(value)
            if row_texts:
                lines.extend(row_texts)

        return lines


def _normalize_header(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _load_locres_via_unreal_locres(path: str) -> SubtitleImportResult:
    tool_path = _find_unreal_locres(path)
    if not tool_path:
        return SubtitleImportResult(
            source=path,
            source_type="locres",
            line_count=0,
            preview_lines=[],
            lines=[],
            error_message=(
                "Для импорта .locres нужен UnrealLocres.exe. Установите инструмент и добавьте в PATH "
                "или положите рядом с файлом .locres."
            ),
        )

    with tempfile.TemporaryDirectory(prefix="locres_export_") as temp_dir:
        csv_path = os.path.join(temp_dir, "export.csv")
        ok, error_text = _try_export_locres_to_csv(tool_path, path, csv_path)
        if not ok:
            return SubtitleImportResult(
                source=path,
                source_type="locres",
                line_count=0,
                preview_lines=[],
                lines=[],
                error_message=(
                    "Не удалось экспортировать .locres через UnrealLocres.exe. "
                    f"{error_text}"
                ),
            )

        lines = _load_csv_like(csv_path)
        return SubtitleImportResult(
            source=path,
            source_type="locres",
            line_count=len(lines),
            preview_lines=lines[:8],
            lines=lines,
        )


def _find_unreal_locres(locres_path: str) -> str | None:
    candidates = []

    configured_tool = str(getattr(config, "UNREAL_LOCRES_TOOL", "") or "").strip()
    if configured_tool:
        candidates.append(os.path.abspath(os.path.expanduser(configured_tool)))

    path_tool = shutil.which("UnrealLocres.exe")
    if path_tool:
        candidates.append(path_tool)

    locres_dir = os.path.dirname(locres_path)
    for rel in ("UnrealLocres.exe", os.path.join("tools", "UnrealLocres.exe")):
        candidates.append(os.path.join(locres_dir, rel))

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return os.path.abspath(candidate)

    return None


def _try_export_locres_to_csv(tool_path: str, locres_path: str, csv_path: str) -> tuple[bool, str]:
    command_variants = [
        [tool_path, "export", locres_path, "-f", "csv", "-o", csv_path],
        [tool_path, "export", "-f", "csv", "-o", csv_path, locres_path],
        [tool_path, "export", locres_path, csv_path],
    ]

    last_error = ""
    for command in command_variants:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=25,
            )
            if completed.returncode == 0 and os.path.isfile(csv_path) and os.path.getsize(csv_path) > 0:
                return True, ""

            stderr = (completed.stderr or "").strip()
            stdout = (completed.stdout or "").strip()
            details = stderr or stdout or f"exit code {completed.returncode}"
            last_error = details
        except Exception as e:
            last_error = str(e)

    if not last_error:
        last_error = "Неизвестная ошибка вызова UnrealLocres.exe"

    return False, last_error
