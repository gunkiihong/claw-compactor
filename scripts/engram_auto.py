#!/usr/bin/env python3
"""
engram_auto.py — Automated multi-channel Engram session ingestion.

Scans OpenClaw session JSONL files, detects which Discord channel / cron job /
subagent they belong to, converts them to Engram format, and ingests them
concurrently using a ThreadPoolExecutor.

Usage:
    python3 scripts/engram_auto.py [--config engram.yaml] [--workspace PATH]
                                   [--once | --daemon] [--dry-run]

Part of claw-compactor / Engram layer. License: MIT.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Ensure scripts/ is on path when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.config import load_engram_config, engram_engine_kwargs
from lib.engram import EngramEngine
from lib.engram_storage import EngramStorage

logger = logging.getLogger("engram_auto")


# ---------------------------------------------------------------------------
# Thread-ID detection
# ---------------------------------------------------------------------------

# Channel-name → thread-id mapping
_CHANNEL_MAP: Dict[str, str] = {
    "general": "discord-general",
    "open-compress": "discord-open-compress",
    "opencompress": "discord-open-compress",
    "aimm": "discord-aimm",
}

_RE_CHANNEL_NAME = re.compile(r"#([\w][\w-]*)")
_RE_CHANNEL_ID = re.compile(r"channel id:(\d+)")
_RE_CRON = re.compile(r'cron job["\s]+([^"\s]+)', re.IGNORECASE)
_RE_SUBAGENT = re.compile(r"subagent", re.IGNORECASE)


def detect_thread_id(session_file: Path) -> str:
    """
    Detect the thread/channel this session belongs to by inspecting its content.

    Reads up to the first 10 user/system messages and applies heuristics:
      - Discord channel name → discord-{name}
      - cron job name        → cron-{job_name}
      - subagent context     → subagent
      - fallback             → openclaw-main

    Args:
        session_file: Path to the session JSONL file.

    Returns:
        Thread-ID string suitable for use as Engram thread identifier.
    """
    try:
        lines_checked = 0
        messages_checked = 0

        with session_file.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if messages_checked >= 10:
                    break
                raw = raw.strip()
                if not raw:
                    continue
                lines_checked += 1
                if lines_checked > 200:
                    # Don't scan forever through non-message lines
                    break

                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                # Collect text from user/system messages and metadata
                role = ""
                text = ""

                if obj.get("type") == "message":
                    msg = obj.get("message", {})
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    text = _extract_text(content)
                elif "role" in obj:
                    role = obj.get("role", "")
                    text = _extract_text(obj.get("content", ""))
                else:
                    # Could be a metadata / system line
                    text = raw

                if role not in ("user", "system", ""):
                    continue

                messages_checked += 1
                if not text:
                    continue

                # --- subagent check (high priority) ---
                if _RE_SUBAGENT.search(text):
                    return "subagent"

                # --- cron job check ---
                m = _RE_CRON.search(text)
                if m:
                    job_name = m.group(1).strip('"\'').strip()
                    return f"cron-{job_name}"

                # --- Discord channel name ---
                for ch_match in _RE_CHANNEL_NAME.finditer(text):
                    ch_name = ch_match.group(1).lower()
                    if ch_name in _CHANNEL_MAP:
                        return _CHANNEL_MAP[ch_name]
                    # Generic discord channel
                    if _RE_CHANNEL_ID.search(text):
                        return f"discord-{ch_name}"

    except OSError as exc:
        logger.warning("detect_thread_id: cannot read %s: %s", session_file, exc)

    return "openclaw-main"


def _extract_text(content: object) -> str:
    """Flatten content (str, list of blocks) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif "text" in block:
                    parts.append(str(block["text"]))
        return "\n".join(parts)
    return str(content)


# ---------------------------------------------------------------------------
# Session → Engram format conversion
# ---------------------------------------------------------------------------

def convert_session(session_file: Path, output_file: Path) -> int:
    """
    Convert an OpenClaw session JSONL to Engram-format JSONL.

    Returns the number of messages written.
    """
    count = 0
    with session_file.open("r", encoding="utf-8", errors="replace") as fin, \
            output_file.open("w", encoding="utf-8") as fout:
        for raw in fin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if obj.get("type") != "message":
                continue

            msg = obj.get("message", {})
            role = msg.get("role", "")
            if role not in ("user", "assistant"):
                continue

            text = _extract_text(msg.get("content", ""))
            if not text.strip():
                continue

            out: Dict[str, object] = {"role": role, "content": text}
            ts = obj.get("timestamp", "")
            if ts:
                out["timestamp"] = ts

            fout.write(json.dumps(out, ensure_ascii=False) + "\n")
            count += 1

    return count


# ---------------------------------------------------------------------------
# Per-thread lock registry
# ---------------------------------------------------------------------------

class _LockRegistry:
    """Thread-safe registry of per-thread-id locks."""

    def __init__(self) -> None:
        self._locks: Dict[str, threading.Lock] = {}
        self._meta = threading.Lock()

    def get(self, thread_id: str) -> threading.Lock:
        with self._meta:
            if thread_id not in self._locks:
                self._locks[thread_id] = threading.Lock()
            return self._locks[thread_id]


# ---------------------------------------------------------------------------
# Auto-runner
# ---------------------------------------------------------------------------

class EngramAutoRunner:
    """
    Scan sessions, detect channels, convert, and ingest concurrently.

    Args:
        workspace:    Workspace root (Engram stores data under memory/engram/).
        engram_cfg:   Output of load_engram_config().
        dry_run:      If True, detect and convert but do not call LLM or write.
    """

    def __init__(
        self,
        workspace: Path,
        engram_cfg: Dict,
        dry_run: bool = False,
    ) -> None:
        self.workspace = workspace
        self.cfg = engram_cfg
        self.dry_run = dry_run

        self.scan_dir = Path(engram_cfg["sessions"]["scan_dir"])
        self.max_age_hours: int = int(engram_cfg["sessions"].get("max_age_hours", 48))
        self.max_workers: int = int(engram_cfg["concurrency"].get("max_workers", 4))
        self.storage_base = Path(engram_cfg["storage"]["base_dir"])

        self._lock_reg = _LockRegistry()

        # Processed-sessions marker lives next to the storage root
        self.storage_base.mkdir(parents=True, exist_ok=True)
        self._processed_marker = self.storage_base / ".processed_sessions"
        self._processed_cache: set = self._load_processed()
        self._processed_lock = threading.Lock()

        # Engine kwargs (shared config; each thread constructs its own engine
        # instance to avoid cross-thread state issues)
        self._engine_kwargs = engram_engine_kwargs(engram_cfg)

    # ------------------------------------------------------------------ #
    # Processed-sessions bookkeeping                                      #
    # ------------------------------------------------------------------ #

    def _load_processed(self) -> set:
        if not self._processed_marker.exists():
            return set()
        return set(self._processed_marker.read_text(encoding="utf-8").splitlines())

    def _is_processed(self, cache_key: str) -> bool:
        with self._processed_lock:
            return cache_key in self._processed_cache

    def _mark_processed(self, cache_key: str) -> None:
        with self._processed_lock:
            if cache_key not in self._processed_cache:
                self._processed_cache.add(cache_key)
                with self._processed_marker.open("a", encoding="utf-8") as f:
                    f.write(cache_key + "\n")

    # ------------------------------------------------------------------ #
    # Session discovery                                                   #
    # ------------------------------------------------------------------ #

    def find_sessions(self) -> List[Path]:
        """Return session JSONL files modified within max_age_hours."""
        if not self.scan_dir.exists():
            logger.warning("Sessions dir not found: %s", self.scan_dir)
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.max_age_hours)
        sessions: List[Path] = []

        for p in sorted(self.scan_dir.rglob("*.jsonl")):
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                if mtime >= cutoff:
                    sessions.append(p)
            except OSError:
                pass

        logger.info("Found %d recent session file(s) in %s", len(sessions), self.scan_dir)
        return sessions

    # ------------------------------------------------------------------ #
    # Per-session processing                                              #
    # ------------------------------------------------------------------ #

    def _process_session(self, session_file: Path, tmp_dir: Path) -> Tuple[str, str, int]:
        """
        Process a single session file.

        Returns (session_id, thread_id, messages_ingested).
        """
        session_id = session_file.stem
        mtime = int(session_file.stat().st_mtime)
        cache_key = f"{session_id}:{mtime}"

        if self._is_processed(cache_key):
            logger.debug("Skip (unchanged): %s", session_id)
            return session_id, "", 0

        # Detect channel
        thread_id = detect_thread_id(session_file)
        logger.info("Session %s → thread '%s'", session_id, thread_id)

        if self.dry_run:
            self._mark_processed(cache_key)
            return session_id, thread_id, 0

        # Convert
        tmp_out = tmp_dir / f"{session_id}.jsonl"
        msg_count = convert_session(session_file, tmp_out)
        if msg_count == 0:
            logger.info("  No messages extracted from %s", session_id)
            self._mark_processed(cache_key)
            return session_id, thread_id, 0

        # Ingest (with per-thread lock to protect file writes)
        lock = self._lock_reg.get(thread_id)

        # Compute workspace root from storage base:
        # storage_base = {workspace}/memory/engram  OR an absolute custom path.
        # EngramEngine wants workspace_path such that it appends memory/engram/ itself.
        # So workspace = storage_base.parent.parent if using default layout,
        # but to be safe we always pass self.workspace.
        engine = EngramEngine(workspace_path=self.workspace, **self._engine_kwargs)

        # Read messages
        messages: List[Dict] = []
        try:
            with tmp_out.open("r", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if raw:
                        try:
                            messages.append(json.loads(raw))
                        except json.JSONDecodeError:
                            pass
        except OSError as exc:
            logger.error("  Cannot read converted file %s: %s", tmp_out, exc)
            return session_id, thread_id, 0

        # Write to storage under lock
        with lock:
            ingested = 0
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                timestamp = msg.get("timestamp")
                if content:
                    engine.add_message(thread_id, role=role, content=content, timestamp=timestamp)
                    ingested += 1

        self._mark_processed(cache_key)
        logger.info("  ✓ Ingested %d messages into thread '%s'", ingested, thread_id)
        return session_id, thread_id, ingested

    # ------------------------------------------------------------------ #
    # Run                                                                 #
    # ------------------------------------------------------------------ #

    def run_once(self) -> Dict[str, int]:
        """
        Process all pending sessions concurrently.

        Returns a dict mapping thread_id → total messages ingested.
        """
        sessions = self.find_sessions()
        if not sessions:
            logger.info("No recent sessions to process.")
            return {}

        totals: Dict[str, int] = {}
        totals_lock = threading.Lock()

        with tempfile.TemporaryDirectory(prefix="engram_auto_") as tmp_str:
            tmp_dir = Path(tmp_str)

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.max_workers, thread_name_prefix="engram"
            ) as executor:
                futures = {
                    executor.submit(self._process_session, sf, tmp_dir): sf
                    for sf in sessions
                }
                for fut in concurrent.futures.as_completed(futures):
                    sf = futures[fut]
                    try:
                        _, thread_id, count = fut.result()
                        if thread_id and count > 0:
                            with totals_lock:
                                totals[thread_id] = totals.get(thread_id, 0) + count
                    except Exception as exc:  # noqa: BLE001
                        logger.error("Error processing %s: %s", sf, exc)

        return totals

    def run_daemon(self, interval_seconds: int = 900) -> None:
        """Run run_once() in a loop, sleeping *interval_seconds* between runs."""
        logger.info("Engram daemon started (interval=%ds)", interval_seconds)
        while True:
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001
                logger.error("run_once error: %s", exc)
            logger.info("Sleeping %ds until next run…", interval_seconds)
            time.sleep(interval_seconds)


# ---------------------------------------------------------------------------
# Engram status helper
# ---------------------------------------------------------------------------

def print_status(workspace: Path, engram_cfg: Dict) -> None:
    """Print Engram status for all known threads."""
    from lib.engram_storage import EngramStorage
    storage = EngramStorage(workspace)
    threads = storage.list_threads()
    if not threads:
        print("No Engram threads found.")
        return
    print(f"{'Thread':<28} {'Pending':>7} {'Obs tok':>8} {'Ref tok':>8} {'Total':>8}")
    print("─" * 65)
    from lib.tokens import estimate_tokens
    for tid in threads:
        pending = storage.read_pending(tid)
        obs = storage.read_observations(tid)
        ref = storage.read_reflection(tid)
        from lib.engram import _count_messages_tokens
        pt = _count_messages_tokens(pending)
        ot = estimate_tokens(obs)
        rt = estimate_tokens(ref)
        print(f"{tid:<28} {len(pending):>7} {ot:>8,} {rt:>8,} {pt+ot+rt:>8,}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="engram_auto.py",
        description="Engram Auto-Runner — multi-channel concurrent session ingestion",
    )
    p.add_argument(
        "--workspace",
        default=None,
        help="Workspace root (default: auto-detected from config storage.base_dir)",
    )
    p.add_argument(
        "--config",
        default=None,
        help="Path to engram.yaml / engram.json (default: auto-detect)",
    )
    p.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously (every 15 minutes)",
    )
    p.add_argument(
        "--interval",
        type=int,
        default=900,
        help="Daemon sleep interval in seconds (default: 900)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Detect channels and convert but do not ingest",
    )
    p.add_argument(
        "--status",
        action="store_true",
        help="Print Engram thread status and exit",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    cfg_path = Path(args.config).expanduser() if args.config else None
    engram_cfg = load_engram_config(cfg_path)

    # Derive workspace from storage base dir
    # storage.base_dir = {workspace}/memory/engram  (by convention)
    # So workspace = storage_base.parent.parent
    storage_base = Path(engram_cfg["storage"]["base_dir"])
    if args.workspace:
        workspace = Path(args.workspace).expanduser().resolve()
    else:
        # If storage base follows the convention, go up two levels; otherwise use cwd
        if storage_base.name == "engram" and storage_base.parent.name == "memory":
            workspace = storage_base.parent.parent
        else:
            workspace = Path.cwd()

    if args.status:
        print_status(workspace, engram_cfg)
        return

    runner = EngramAutoRunner(
        workspace=workspace,
        engram_cfg=engram_cfg,
        dry_run=args.dry_run,
    )

    if args.daemon:
        runner.run_daemon(interval_seconds=args.interval)
    else:
        totals = runner.run_once()
        if totals:
            print("Ingestion summary:")
            for tid, count in sorted(totals.items()):
                print(f"  {tid}: {count} messages")
        else:
            print("Nothing to ingest (all sessions up to date).")


if __name__ == "__main__":
    main()
