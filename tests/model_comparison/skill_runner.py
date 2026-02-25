"""
Core agentic loop for running a slash-command skill against a real Claude model.

Loads the skill .md file, substitutes $ARGUMENTS, then drives a multi-turn
tool-use loop until the model reaches end_turn or the turn limit is hit.
Real Bash and Read tool calls are executed via subprocess / file I/O.

SECURITY NOTE: This runner executes bash commands emitted by the model. Only
commands whose first token matches _BASH_ALLOWLIST are permitted, which limits
the blast radius of prompt-injection attacks. Do not run with elevated privileges.
"""

import subprocess
from pathlib import Path
from typing import Any

import anthropic

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
COMMANDS_DIR = PROJECT_ROOT / ".claude" / "commands"
MAX_TURNS = 20
BASH_TIMEOUT = 120  # seconds
MAX_TOKENS = 4096

# Allow only commands that invoke the project Python interpreter or project scripts.
# Commands not starting with one of these prefixes are blocked.
_BASH_ALLOWLIST = (
    "/c/Users/johnb/Advocacy/tdranalysis/venv/Scripts/python",
    "python ",
    "python3 ",
)


def _load_skill(skill_name: str, arguments: str) -> str:
    """Load skill .md and substitute $ARGUMENTS."""
    skill_path = COMMANDS_DIR / f"{skill_name}.md"
    content = skill_path.read_text(encoding="utf-8")
    return content.replace("$ARGUMENTS", arguments)


def _execute_bash(command: str) -> str:
    """Execute a bash command and return combined stdout+stderr.

    Only commands matching _BASH_ALLOWLIST prefixes are executed; all others
    are blocked and return an error string.
    """
    stripped = command.strip()
    if not any(stripped.startswith(prefix) for prefix in _BASH_ALLOWLIST):
        return f"[BLOCKED] Command not in allowlist: {stripped[:120]!r}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=BASH_TIMEOUT,
            cwd=str(PROJECT_ROOT),
        )
        output = result.stdout
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"[ERROR] Command timed out after {BASH_TIMEOUT}s"
    except OSError as e:
        return f"[ERROR] OS error running command: {e}"


def _execute_read(file_path: str) -> str:
    """Read a file and return its contents.

    Resolves relative paths against PROJECT_ROOT and rejects paths that
    resolve outside the project tree to prevent path traversal.
    """
    try:
        p = Path(file_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        resolved = p.resolve()
        if not str(resolved).startswith(str(PROJECT_ROOT)):
            return f"[BLOCKED] Path outside project root: {file_path!r}"
        return resolved.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError) as e:
        return f"[ERROR reading {file_path}] {e}"
    except UnicodeDecodeError as e:
        return f"[ERROR reading {file_path}] Encoding error: {e}"


def _make_tools() -> list[dict[str, Any]]:
    """Return the tool definitions sent to the model."""
    return [
        {
            "name": "Bash",
            "description": (
                f"Execute a bash command in the project root ({PROJECT_ROOT}). "
                "Returns stdout and stderr."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to execute.",
                    }
                },
                "required": ["command"],
            },
        },
        {
            "name": "Read",
            "description": "Read a file from the filesystem and return its contents.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute or project-relative path to the file.",
                    }
                },
                "required": ["file_path"],
            },
        },
    ]


def run_skill(
    skill_name: str,
    arguments: str,
    model: str,
    api_key: str,
) -> dict[str, Any]:
    """
    Run a skill against the given model and return a session dict.

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
    """
    client = anthropic.Anthropic(api_key=api_key)
    system_prompt = _load_skill(skill_name, arguments)
    tools = _make_tools()

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": f"Run the skill with arguments: {arguments!r}"}
    ]

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

    try:
        for _turn in range(MAX_TURNS):
            session["turn_count"] += 1

            response = client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                tools=tools,
                messages=messages,
            )

            session["input_tokens"] += response.usage.input_tokens
            session["output_tokens"] += response.usage.output_tokens

            # Collect assistant message content
            assistant_content = []
            tool_use_blocks = []

            for block in response.content:
                if block.type == "tool_use":
                    tool_use_blocks.append(block)
                    assistant_content.append(block)
                elif block.type == "text":
                    assistant_content.append(block)
                    session["final_text"] = block.text  # keep last text block

            # Add assistant turn to messages
            messages.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason == "tool_use":
                # Execute each tool call and collect results
                tool_results = []
                for tu in tool_use_blocks:
                    tool_input = tu.input if isinstance(tu.input, dict) else {}
                    if tu.name == "Bash":
                        cmd = tool_input.get("command", "")
                        output = _execute_bash(cmd)
                        session["tool_calls"].append(
                            {"name": "Bash", "input": cmd, "output": output}
                        )
                    elif tu.name == "Read":
                        fp = tool_input.get("file_path", "")
                        output = _execute_read(fp)
                        session["tool_calls"].append(
                            {"name": "Read", "input": fp, "output": output}
                        )
                    else:
                        output = f"[Unknown tool: {tu.name}]"
                        session["tool_calls"].append(
                            {"name": tu.name, "input": str(tool_input), "output": output}
                        )

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": output,
                        }
                    )

                messages.append({"role": "user", "content": tool_results})

        else:
            session["error"] = f"Reached max turns ({MAX_TURNS}) without end_turn"

    except Exception as e:  # noqa: BLE001 — intentional: capture all API/network errors into session
        session["error"] = str(e)

    return session
