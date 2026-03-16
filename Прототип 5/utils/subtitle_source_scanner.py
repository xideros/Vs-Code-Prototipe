# utils/subtitle_source_scanner.py

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Iterable

import config


READABLE_TEXT_EXTS = {
    ".log",
    ".txt",
    ".json",
    ".jsonl",
    ".csv",
    ".xml",
    ".srt",
    ".sub",
}

PACKED_RESOURCE_EXTS = {
    ".locres",
    ".locmeta",
    ".uasset",
    ".uexp",
    ".pak",
    ".utoc",
    ".ucas",
}

HIGH_VALUE_PATH_BOOSTS = {
    os.path.join("content", "localization", "game"): 42,
    os.path.join("content", "subtitles"): 44,
    os.path.join("content", "stringtables"): 40,
}

HIGH_VALUE_NAME_BOOSTS = {
    "st_activedialogs": 34,
    "dt_dialog": 32,
    "dialog_struct": 22,
    "dt_speaker_subtitlesentries": 38,
    "subspeakersdata": 24,
    "game.locres": 28,
    "game.locmeta": 20,
}

SAVE_EXTS = {
    ".sav",
    ".save",
    ".slot",
}

KEYWORDS = {
    "subtitle",
    "subtitles",
    "dialog",
    "dialogue",
    "caption",
    "captions",
    "stringtable",
    "stringtables",
    "localization",
    "l10n",
    "locres",
    "locmeta",
    "activedialogs",
    "speaker",
    "voice",
    "text",
    "story",
    "quest",
}

UE_PATH_BOOSTS = {
    os.path.join("content", "localization"): 34,
    os.path.join("content", "subtitles"): 30,
    os.path.join("content", "stringtables"): 28,
    os.path.join("saved", "logs"): 24,
    os.path.join("saved", "config"): 10,
    os.path.join("content", "paks"): 14,
}

SKIP_DIR_NAMES = {
    ".git",
    "__pycache__",
    "binaries",
    "intermediate",
    "deriveddatacache",
    "shadercache",
    "d3dshadercache",
}

PRIORITY_DIR_KEYWORDS = {
    "content",
    "saved",
    "localization",
    "subtitles",
    "stringtables",
    "paks",
    "dialog",
    "dialogue",
    "caption",
    "voice",
    "text",
    "story",
    "quest",
}

GENERIC_CONFIG_NAMES = {
    "engine.ini",
    "input.ini",
    "scalability.ini",
    "game.ini",
    "settings.ini",
}

GENERIC_GAME_TOKENS = {
    "game",
    "games",
    "steam",
    "engine",
    "content",
    "binaries",
    "plugins",
    "manifest",
    "windows",
    "win64",
    "default",
    "edition",
    "ultimate",
    "deluxe",
    "definitive",
    "remastered",
    "redux",
    "complete",
    "the",
    "and",
}


@dataclass
class SubtitleSourceCandidate:
    path: str
    kind: str
    score: int
    reason: str

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "kind": self.kind,
            "score": self.score,
            "reason": self.reason,
        }


class SubtitleSourceScanner:
    """Scans game/runtime folders and ranks potential subtitle sources."""

    def __init__(self, max_files: int | None = None):
        self.max_files = int(max_files or getattr(config, "SCAN_MAX_FILES", 25000))

    def scan(
        self,
        game_root: str,
        extra_saved_dir: str | None = None,
        result_limit: int | None = None,
    ) -> dict:
        roots = self._collect_roots(game_root, extra_saved_dir=extra_saved_dir)
        visited_files = 0
        stopped_by_limit = False
        all_candidates: list[SubtitleSourceCandidate] = []

        for root in roots:
            if visited_files >= self.max_files:
                stopped_by_limit = True
                break

            for candidate, visited_files in self._scan_root(root, visited_files):
                all_candidates.append(candidate)
                if visited_files >= self.max_files:
                    stopped_by_limit = True
                    break

            all_candidates = self._dedupe_candidates(all_candidates)
        all_candidates.sort(key=lambda x: (x.score, x.path.lower()), reverse=True)
        if result_limit is None:
            result_limit = int(getattr(config, "SCAN_RESULT_LIMIT", 30))
        result_limit = max(1, int(result_limit))

        return {
            "roots": roots,
            "visited_files": visited_files,
            "max_files": self.max_files,
            "stopped_by_limit": stopped_by_limit,
            "candidates": [c.as_dict() for c in all_candidates[:result_limit]],
        }

    def _dedupe_candidates(self, candidates: list[SubtitleSourceCandidate]) -> list[SubtitleSourceCandidate]:
        best_by_key: dict[tuple[str, str], SubtitleSourceCandidate] = {}

        for candidate in candidates:
            normalized_path = candidate.path.replace("/", "\\")
            stem = os.path.splitext(normalized_path)[0].lower()
            key = (candidate.kind, stem if candidate.kind == "pak-container" else candidate.path.lower())
            current = best_by_key.get(key)
            if current is None or candidate.score > current.score:
                best_by_key[key] = candidate

        return list(best_by_key.values())

    def _collect_roots(self, game_root: str, extra_saved_dir: str | None = None) -> list[str]:
        roots: list[str] = []

        def add_root(path: str | None):
            if not path:
                return
            normalized = os.path.normpath(path)
            if not os.path.isdir(normalized):
                return
            if normalized not in roots:
                roots.append(normalized)

        add_root(game_root)
        if game_root:
            add_root(os.path.join(game_root, "Saved"))

        game_tokens = self._collect_game_tokens(game_root)

        if extra_saved_dir:
            add_root(extra_saved_dir)

        local_app_data = os.getenv("LOCALAPPDATA")
        roaming_app_data = os.getenv("APPDATA")
        user_profile = os.getenv("USERPROFILE") or os.path.expanduser("~")

        probable_user_roots: list[str] = []
        if local_app_data:
            probable_user_roots.append(local_app_data)
            probable_user_roots.append(
                os.path.normpath(os.path.join(local_app_data, os.pardir, "LocalLow"))
            )
        if roaming_app_data:
            probable_user_roots.append(roaming_app_data)
        if user_profile:
            probable_user_roots.append(os.path.join(user_profile, "AppData", "LocalLow"))
            documents = os.path.join(user_profile, "Documents")
            probable_user_roots.append(documents)
            probable_user_roots.append(os.path.join(documents, "My Games"))

        for root in probable_user_roots:
            for candidate in self._find_matching_user_dirs(root, game_tokens):
                add_root(candidate)

        return roots

    def _collect_game_tokens(self, game_root: str) -> set[str]:
        tokens: set[str] = set()
        if not game_root:
            return tokens

        path_parts = [part for part in os.path.normpath(game_root).split(os.sep) if part]
        interesting_parts = path_parts[-3:]

        for part in interesting_parts:
            for token in re.split(r"[^A-Za-zА-Яа-яЁё0-9]+", part.lower()):
                token = token.strip()
                if len(token) < 3:
                    continue
                if token in GENERIC_GAME_TOKENS:
                    continue
                tokens.add(token)

        try:
            for entry in os.listdir(game_root):
                for token in re.split(r"[^A-Za-zА-Яа-яЁё0-9]+", entry.lower()):
                    token = token.strip()
                    if len(token) < 3:
                        continue
                    if token in GENERIC_GAME_TOKENS:
                        continue
                    tokens.add(token)
        except Exception:
            pass

        return tokens

    def _find_matching_user_dirs(self, root: str, game_tokens: set[str]) -> list[str]:
        if not root or not os.path.isdir(root):
            return []

        if not game_tokens:
            return []

        matches: list[str] = []
        try:
            for entry in os.scandir(root):
                if not entry.is_dir():
                    continue

                name_low = entry.name.lower()
                if any(token in name_low or name_low in token for token in game_tokens):
                    matches.append(entry.path)
        except Exception:
            return []

        return matches

    def _scan_root(
        self,
        root: str,
        visited_start: int,
    ) -> Iterable[tuple[SubtitleSourceCandidate, int]]:
        visited_files = visited_start

        for current_root, dirs, files in os.walk(root, topdown=True):
            dirs[:] = [d for d in dirs if not self._should_skip_dir(current_root, d)]
            dirs.sort(key=self._dir_priority_key)

            for filename in files:
                if visited_files >= self.max_files:
                    return

                visited_files += 1
                full_path = os.path.join(current_root, filename)

                for manifest_candidate in self._scan_manifest_file(full_path):
                    yield manifest_candidate, visited_files

                candidate = self._build_candidate(full_path)
                if candidate is not None:
                    yield candidate, visited_files

    def _should_skip_dir(self, parent: str, dirname: str) -> bool:
        low = dirname.strip().lower()
        if low in SKIP_DIR_NAMES:
            return True

        parent_low = parent.replace("/", "\\").lower()
        if low == "intermediate" and "\\engine\\" in parent_low:
            return True

        return False

    def _dir_priority_key(self, dirname: str):
        low = dirname.strip().lower()
        for keyword in PRIORITY_DIR_KEYWORDS:
            if keyword in low:
                return (0, low)
        return (1, low)

    def _scan_manifest_file(self, path: str) -> list[SubtitleSourceCandidate]:
        name_low = os.path.basename(path).lower()
        if not (name_low.startswith("manifest_") and name_low.endswith(".txt")):
            return []

        candidates: list[SubtitleSourceCandidate] = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for raw_line in handle:
                    text = (raw_line or "").strip()
                    if not text:
                        continue
                    internal_path = text.split("\t", 1)[0].split("   ", 1)[0].strip()
                    candidate = self._build_candidate(
                        internal_path,
                        display_path=f"{path} :: {internal_path}",
                        extra_score=12,
                        extra_reason="manifest-hit",
                    )
                    if candidate is not None:
                        candidates.append(candidate)
        except Exception:
            return []

        return candidates

    def _build_candidate(
        self,
        path: str,
        display_path: str | None = None,
        extra_score: int = 0,
        extra_reason: str | None = None,
    ) -> SubtitleSourceCandidate | None:
        name = os.path.basename(path)
        name_low = name.lower()
        ext = os.path.splitext(name_low)[1]
        full_low = path.replace("/", "\\").lower()

        score = 0
        reasons: list[str] = []

        for keyword in KEYWORDS:
            if keyword in full_low:
                score += 8
                reasons.append(f"keyword:{keyword}")

        for ue_path, boost in UE_PATH_BOOSTS.items():
            token = "\\" + ue_path.replace("/", "\\")
            if token in full_low:
                score += boost
                reasons.append(f"ue-path:{ue_path}")

        for special_path, boost in HIGH_VALUE_PATH_BOOSTS.items():
            token = "\\" + special_path.replace("/", "\\")
            if token in full_low:
                score += boost
                reasons.append(f"high-path:{special_path}")

        for special_name, boost in HIGH_VALUE_NAME_BOOSTS.items():
            if special_name in name_low:
                score += boost
                reasons.append(f"high-name:{special_name}")

        if ext in READABLE_TEXT_EXTS:
            score += 13
            reasons.append(f"readable-ext:{ext}")

        if ext in PACKED_RESOURCE_EXTS:
            score += 16
            reasons.append(f"resource-ext:{ext}")

        if ext in {".locres", ".locmeta"}:
            score += 16
            reasons.append("localization-binary")

        if ext in {".pak", ".utoc", ".ucas"}:
            score += 2
            reasons.append("container-resource")

        if ext in SAVE_EXTS or "\\saved\\savegames\\" in full_low:
            score += 3
            reasons.append("save-data")

        if name_low == "gameusersettings.ini":
            score -= 34
            reasons.append("penalty:gameusersettings")

        if name_low in GENERIC_CONFIG_NAMES:
            score -= 18
            reasons.append("penalty:generic-config")

        if "shadercache" in full_low:
            score -= 20
            reasons.append("penalty:shader-cache")

        if extra_score:
            score += int(extra_score)
        if extra_reason:
            reasons.append(extra_reason)

        kind = self._detect_kind(full_low, name_low, ext)

        # Keep weak save-data hits for context, skip unrelated noise.
        if score < 8 and kind not in {"save-data", "pak-container"}:
            return None

        reasons_text = ", ".join(reasons[:6]) if reasons else "path-pattern"
        return SubtitleSourceCandidate(path=display_path or path, kind=kind, score=score, reason=reasons_text)

    def _detect_kind(self, full_low: str, name_low: str, ext: str) -> str:
        if ext in {".pak", ".utoc", ".ucas"}:
            return "pak-container"

        if ext in {".locres", ".locmeta"}:
            return "localization-resource"

        if ext in SAVE_EXTS or "\\saved\\savegames\\" in full_low:
            return "save-data"

        if ext in READABLE_TEXT_EXTS:
            if any(k in name_low for k in ("subtitle", "caption", "dialog", "dialogue")):
                return "subtitle-resource"
            if any(k in name_low for k in ("localization", "l10n", "stringtable", "locres")):
                return "localization-resource"
            if any(k in name_low for k in ("quest", "story", "speaker", "voice")):
                return "dialog-resource"
            return "text-log"

        if ext in {".uasset", ".uexp"}:
            if "localization" in full_low or "stringtable" in full_low:
                return "localization-resource"
            if any(k in full_low for k in ("subtitle", "caption", "dialog", "dialogue")):
                return "subtitle-resource"
            return "dialog-resource"

        if any(k in full_low for k in ("subtitle", "caption")):
            return "subtitle-resource"

        if any(k in full_low for k in ("dialog", "dialogue", "quest", "story", "speaker", "voice")):
            return "dialog-resource"

        if any(k in full_low for k in ("localization", "l10n", "stringtable")):
            return "localization-resource"

        return "unknown"
