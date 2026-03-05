"""
tests/test_engram_auto.py — Tests for multi-channel auto-discovery,
unified config, and concurrent processing (Engram Layer 6 refactor).

Run with:
    pytest tests/test_engram_auto.py -v

Part of claw-compactor / Engram layer. License: MIT.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts/ is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from lib.config import load_engram_config, engram_engine_kwargs, _load_dotenv, _deep_merge
from engram_auto import detect_thread_id, convert_session, EngramAutoRunner, _extract_text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def sessions_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sessions"
    d.mkdir()
    return d


def _write_session(sessions_dir: Path, name: str, lines: List[dict]) -> Path:
    """Write a mock session JSONL file."""
    p = sessions_dir / f"{name}.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    return p


def _make_openclaw_msg(role: str, text: str, ts: str = "") -> dict:
    """Build an OpenClaw-format session message."""
    msg: dict = {
        "type": "message",
        "message": {
            "role": role,
            "content": [{"type": "text", "text": text}],
        },
    }
    if ts:
        msg["timestamp"] = ts
    return msg


# ---------------------------------------------------------------------------
# Test 1: detect_thread_id — channel detection
# ---------------------------------------------------------------------------

class TestDetectThreadId:
    """detect_thread_id() should correctly map sessions to thread IDs."""

    def test_discord_general(self, sessions_dir: Path) -> None:
        p = _write_session(sessions_dir, "s1", [
            _make_openclaw_msg("user",
                "You are in [Discord Guild #general channel id:1470169146539901001]"),
        ])
        assert detect_thread_id(p) == "discord-general"

    def test_discord_open_compress(self, sessions_dir: Path) -> None:
        p = _write_session(sessions_dir, "s2", [
            _make_openclaw_msg("user",
                "Context: [Discord Guild #open-compress channel id:1476885945163714641]"),
        ])
        assert detect_thread_id(p) == "discord-open-compress"

    def test_discord_aimm(self, sessions_dir: Path) -> None:
        p = _write_session(sessions_dir, "s3", [
            _make_openclaw_msg("user",
                "Channel: [Discord Guild #aimm channel id:1234567890]"),
        ])
        assert detect_thread_id(p) == "discord-aimm"

    def test_cron_job(self, sessions_dir: Path) -> None:
        p = _write_session(sessions_dir, "s4", [
            _make_openclaw_msg("system",
                'A cron job "cortex-tick" has fired.'),
        ])
        assert detect_thread_id(p) == "cron-cortex-tick"

    def test_subagent(self, sessions_dir: Path) -> None:
        p = _write_session(sessions_dir, "s5", [
            _make_openclaw_msg("system", "You are running as a subagent (depth 1/1)."),
        ])
        assert detect_thread_id(p) == "subagent"

    def test_fallback_openclaw_main(self, sessions_dir: Path) -> None:
        p = _write_session(sessions_dir, "s6", [
            _make_openclaw_msg("user", "Hello, this is a random message."),
        ])
        assert detect_thread_id(p) == "openclaw-main"

    def test_empty_session(self, sessions_dir: Path) -> None:
        p = sessions_dir / "empty.jsonl"
        p.write_text("")
        assert detect_thread_id(p) == "openclaw-main"

    def test_nonexistent_session(self, sessions_dir: Path) -> None:
        p = sessions_dir / "nonexistent.jsonl"
        # Should not raise, returns default
        result = detect_thread_id(p)
        assert result == "openclaw-main"

    def test_subagent_takes_priority(self, sessions_dir: Path) -> None:
        """subagent detection should override channel name if both present."""
        p = _write_session(sessions_dir, "s7", [
            _make_openclaw_msg("system",
                "You are a subagent in [Discord Guild #general channel id:111]"),
        ])
        assert detect_thread_id(p) == "subagent"

    def test_generic_discord_channel(self, sessions_dir: Path) -> None:
        """Unknown channel name with channel id should become discord-{name}."""
        p = _write_session(sessions_dir, "s8", [
            _make_openclaw_msg("user",
                "[Discord Guild #mychannel channel id:9999]"),
        ])
        result = detect_thread_id(p)
        assert result == "discord-mychannel"


# ---------------------------------------------------------------------------
# Test 2: convert_session — format conversion
# ---------------------------------------------------------------------------

class TestConvertSession:
    """convert_session() should produce valid Engram-format JSONL."""

    def test_basic_conversion(self, tmp_path: Path) -> None:
        session = tmp_path / "sess.jsonl"
        session.write_text(
            json.dumps(_make_openclaw_msg("user", "Hello world")) + "\n" +
            json.dumps(_make_openclaw_msg("assistant", "Hi there")) + "\n"
        )
        out = tmp_path / "out.jsonl"
        count = convert_session(session, out)

        assert count == 2
        lines = out.read_text().splitlines()
        assert len(lines) == 2
        msg0 = json.loads(lines[0])
        assert msg0["role"] == "user"
        assert msg0["content"] == "Hello world"

    def test_skips_non_message_events(self, tmp_path: Path) -> None:
        session = tmp_path / "sess.jsonl"
        session.write_text(
            json.dumps({"type": "system_event", "data": "boot"}) + "\n" +
            json.dumps(_make_openclaw_msg("user", "Real message")) + "\n"
        )
        out = tmp_path / "out.jsonl"
        count = convert_session(session, out)
        assert count == 1

    def test_skips_empty_content(self, tmp_path: Path) -> None:
        session = tmp_path / "sess.jsonl"
        obj = {"type": "message", "message": {"role": "user", "content": ""}}
        session.write_text(json.dumps(obj) + "\n")
        out = tmp_path / "out.jsonl"
        count = convert_session(session, out)
        assert count == 0

    def test_preserves_timestamp(self, tmp_path: Path) -> None:
        session = tmp_path / "sess.jsonl"
        obj = _make_openclaw_msg("user", "With timestamp")
        obj["timestamp"] = "2026-03-05T12:00:00Z"
        session.write_text(json.dumps(obj) + "\n")
        out = tmp_path / "out.jsonl"
        convert_session(session, out)
        msg = json.loads(out.read_text())
        assert msg["timestamp"] == "2026-03-05T12:00:00Z"

    def test_skips_corrupt_lines(self, tmp_path: Path) -> None:
        session = tmp_path / "sess.jsonl"
        session.write_text(
            "NOT JSON\n" +
            json.dumps(_make_openclaw_msg("user", "Good message")) + "\n"
        )
        out = tmp_path / "out.jsonl"
        count = convert_session(session, out)
        assert count == 1


# ---------------------------------------------------------------------------
# Test 3: _extract_text
# ---------------------------------------------------------------------------

class TestExtractText:
    def test_string_passthrough(self) -> None:
        assert _extract_text("hello") == "hello"

    def test_list_of_text_blocks(self) -> None:
        blocks = [{"type": "text", "text": "Hello"}, {"type": "text", "text": "World"}]
        result = _extract_text(blocks)
        assert "Hello" in result
        assert "World" in result

    def test_list_of_strings(self) -> None:
        result = _extract_text(["foo", "bar"])
        assert "foo" in result and "bar" in result

    def test_non_text_blocks_ignored(self) -> None:
        blocks = [{"type": "tool_use", "name": "bash"}, {"type": "text", "text": "hi"}]
        result = _extract_text(blocks)
        assert "hi" in result

    def test_fallback_to_str(self) -> None:
        result = _extract_text(42)
        assert result == "42"


# ---------------------------------------------------------------------------
# Test 4: load_engram_config
# ---------------------------------------------------------------------------

class TestLoadEngramConfig:
    """Config loading: yaml file, env overrides, defaults."""

    def test_loads_defaults_without_file(self, tmp_path: Path, monkeypatch) -> None:
        # Point away from real engram.yaml
        monkeypatch.setenv("ENGRAM_CONFIG", str(tmp_path / "nonexistent.yaml"))
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        cfg = load_engram_config()
        assert "llm" in cfg
        assert "threads" in cfg
        assert "sessions" in cfg
        assert "storage" in cfg
        assert "concurrency" in cfg

    def test_env_var_overrides(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("ENGRAM_CONFIG", str(tmp_path / "nonexistent.yaml"))
        monkeypatch.setenv("ENGRAM_MODEL", "my-test-model")
        monkeypatch.setenv("ENGRAM_OBSERVER_THRESHOLD", "12345")
        monkeypatch.setenv("ENGRAM_MAX_WORKERS", "8")
        cfg = load_engram_config()
        assert cfg["llm"]["model"] == "my-test-model"
        assert cfg["threads"]["default"]["observer_threshold"] == 12345
        assert cfg["concurrency"]["max_workers"] == 8

    def test_yaml_file_loaded(self, tmp_path: Path, monkeypatch) -> None:
        yaml_content = """
llm:
  model: test-model-from-yaml
  max_tokens: 1234
threads:
  default:
    observer_threshold: 5000
"""
        yaml_path = tmp_path / "engram.yaml"
        yaml_path.write_text(yaml_content)
        # Suppress .env loading by pointing to a nonexistent .env inside config.py's
        # root detection. We do this by patching _load_dotenv to a no-op for this test.
        # Also clear any lingering env-var overrides.
        monkeypatch.delenv("ENGRAM_MODEL", raising=False)
        monkeypatch.delenv("ENGRAM_MAX_TOKENS", raising=False)
        monkeypatch.delenv("ENGRAM_OBSERVER_THRESHOLD", raising=False)
        # Prevent .env from re-setting ENGRAM_MODEL during this call
        with patch("lib.config._load_dotenv"):
            cfg = load_engram_config(yaml_path)
        assert cfg["llm"]["model"] == "test-model-from-yaml"
        assert cfg["llm"]["max_tokens"] == 1234
        assert cfg["threads"]["default"]["observer_threshold"] == 5000

    def test_json_fallback(self, tmp_path: Path, monkeypatch) -> None:
        json_data = {
            "llm": {"model": "from-json", "max_tokens": 999},
            "threads": {"default": {"observer_threshold": 7777}},
        }
        json_path = tmp_path / "engram.json"
        json_path.write_text(json.dumps(json_data))
        # Clear env-var overrides; suppress .env re-population
        monkeypatch.delenv("ENGRAM_MODEL", raising=False)
        monkeypatch.delenv("ENGRAM_MAX_TOKENS", raising=False)
        monkeypatch.delenv("ENGRAM_OBSERVER_THRESHOLD", raising=False)
        with patch("lib.config._load_dotenv"):
            cfg = load_engram_config(json_path)
        assert cfg["llm"]["model"] == "from-json"
        assert cfg["threads"]["default"]["observer_threshold"] == 7777

    def test_paths_expanded(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("ENGRAM_STORAGE_DIR", "~/my/custom/path")
        monkeypatch.setenv("ENGRAM_CONFIG", str(tmp_path / "nonexistent.yaml"))
        cfg = load_engram_config()
        assert "~" not in cfg["storage"]["base_dir"]
        assert "my/custom/path" in cfg["storage"]["base_dir"]

    def test_deep_merge(self) -> None:
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 99, "z": 100}, "c": 4}
        result = _deep_merge(base, override)
        assert result["a"]["x"] == 1   # preserved from base
        assert result["a"]["y"] == 99  # overridden
        assert result["a"]["z"] == 100  # new from override
        assert result["b"] == 3        # untouched
        assert result["c"] == 4        # new


# ---------------------------------------------------------------------------
# Test 5: engram_engine_kwargs
# ---------------------------------------------------------------------------

class TestEngramEngineKwargs:
    def test_openai_provider(self, monkeypatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-oai-key")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        cfg = {
            "llm": {
                "provider": "openai-compatible",
                "base_url": "http://localhost:8403",
                "api_key_env": "OPENAI_API_KEY",
                "model": "test-model",
                "max_tokens": 2048,
            },
            "threads": {"default": {"observer_threshold": 1000, "reflector_threshold": 2000}},
        }
        kwargs = engram_engine_kwargs(cfg)
        assert kwargs["openai_api_key"] == "test-oai-key"
        assert kwargs["openai_base_url"] == "http://localhost:8403"
        assert kwargs["model"] == "test-model"
        assert kwargs["observer_threshold"] == 1000

    def test_anthropic_provider(self, monkeypatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-ant-key")
        cfg = {
            "llm": {
                "provider": "anthropic",
                "base_url": "",
                "api_key_env": "ANTHROPIC_API_KEY",
                "model": "claude-opus-4-5",
                "max_tokens": 4096,
            },
            "threads": {"default": {"observer_threshold": 30000, "reflector_threshold": 40000}},
        }
        kwargs = engram_engine_kwargs(cfg)
        assert kwargs["anthropic_api_key"] == "test-ant-key"
        assert kwargs["openai_api_key"] == ""


# ---------------------------------------------------------------------------
# Test 6: EngramAutoRunner — concurrent ingestion
# ---------------------------------------------------------------------------

class TestEngramAutoRunner:
    """Test the concurrent auto-runner."""

    def _make_cfg(self, sessions_dir: Path, workspace: Path) -> dict:
        return {
            "llm": {
                "provider": "openai-compatible",
                "base_url": "http://localhost:9999",
                "api_key_env": "OPENAI_API_KEY",
                "model": "test-model",
                "max_tokens": 512,
            },
            "threads": {"default": {"observer_threshold": 99999, "reflector_threshold": 99999}},
            "sessions": {"scan_dir": str(sessions_dir), "max_age_hours": 48},
            "storage": {"base_dir": str(workspace / "memory" / "engram")},
            "concurrency": {"max_workers": 2},
        }

    def test_dry_run_no_write(self, workspace: Path, sessions_dir: Path) -> None:
        p = _write_session(sessions_dir, "s1", [
            _make_openclaw_msg("user", "Hello from dry run test"),
        ])
        cfg = self._make_cfg(sessions_dir, workspace)
        runner = EngramAutoRunner(workspace=workspace, engram_cfg=cfg, dry_run=True)
        totals = runner.run_once()
        # dry_run → nothing ingested
        assert all(v == 0 for v in totals.values()) or totals == {}
        # storage should have no pending messages
        from lib.engram_storage import EngramStorage
        storage = EngramStorage(workspace)
        threads = storage.list_threads()
        assert threads == []

    def test_multi_channel_isolation(self, workspace: Path, sessions_dir: Path, monkeypatch) -> None:
        """Sessions from different channels should end up in different threads."""
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key-for-test")

        _write_session(sessions_dir, "general_sess", [
            _make_openclaw_msg("user", "[Discord Guild #general channel id:111] Hello"),
        ])
        _write_session(sessions_dir, "aimm_sess", [
            _make_openclaw_msg("user", "[Discord Guild #aimm channel id:222] Hello"),
        ])

        cfg = self._make_cfg(sessions_dir, workspace)
        # Very high threshold so no LLM calls fire
        cfg["threads"]["default"]["observer_threshold"] = 999999
        cfg["threads"]["default"]["reflector_threshold"] = 999999

        runner = EngramAutoRunner(workspace=workspace, engram_cfg=cfg, dry_run=False)
        # Patch _call_llm on the engine to avoid HTTP calls
        with patch("lib.engram.EngramEngine._call_llm", return_value="fake obs"):
            totals = runner.run_once()

        from lib.engram_storage import EngramStorage
        storage = EngramStorage(workspace)

        # Use pending.jsonl existence (not meta.json which only appears after observe)
        engram_base = workspace / "memory" / "engram"
        thread_dirs = [d.name for d in engram_base.iterdir() if d.is_dir()] if engram_base.exists() else []

        # Both channels should have their own thread directory
        assert "discord-general" in thread_dirs, f"expected discord-general in {thread_dirs}"
        assert "discord-aimm" in thread_dirs, f"expected discord-aimm in {thread_dirs}"

        # Content isolation: each thread gets only its own session's messages
        general_msgs = storage.read_pending("discord-general")
        aimm_msgs = storage.read_pending("discord-aimm")
        general_texts = [m.get("content", "") for m in general_msgs]
        aimm_texts = [m.get("content", "") for m in aimm_msgs]
        assert not any("aimm" in t.lower() for t in general_texts), "general thread has aimm content"
        assert not any("general" in t.lower() for t in aimm_texts), "aimm thread has general content"

    def test_processed_marker_prevents_reprocess(
        self, workspace: Path, sessions_dir: Path, monkeypatch
    ) -> None:
        """A session that was already processed should not be ingested again."""
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        _write_session(sessions_dir, "repeated_sess", [
            _make_openclaw_msg("user", "Hello, I should only be ingested once"),
        ])

        cfg = self._make_cfg(sessions_dir, workspace)
        runner = EngramAutoRunner(workspace=workspace, engram_cfg=cfg, dry_run=False)

        with patch("lib.engram.EngramEngine._call_llm", return_value="fake obs"):
            runner.run_once()

        # Get pending count after first run
        from lib.engram_storage import EngramStorage
        storage = EngramStorage(workspace)
        threads = storage.list_threads()
        first_counts = {t: len(storage.read_pending(t)) for t in threads}

        # Run again — should NOT re-ingest
        runner2 = EngramAutoRunner(workspace=workspace, engram_cfg=cfg, dry_run=False)
        with patch("lib.engram.EngramEngine._call_llm", return_value="fake obs"):
            runner2.run_once()

        second_counts = {t: len(storage.read_pending(t)) for t in threads}
        assert first_counts == second_counts

    def test_concurrent_threads_use_locks(
        self, workspace: Path, sessions_dir: Path, monkeypatch
    ) -> None:
        """Concurrent processing with shared thread should not corrupt state."""
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        # Create 5 sessions all going to the same thread
        for i in range(5):
            _write_session(sessions_dir, f"sess_{i}", [
                _make_openclaw_msg("user", f"Message number {i} going to general"),
                _make_openclaw_msg("assistant", f"Response {i}"),
            ])

        cfg = self._make_cfg(sessions_dir, workspace)
        cfg["concurrency"]["max_workers"] = 4

        runner = EngramAutoRunner(workspace=workspace, engram_cfg=cfg, dry_run=False)
        with patch("lib.engram.EngramEngine._call_llm", return_value="fake obs"):
            runner.run_once()

        # Storage should be consistent (no corrupt JSONL)
        from lib.engram_storage import EngramStorage
        storage = EngramStorage(workspace)
        for tid in storage.list_threads():
            # read_pending() should succeed without exceptions
            msgs = storage.read_pending(tid)
            for m in msgs:
                assert "role" in m
                assert "content" in m


# ---------------------------------------------------------------------------
# Test 7: _load_dotenv
# ---------------------------------------------------------------------------

class TestLoadDotenv:
    def test_loads_key_value(self, tmp_path: Path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("MY_TEST_VAR_XYZ=hello123\n")
        monkeypatch.delenv("MY_TEST_VAR_XYZ", raising=False)
        _load_dotenv(env_file)
        assert os.environ.get("MY_TEST_VAR_XYZ") == "hello123"

    def test_does_not_override_existing(self, tmp_path: Path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("MY_TEST_VAR_ABC=from_dotenv\n")
        monkeypatch.setenv("MY_TEST_VAR_ABC", "from_env")
        _load_dotenv(env_file)
        assert os.environ.get("MY_TEST_VAR_ABC") == "from_env"

    def test_skips_comments(self, tmp_path: Path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("# This is a comment\nMY_VAR_COMMENT=value\n")
        monkeypatch.delenv("MY_VAR_COMMENT", raising=False)
        _load_dotenv(env_file)
        assert os.environ.get("MY_VAR_COMMENT") == "value"

    def test_nonexistent_file_no_error(self, tmp_path: Path) -> None:
        # Should not raise
        _load_dotenv(tmp_path / "nonexistent.env")
