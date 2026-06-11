"""structlog configuration for the whole application.

This module is configured once at startup via ``configure_logging()`` and then
every other module just calls ``get_logger(...)`` and logs. The output format
and the standard fields (timestamp, level, component, plus any bound context
such as ``session_id``) are decided here and nowhere else.

Design notes:
- Rendering is env-switched: JSON in production (the source of truth), an
  optional human-readable console renderer for local development.
- Per-request context (e.g. ``session_id``) is propagated via structlog's
  contextvars integration: bind it once at the API boundary and it rides
  along on every log line within that async request, with no parameter
  threading. The ``merge_contextvars`` processor below is what makes that work.
- stdlib logging (uvicorn, SQLAlchemy) is intentionally NOT bridged yet —
  there is no web server in the codebase at this phase. That bridge is added
  when the API layer arrives and the need is concrete.

``configure_logging`` takes ``log_level`` and ``json_logs`` as explicit
parameters rather than importing settings, so it has zero internal
dependencies and is testable without API keys present. The caller (the API
entry point) reads ``Settings`` and passes the values in.
"""

import logging

import structlog

# structlog's BoundLogger type after configuration; kept loose to avoid
# over-specifying the return type for callers.
Logger = structlog.stdlib.BoundLogger


def configure_logging(log_level: str = "INFO", json_logs: bool = True) -> None:
    """Install the global structlog processing pipeline.

    Call once at application startup, before any logging happens.

    Args:
        log_level: Minimum level to emit ("DEBUG", "INFO", "WARNING", ...).
            Anything below this threshold is dropped.
        json_logs: True renders each line as a JSON object (production /
            source of truth); False renders human-readable console output
            for local development.
    """
    level = logging.getLevelNamesMapping().get(log_level.upper(), logging.INFO)

    # Shared processors run for every log call, in order, before rendering.
    processors: list = [
        # Pull in anything bound via bind_contextvars (e.g. session_id).
        structlog.contextvars.merge_contextvars,
        # Add the "level" field ("info", "error", ...).
        structlog.processors.add_log_level,
        # ISO-8601 UTC "timestamp" field.
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        # Render exceptions passed via exc_info into a readable field.
        structlog.processors.format_exc_info,
    ]

    renderer: object = (
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*processors, renderer],
        # Filtering at the bound-logger level drops sub-threshold calls cheaply.
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        # Caching is a perf win but would prevent reconfiguration between
        # tests; correctness under reconfiguration matters more here.
        cache_logger_on_first_use=False,
    )


def get_logger(component: str | None = None) -> Logger:
    """Return a logger, optionally tagged with the calling component.

    Modules typically call ``get_logger(__name__)`` or pass an explicit
    component label so every line carries a ``component`` field, satisfying
    the project-wide logging contract.

    Args:
        component: Value for the "component" field (e.g. "agents.patient").
            Omit for an untagged logger.

    Returns:
        A structlog logger ready for ``.info(event, **fields)`` calls.
    """
    logger = structlog.get_logger()
    if component is not None:
        logger = logger.bind(component=component)
    return logger
