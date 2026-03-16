from __future__ import annotations

from dataclasses import dataclass
import os
import subprocess
from typing import Iterable


DEFAULT_COMMAND_TEMPLATE = 'cmd /c ""{tool}" get "{container}" "{internal_path}" > "{expected_output_path}""'
_CONTAINER_EXTENSIONS = {".pak", ".utoc", ".ucas"}


@dataclass
class ExtractionPlan:
    manifest_path: str
    internal_path: str
    expected_output_path: str
    container_candidates: list[str]
    command_preview: str
    selected_container: str = ""
    game_root: str = ""
    output_dir: str = ""
    command_template: str = DEFAULT_COMMAND_TEMPLATE
    success: bool = True
    error: str = ""
    message: str = ""


@dataclass
class ExtractionRunResult:
    success: bool
    message: str
    manifest_path: str
    internal_path: str
    expected_output_path: str
    output_dir: str
    selected_container: str
    command_preview: str
    extracted_file: str = ""
    return_code: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    error: str = ""


class UEResourceExtractor:
    @staticmethod
    def parse_manifest_style(raw_target: str) -> tuple[bool, str, str, str]:
        raw = (raw_target or "").strip()
        if "::" not in raw:
            return False, "", "", "Target is not manifest-style (missing '::')."

        left, right = raw.split("::", 1)
        manifest_path = (left or "").strip()
        internal_path = (right or "").strip()
        if not manifest_path or not internal_path:
            return False, "", "", "Manifest-style target is incomplete."

        manifest_name = os.path.basename(manifest_path).lower()
        if not (manifest_name.startswith("manifest_") and manifest_name.endswith(".txt")):
            return False, "", "", "Left side is not a Manifest_*.txt file."

        manifest_path = os.path.abspath(os.path.expanduser(manifest_path))
        normalized_internal = internal_path.replace("\\", "/").lstrip("/")
        if not normalized_internal:
            return False, "", "", "Internal path is empty."

        return True, manifest_path, normalized_internal, ""

    @staticmethod
    def prepare_plan(
        raw_target: str,
        game_root: str,
        output_dir: str,
        tool_path: str = "",
        command_template: str = DEFAULT_COMMAND_TEMPLATE,
    ) -> ExtractionPlan:
        ok, manifest_path, internal_path, parse_error = UEResourceExtractor.parse_manifest_style(raw_target)
        if not ok:
            return ExtractionPlan(
                manifest_path="",
                internal_path="",
                expected_output_path="",
                container_candidates=[],
                command_preview="",
                selected_container="",
                game_root=(game_root or "").strip(),
                output_dir=(output_dir or "").strip(),
                command_template=command_template or DEFAULT_COMMAND_TEMPLATE,
                success=False,
                error=parse_error,
                message=parse_error,
            )

        resolved_game_root = os.path.abspath(os.path.expanduser((game_root or "").strip())) if game_root else ""
        resolved_output_dir = os.path.abspath(os.path.expanduser((output_dir or "").strip())) if output_dir else ""
        expected_output_path = UEResourceExtractor.build_expected_output_path(resolved_output_dir, internal_path)

        container_candidates = UEResourceExtractor.find_container_candidates(resolved_game_root)
        selected_container = container_candidates[0] if container_candidates else ""
        command_preview = UEResourceExtractor.build_command_preview(
            tool=(tool_path or "").strip() or "<tool>",
            container=selected_container or "<container>",
            output_dir=resolved_output_dir or "<output_dir>",
            internal_path=internal_path,
            game_root=resolved_game_root or "<game_root>",
            expected_output_path=expected_output_path or "<expected_output_path>",
            command_template=command_template or DEFAULT_COMMAND_TEMPLATE,
        )

        message_parts = [
            "Extraction plan prepared.",
            f"Containers found: {len(container_candidates)}.",
        ]
        if not container_candidates:
            message_parts.append("No pak/utoc/ucas containers were found under Content/Paks.")

        return ExtractionPlan(
            manifest_path=manifest_path,
            internal_path=internal_path,
            expected_output_path=expected_output_path,
            container_candidates=container_candidates,
            command_preview=command_preview,
            selected_container=selected_container,
            game_root=resolved_game_root,
            output_dir=resolved_output_dir,
            command_template=command_template or DEFAULT_COMMAND_TEMPLATE,
            success=True,
            error="",
            message=" ".join(message_parts),
        )

    @staticmethod
    def run_extraction(
        plan: ExtractionPlan,
        tool_path: str,
        container_path: str,
        command_template: str,
        timeout_sec: int = 120,
    ) -> ExtractionRunResult:
        if not plan or not plan.success:
            return ExtractionRunResult(
                success=False,
                message="Extraction plan is not prepared.",
                manifest_path=getattr(plan, "manifest_path", ""),
                internal_path=getattr(plan, "internal_path", ""),
                expected_output_path=getattr(plan, "expected_output_path", ""),
                output_dir=getattr(plan, "output_dir", ""),
                selected_container=container_path or "",
                command_preview="",
                error="Plan is missing or invalid.",
            )

        tool = os.path.abspath(os.path.expanduser((tool_path or "").strip()))
        output_dir = os.path.abspath(os.path.expanduser((plan.output_dir or "").strip())) if plan.output_dir else ""
        container = os.path.abspath(os.path.expanduser((container_path or "").strip())) if container_path else ""

        if not tool:
            return UEResourceExtractor._failed_result(plan, container, "Extractor tool path is empty.")
        if not os.path.isfile(tool):
            return UEResourceExtractor._failed_result(plan, container, f"Extractor tool not found: {tool}")
        if not container:
            return UEResourceExtractor._failed_result(plan, container, "Container file is not selected.")
        if not os.path.isfile(container):
            return UEResourceExtractor._failed_result(plan, container, f"Container file not found: {container}")
        if not output_dir:
            return UEResourceExtractor._failed_result(plan, container, "Output directory is empty.")

        os.makedirs(output_dir, exist_ok=True)
        expected_parent = os.path.dirname(plan.expected_output_path or "")
        if expected_parent:
            os.makedirs(expected_parent, exist_ok=True)

        template = command_template or DEFAULT_COMMAND_TEMPLATE
        command = UEResourceExtractor.build_command_preview(
            tool=tool,
            container=container,
            output_dir=output_dir,
            internal_path=plan.internal_path,
            game_root=plan.game_root,
            expected_output_path=plan.expected_output_path,
            command_template=template,
        )

        if command.startswith("Template error:"):
            return UEResourceExtractor._failed_result(plan, container, command)

        try:
            completed = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
                timeout=max(1, int(timeout_sec)),
            )
        except subprocess.TimeoutExpired as exc:
            return ExtractionRunResult(
                success=False,
                message="Extractor process timed out.",
                manifest_path=plan.manifest_path,
                internal_path=plan.internal_path,
                expected_output_path=plan.expected_output_path,
                output_dir=output_dir,
                selected_container=container,
                command_preview=command,
                return_code=None,
                stdout_tail=_tail_text(exc.stdout or ""),
                stderr_tail=_tail_text(exc.stderr or ""),
                error="Timeout expired.",
            )
        except Exception as exc:
            return UEResourceExtractor._failed_result(
                plan,
                container,
                f"Failed to run extractor: {exc}",
                command_preview=command,
            )

        found_file = ""
        expected = plan.expected_output_path
        if expected and os.path.isfile(expected):
            found_file = expected
        else:
            found_file = UEResourceExtractor.find_by_basename(output_dir, os.path.basename(plan.internal_path)) or ""

        if completed.returncode == 0 and found_file:
            return ExtractionRunResult(
                success=True,
                message="Extraction completed successfully.",
                manifest_path=plan.manifest_path,
                internal_path=plan.internal_path,
                expected_output_path=expected,
                output_dir=output_dir,
                selected_container=container,
                command_preview=command,
                extracted_file=os.path.abspath(found_file),
                return_code=completed.returncode,
                stdout_tail=_tail_text(completed.stdout),
                stderr_tail=_tail_text(completed.stderr),
            )

        err_message = "Extractor finished without the expected output file."
        if completed.returncode != 0:
            err_message = f"Extractor exited with code {completed.returncode}."

        return ExtractionRunResult(
            success=False,
            message=err_message,
            manifest_path=plan.manifest_path,
            internal_path=plan.internal_path,
            expected_output_path=expected,
            output_dir=output_dir,
            selected_container=container,
            command_preview=command,
            extracted_file=found_file,
            return_code=completed.returncode,
            stdout_tail=_tail_text(completed.stdout),
            stderr_tail=_tail_text(completed.stderr),
            error=err_message,
        )

    @staticmethod
    def build_expected_output_path(output_dir: str, internal_path: str) -> str:
        normalized_internal = (internal_path or "").replace("\\", "/").lstrip("/")
        chunks = [chunk for chunk in normalized_internal.split("/") if chunk and chunk not in {".", ".."}]
        if not output_dir:
            return os.path.normpath(os.path.join(*chunks)) if chunks else ""
        if not chunks:
            return os.path.normpath(output_dir)
        return os.path.normpath(os.path.join(output_dir, *chunks))

    @staticmethod
    def find_container_candidates(game_root: str) -> list[str]:
        if not game_root:
            return []

        paks_root = os.path.join(game_root, "Content", "Paks")
        if not os.path.isdir(paks_root):
            return []

        discovered: list[str] = []
        for current_root, _, files in os.walk(paks_root):
            for name in files:
                ext = os.path.splitext(name)[1].lower()
                if ext in _CONTAINER_EXTENSIONS:
                    discovered.append(os.path.abspath(os.path.join(current_root, name)))

        discovered = list(dict.fromkeys(discovered))
        discovered.sort(key=_container_sort_key)
        return discovered

    @staticmethod
    def build_command_preview(
        tool: str,
        container: str,
        output_dir: str,
        internal_path: str,
        game_root: str,
        expected_output_path: str,
        command_template: str,
    ) -> str:
        template = command_template or DEFAULT_COMMAND_TEMPLATE
        try:
            return template.format(
                tool=tool,
                container=container,
                output_dir=output_dir,
                internal_path=internal_path,
                game_root=game_root,
                expected_output_path=expected_output_path,
            )
        except KeyError as missing:
            return f"Template error: unknown placeholder {missing}."
        except Exception as exc:
            return f"Template error: {exc}"

    @staticmethod
    def find_by_basename(output_dir: str, basename: str) -> str | None:
        if not output_dir or not basename or not os.path.isdir(output_dir):
            return None

        target = basename.lower()
        for current_root, _, files in os.walk(output_dir):
            for name in files:
                if name.lower() == target:
                    return os.path.join(current_root, name)

        return None

    @staticmethod
    def _failed_result(
        plan: ExtractionPlan,
        container: str,
        message: str,
        command_preview: str = "",
    ) -> ExtractionRunResult:
        return ExtractionRunResult(
            success=False,
            message=message,
            manifest_path=plan.manifest_path,
            internal_path=plan.internal_path,
            expected_output_path=plan.expected_output_path,
            output_dir=plan.output_dir,
            selected_container=container,
            command_preview=command_preview,
            error=message,
        )


def _tail_text(text: str, max_lines: int = 20, max_chars: int = 3000) -> str:
    if not text:
        return ""

    lines = text.splitlines()
    tail = "\n".join(lines[-max(1, int(max_lines)):])
    if len(tail) > max_chars:
        return tail[-max_chars:]
    return tail


def iter_preview_lines(lines: Iterable[str], limit: int = 8) -> list[str]:
    out: list[str] = []
    for item in lines:
        out.append(str(item))
        if len(out) >= max(1, int(limit)):
            break
    return out


def _container_sort_key(path: str):
    name = os.path.basename(path).lower()
    score = 0

    if "pakchunk0" in name:
        score += 120
    elif "pakchunk" in name:
        score += 90

    for token, boost in (
        ("main", 60),
        ("base", 56),
        ("global", 44),
        ("windows", 36),
        ("win64", 34),
        ("content", 20),
    ):
        if token in name:
            score += boost

    ext = os.path.splitext(name)[1]
    ext_rank = {".pak": 0, ".utoc": 1, ".ucas": 2}.get(ext, 3)
    return (-score, ext_rank, name)
