"""
Core runner for executing a slash-command skill via the `claude` CLI.

Invokes `claude --print --output-format stream-json` as a subprocess, which
uses the user's existing Claude Pro credentials — no API key required.

Parses the JSONL event stream to reconstruct tool call records and token
counts in the same session dict schema as the original SDK-based runner.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

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


PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
COMMANDS_DIR = PROJECT_ROOT / ".claude" / "commands"

# Maximum wall-clock seconds to wait for the CLI session to complete.
SESSION_TIMEOUT = 300

# Allowlist for model identifiers accepted by run_skill.
_ALLOWED_MODELS: frozenset[str] = frozenset({
    "sonnet",
    "haiku",
    "opus",
    "claude-sonnet-latest",
    "claude-haiku-latest",
    "claude-opus-latest",
})

# Skill names may only contain word characters and hyphens.
_SAFE_SKILL_NAME = re.compile(r"^[\w\-]+$")

# Arguments may contain word characters, whitespace, hyphens, dots, commas,
# and single/double quotes — sufficient for all current scenarios.
_SAFE_ARGUMENTS = re.compile(r'^[\w\s\-\.,\'"]*$')


def run_skill(
    skill_name: str,
    arguments: str,
    model: str,
) -> dict[str, Any]:
    """
    Run a skill via the `claude` CLI and return a session dict.

    Invokes: claude --print --model <model> --output-format stream-json
                    --no-session-persistence /<skill_name> [arguments]

    Returns:
        {
            "model": str,
            "skill": str,
            "arguments": str,
            "tool_calls": list[dict],   # {name, input, output}
            "final_text": str,
            "input_tokens": int,
            "output_tokens": int,
            "turn_count": int,
            "error": str | None,
        }

    Raises:
        ValueError: if skill_name, arguments, or model fail validation.
    """
    if not _SAFE_SKILL_NAME.match(skill_name):
        raise ValueError(f"Invalid skill_name: {skill_name!r}")
    if arguments and not _SAFE_ARGUMENTS.match(arguments):
        raise ValueError(f"Unsafe characters in arguments: {arguments!r}")
    if model not in _ALLOWED_MODELS:
        raise ValueError(f"Model not in allowlist: {model!r}")

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
        "claude", "--print",
        "--verbose",
        "--model", model,
        "--output-format", "stream-json",
        "--no-session-persistence",
        prompt,
    ]
    # On Windows, invoke node.exe + cli.js directly (bypasses cmd.exe wrapper)
    # so Python holds a direct handle to the Claude process and can kill it
    # cleanly on timeout without pipe deadlocks.
    direct = _claude_direct_cmd()
    if direct is not None:
        cmd = direct + claude_args[1:]  # drop "claude" from the front of claude_args
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
            timeout=SESSION_TIMEOUT,
            cwd=str(PROJECT_ROOT),
            env=env,
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
        session["error"] = f"claude CLI timed out after {SESSION_TIMEOUT}s"
        return session
    except FileNotFoundError:
        session["error"] = "claude CLI not found — ensure it is installed and on PATH"
        return session
    except OSError as e:
        session["error"] = f"OS error launching claude CLI: {e}"
        return session

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
                                b.get("text", "") for b in raw_output if isinstance(b, dict)
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
    # stream or premature CLI exit).  Record them so scoring counts them correctly.
    for orphan in pending_tool_uses.values():
        session["tool_calls"].append({
            "name": orphan["name"],
            "input": str(orphan["input"]),
            "output": "[INCOMPLETE — no tool_result received]",
        })
    if pending_tool_uses and session["error"] is None:
        session["error"] = (
            f"Stream ended with {len(pending_tool_uses)} unmatched tool_use block(s)"
        )

    return session
