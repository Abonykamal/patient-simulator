"""Tests for src.core.logging — structlog configuration.

These tests capture stdout (the PrintLogger destination) and assert on the
rendered output, so the production JSON format is what's actually verified.
"""

import json

import pytest
import structlog


@pytest.fixture(autouse=True)
def _reset_structlog():
    """Each test reconfigures structlog; reset global state and context after."""
    yield
    structlog.contextvars.clear_contextvars()
    structlog.reset_defaults()


class TestJSONOutput:
    def test_emits_json_with_event_level_and_fields(self, capsys):
        from src.core.logging import configure_logging

        configure_logging(log_level="INFO", json_logs=True)
        structlog.get_logger().info("agent_response", tokens_used=342)

        line = capsys.readouterr().out.strip()
        obj = json.loads(line)  # fails loudly if output is not valid JSON
        assert obj["event"] == "agent_response"
        assert obj["level"] == "info"
        assert obj["tokens_used"] == 342
        assert "timestamp" in obj

    def test_bound_contextvars_appear_on_every_line(self, capsys):
        # session_id bound once at a boundary must ride along automatically,
        # without being passed to the log call.
        from src.core.logging import configure_logging

        configure_logging(log_level="INFO", json_logs=True)
        structlog.contextvars.bind_contextvars(session_id="abc123")
        structlog.get_logger().info("turn_received")

        obj = json.loads(capsys.readouterr().out.strip())
        assert obj["session_id"] == "abc123"

    def test_respects_log_level(self, capsys):
        from src.core.logging import configure_logging

        configure_logging(log_level="INFO", json_logs=True)
        structlog.get_logger().debug("below_threshold")

        assert capsys.readouterr().out.strip() == ""


class TestConsoleOutput:
    def test_console_renderer_is_not_json(self, capsys):
        from src.core.logging import configure_logging

        configure_logging(log_level="INFO", json_logs=False)
        structlog.get_logger().info("human_readable")

        out = capsys.readouterr().out
        assert "human_readable" in out
        with pytest.raises(json.JSONDecodeError):
            json.loads(out.strip())


class TestGetLogger:
    def test_get_logger_binds_component(self, capsys):
        from src.core.logging import configure_logging, get_logger

        configure_logging(log_level="INFO", json_logs=True)
        get_logger("agents.patient").info("ready")

        obj = json.loads(capsys.readouterr().out.strip())
        assert obj["component"] == "agents.patient"
