"""
SkillRunner: executes a slash-command skill via the `claude` CLI subprocess.

Wraps the original skill_runner.py logic in a class, adding:
- RunStatus detection (SUCCESS / RATE_LIMITED / TIMEOUT / ERROR)
- Optional max_turns passthrough (--max-turns N flag)
- SessionResult dataclass return type

All Windows-specific subprocess fixes are preserved verbatim:
- stdin=subprocess.DEVNULL  (prevents Git Bash hang waiting for terminal input)
- encoding="utf-8"          (prevents Windows cp1252 UnicodeDecodeError)
- Direct node.exe resolution (bypasses cmd.exe wrapper for clean process kill)
- CLAUDECODE env var removal (allows CLI to run inside a Claude Code session)
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from tests.model_comparison.framework.types import RunStatus, SessionResult


def _claude_direct_cmd() -> list[str] | None:
    """
    On Windows, resolve node.exe + cli.js directly from claude.CMD so that
    subprocess can kill the actual node process (not just a cmd.exe wrapper).
    Returns None on non-Windows or if resolution fails.
    """
    if sys.platform != "win32":
        return None
    claude_cmd = shutil.which("claude")
    if claude_cmd is None:
        return None
    npm_bin = Path(claude_cmd).parent
    # npm places node.exe next to claude.CMD; fall back to system node
    node_exe = npm_bin / "node.exe"
    if not node_exe.exists():
        node_path = shutil.which("node")
        if node_path is None:
            return None
        node_exe = Path(node_path)
    cli_js = npm_bin / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
    if not cli_js.exists():
        return None
    return [str(node_exe), str(cli_js)]


class SkillRunner:
    """
    Executes a skill via the `claude` CLI and returns a SessionResult.

    Invokes:
        claude --print --verbose --model <model> --output-format stream-json
               --no-session-persistence [--max-turns N] /<skill> [arguments]

    The subprocess call preserves all Windows-specific fixes from the original
    skill_runner.py. See module docstring for details.
    """

    SESSION_TIMEOUT: int = 600
    RATE_LIMIT_STRING: str = "You've hit your limit"

    # Allowlist for model identifiers.
    _ALLOWED_MODELS: frozenset[str] = frozenset(
        {
            "sonnet",
            "haiku",
            "opus",
            "claude-sonnet-latest",
            "claude-haiku-latest",
            "claude-opus-latest",
        }
    )

    # Skill names may only contain word characters and hyphens.
    _SAFE_SKILL_NAME = re.compile(r"^[\w\-]+$")

    # Arguments may contain ASCII word characters, whitespace, hyphens, and dots/commas.
    _SAFE_ARGUMENTS = re.compile(r"^[\w\s\-\.,]*$", re.ASCII)

    def __init__(self, project_root: Path, timeout: int = SESSION_TIMEOUT) -> None:
        """
        Args:
            project_root: Absolute path to the project root (used as cwd for subprocess).
            timeout: Maximum wall-clock seconds per CLI invocation.
        """
        self._project_root = project_root
        self._timeout = timeout

    def run(
        self,
        skill_name: str,
        arguments: str,
        model: str,
        max_turns: int | None = None,
    ) -> SessionResult:
        """
        Execute a skill and return a parsed SessionResult.

        Args:
            skill_name: Skill name as it appears in .claude/commands/ (e.g. "run-pipeline").
            arguments:  Arguments string to pass after the skill name.
            model:      Model identifier from _ALLOWED_MODELS.
            max_turns:  If provided, passed as --max-turns N to the CLI.

        Raises:
            ValueError: if skill_name, arguments, or model fail validation.
        """
        if not self._SAFE_SKILL_NAME.match(skill_name):
            raise ValueError(f"Invalid skill_name: {skill_name!r}")
        if arguments and not self._SAFE_ARGUMENTS.match(arguments):
            raise ValueError(f"Unsafe characters in arguments: {arguments!r}")
        if model not in self._ALLOWED_MODELS:
            raise ValueError(f"Model not in allowlist: {model!r}")

        raw = self._invoke(skill_name, arguments, model, max_turns)
        status = self._detect_status(raw)
        return SessionResult(
            model=model,
            skill=skill_name,
            arguments=arguments,
            tool_calls=raw["tool_calls"],
            final_text=raw["final_text"],
            input_tokens=raw["input_tokens"],
            output_tokens=raw["output_tokens"],
            turn_count=raw["turn_count"],
            error=raw["error"],
            status=status,
        )

    def _detect_status(self, raw: dict[str, Any]) -> RunStatus:
        """
        Classify the session outcome.

        Priority order:
        1. "timed out" in error  → TIMEOUT
        2. Rate-limit string in final_text or error  → RATE_LIMITED
        3. error is not None  → ERROR
        4. Otherwise  → SUCCESS
        """
        error = raw.get("error") or ""
        final_text = raw.get("final_text") or ""

        if "timed out" in error:
            return RunStatus.TIMEOUT
        if self.RATE_LIMIT_STRING in final_text or self.RATE_LIMIT_STRING in error:
            return RunStatus.RATE_LIMITED
        if error:
            return RunStatus.ERROR
        return RunStatus.SUCCESS

    def _invoke(
        self,
        skill_name: str,
        arguments: str,
        model: str,
        max_turns: int | None,
    ) -> dict[str, Any]:
        """Spawn the claude CLI subprocess and parse the JSONL stream."""
        session: dict[str, Any] = {
            "model": model,
            "skill": skill_name,
            "arguments": arguments,
            "tool_calls": [],
            "final_text": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "turn_count": 0,
            "error": None,
        }

        prompt = f"/{skill_name} {arguments}".strip()
        claude_args = [
            "claude",
            "--print",
            "--verbose",
            "--model",
            model,
            "--output-format",
            "stream-json",
            "--no-session-persistence",
        ]
        if max_turns is not None:
            claude_args += ["--max-turns", str(max_turns)]
        claude_args.append(prompt)

        # On Windows, invoke node.exe + cli.js directly (bypasses cmd.exe wrapper)
        # so Python holds a direct handle to the Claude process and can kill it
        # cleanly on timeout without pipe deadlocks.
        direct = _claude_direct_cmd()
        if direct is not None:
            cmd = direct + claude_args[1:]  # drop "claude" from front
        elif sys.platform == "win32":
            cmd = ["cmd", "/c"] + claude_args  # fallback if resolution fails
        else:
            cmd = claude_args

        # Strip CLAUDECODE so the CLI doesn't refuse to run inside a Claude Code session.
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self._timeout,
                cwd=str(self._project_root),
                env=env,
                stdin=subprocess.DEVNULL,
            )
            stdout = result.stdout
            if result.returncode != 0:
                stderr_msg = result.stderr.strip()
                if not stdout:
                    session["error"] = (
                        f"claude CLI exited with code {result.returncode}: {stderr_msg}"
                    )
                    return session
                # Partial output — record warning but continue parsing.
                session["error"] = (
                    f"claude CLI exited with code {result.returncode}"
                    f" (partial output): {stderr_msg}"
                )
        except subprocess.TimeoutExpired:
            session["error"] = f"claude CLI timed out after {self._timeout}s"
            return session
        except FileNotFoundError:
            session["error"] = "claude CLI not found — ensure it is installed and on PATH"
            return session
        except OSError as e:
            session["error"] = f"OS error launching claude CLI: {e}"
            return session

        self._parse_jsonl(stdout, session)
        return session

    @staticmethod
    def _parse_jsonl(stdout: str, session: dict[str, Any]) -> None:
        """Parse the JSONL event stream from the claude CLI into session dict (in-place)."""
        # Keyed by tool_use id; cleared once the matching tool_result is seen.
        pending_tool_uses: dict[str, dict[str, Any]] = {}

        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # Non-JSON lines (e.g. progress dots) are silently skipped.
                continue

            event_type = event.get("type")

            if event_type == "assistant":
                message = event.get("message", {})
                content = message.get("content", [])
                usage = message.get("usage", {})

                session["input_tokens"] += usage.get("input_tokens", 0)
                session["output_tokens"] += usage.get("output_tokens", 0)
                session["turn_count"] += 1

                for block in content:
                    block_type = block.get("type")
                    if block_type == "tool_use":
                        pending_tool_uses[block["id"]] = {
                            "id": block["id"],
                            "name": block.get("name", ""),
                            "input": block.get("input", {}),
                        }
                    elif block_type == "text":
                        # Accumulate text across all turns; overwriting would discard
                        # earlier reasoning and key numbers from multi-turn sessions.
                        text = block.get("text", "")
                        if text:
                            if session["final_text"]:
                                session["final_text"] += "\n" + text
                            else:
                                session["final_text"] = text

            elif event_type == "user":
                message = event.get("message", {})
                content = message.get("content", [])

                for block in content:
                    if block.get("type") == "tool_result":
                        tool_use_id = block.get("tool_use_id", "")
                        pending = pending_tool_uses.pop(tool_use_id, None)
                        if pending is not None:
                            tool_input = pending["input"]
                            # Normalise input to a plain string for the report.
                            if isinstance(tool_input, dict):
                                # Bash → command field; Read → file_path; fallback to repr
                                input_str = (
                                    tool_input.get("command")
                                    or tool_input.get("file_path")
                                    or str(tool_input)
                                )
                            else:
                                input_str = str(tool_input)

                            raw_output = block.get("content", "")
                            if isinstance(raw_output, list):
                                # content can be a list of text blocks
                                output_str = "\n".join(
                                    b.get("text", "")
                                    for b in raw_output
                                    if isinstance(b, dict)
                                )
                            else:
                                output_str = str(raw_output)

                            session["tool_calls"].append(
                                {
                                    "name": pending["name"],
                                    "input": input_str,
                                    "output": output_str,
                                }
                            )

            elif event_type == "result":
                if event.get("subtype") == "error":
                    session["error"] = event.get("error", "Unknown CLI error")

        # Drain any tool_use blocks whose tool_result was never received (e.g. truncated
        # stream or premature CLI exit). Record them so scoring counts them correctly.
        for orphan in pending_tool_uses.values():
            session["tool_calls"].append(
                {
                    "name": orphan["name"],
                    "input": str(orphan["input"]),
                    "output": "[INCOMPLETE — no tool_result received]",
                }
            )
        if pending_tool_uses and session["error"] is None:
            session["error"] = (
                f"Stream ended with {len(pending_tool_uses)} unmatched tool_use block(s)"
            )
