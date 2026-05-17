"""
LLM wrapper. Supports two backends:
  claude  (default) — local claude CLI via async subprocess, no API key needed
  moonshot          — Moonshot API via urllib, set LLM_BACKEND=moonshot in env

Set LLM_BACKEND=moonshot on VPS where claude CLI is unavailable.
"""

import asyncio
import json
import logging
import os
import urllib.request
import urllib.error
from typing import Any

from config import CLAUDE_CLI_PATH, CLAUDE_MODEL, CLAUDE_MAX_TOKENS

logger = logging.getLogger(__name__)

LLM_BACKEND = os.environ.get("LLM_BACKEND", "claude")  # "claude" | "moonshot"
_MOONSHOT_API_KEY = os.environ.get("MOONSHOT_API_KEY", "")
_MOONSHOT_URL = "https://api.moonshot.cn/v1/chat/completions"
_MOONSHOT_MODEL = "moonshot-v1-8k"


def _moonshot_request(system: str, user: str, max_tokens: int, temperature: float) -> str:
    """Synchronous Moonshot API call — run via asyncio.to_thread()."""
    if not _MOONSHOT_API_KEY:
        raise RuntimeError("MOONSHOT_API_KEY not set — cannot use moonshot backend")
    payload = json.dumps({
        "model": _MOONSHOT_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode("utf-8")
    req = urllib.request.Request(
        _MOONSHOT_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_MOONSHOT_API_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Moonshot API HTTP {exc.code}: {body}") from exc


async def call_claude(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = CLAUDE_MAX_TOKENS,
    temperature: float = 0.7,
) -> str:
    """
    Call LLM asynchronously. Routes to Moonshot or local Claude CLI based on LLM_BACKEND.
    Returns the text response.
    """
    if LLM_BACKEND == "moonshot":
        return await asyncio.to_thread(
            _moonshot_request, system_prompt, user_prompt, max_tokens, temperature
        )
    return await _call_claude_cli(system_prompt, user_prompt, max_tokens)


async def _call_claude_cli(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
) -> str:
    """Call local Claude CLI via async subprocess."""
    cmd = [
        CLAUDE_CLI_PATH,
        "-p", user_prompt,
        "--model", CLAUDE_MODEL,
        "--output-format", "text",
    ]

    # Pass system prompt via --system-prompt if available
    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=120
        )

        if process.returncode != 0:
            stderr_text = stderr.decode("utf-8").strip()
            # Fallback: if --system-prompt is not supported, prepend to user prompt
            if "system-prompt" in stderr_text.lower() or "unknown" in stderr_text.lower():
                logger.warning("--system-prompt not supported, falling back to inline")
                return await _call_claude_fallback(
                    system_prompt, user_prompt, max_tokens
                )
            logger.error("Claude CLI error (exit %d): %s", process.returncode, stderr_text)
            raise RuntimeError(f"Claude CLI failed: {stderr_text}")

        response = stdout.decode("utf-8").strip()
        if not response:
            raise RuntimeError("Claude CLI returned empty response")

        return response

    except asyncio.TimeoutError:
        logger.error("Claude CLI timed out after 120s")
        raise
    except FileNotFoundError:
        logger.error("Claude CLI not found at: %s", CLAUDE_CLI_PATH)
        raise RuntimeError(
            f"Claude CLI not found. Install it or update CLAUDE_CLI_PATH in config.py. "
            f"Current path: {CLAUDE_CLI_PATH}"
        )


async def _call_claude_fallback(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
) -> str:
    """Fallback: prepend system prompt as context in the user prompt."""
    combined_prompt = f"""<context role="system">
{system_prompt}
</context>

{user_prompt}"""

    cmd = [
        CLAUDE_CLI_PATH,
        "-p", combined_prompt,
        "--model", CLAUDE_MODEL,
        "--output-format", "text",
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await asyncio.wait_for(
        process.communicate(), timeout=120
    )

    if process.returncode != 0:
        stderr_text = stderr.decode("utf-8").strip()
        raise RuntimeError(f"Claude CLI fallback failed: {stderr_text}")

    response = stdout.decode("utf-8").strip()
    if not response:
        raise RuntimeError("Claude CLI returned empty response")

    return response


async def call_claude_json(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = CLAUDE_MAX_TOKENS,
    temperature: float = 0.3,
) -> dict[str, Any]:
    """
    Call Claude CLI and parse response as JSON.
    Appends JSON-only instruction to system prompt.
    """
    json_system = system_prompt + "\n\nRespond with valid JSON only. No markdown code fences, no explanation, just the JSON object."

    response = await call_claude(
        system_prompt=json_system,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    # Strip markdown code fences if present
    cleaned = response.strip()
    if cleaned.startswith("```"):
        # Remove first line (```json or ```)
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    # Try to find JSON object in the response
    if not cleaned.startswith("{") and not cleaned.startswith("["):
        # Look for first { or [
        brace_idx = cleaned.find("{")
        bracket_idx = cleaned.find("[")
        if brace_idx >= 0 and (bracket_idx < 0 or brace_idx < bracket_idx):
            cleaned = cleaned[brace_idx:]
        elif bracket_idx >= 0:
            cleaned = cleaned[bracket_idx:]

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("Failed to parse Claude JSON: %s", cleaned[:300])
        raise ValueError(f"Invalid JSON from Claude CLI: {cleaned[:300]}")


async def call_claude_with_file(
    system_prompt: str,
    user_prompt: str,
    file_path: str = "",
    max_tokens: int = CLAUDE_MAX_TOKENS,
) -> str:
    """
    Call Claude CLI with a file as additional context.
    Useful for analyzing screenshots or documents.
    """
    cmd = [
        CLAUDE_CLI_PATH,
        "-p", user_prompt,
        "--model", CLAUDE_MODEL,
        "--output-format", "text",
    ]

    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])

    if file_path:
        cmd.extend(["--file", file_path])

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=120
        )

        if process.returncode != 0:
            stderr_text = stderr.decode("utf-8").strip()
            # Fallback if --system-prompt not supported
            if "system-prompt" in stderr_text.lower():
                combined = f"<context role='system'>\n{system_prompt}\n</context>\n\n{user_prompt}"
                cmd2 = [
                    CLAUDE_CLI_PATH, "-p", combined,
                    "--model", CLAUDE_MODEL,
                    "--output-format", "text",
                ]
                if file_path:
                    cmd2.extend(["--file", file_path])
                proc2 = await asyncio.create_subprocess_exec(
                    *cmd2, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                out2, err2 = await asyncio.wait_for(proc2.communicate(), timeout=120)
                if proc2.returncode != 0:
                    raise RuntimeError(f"Claude CLI failed: {err2.decode().strip()}")
                return out2.decode("utf-8").strip()
            raise RuntimeError(f"Claude CLI failed: {stderr_text}")

        return stdout.decode("utf-8").strip()

    except asyncio.TimeoutError:
        logger.error("Claude CLI timed out")
        raise
