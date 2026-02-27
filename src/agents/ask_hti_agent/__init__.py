
"""
Document Q&A Agent - Answers questions based on indexed documents.
"""

from .agent import root_agent

# Optional Phoenix tracing (not available in packaged app)
try:
    from phoenix.otel import register
    tracer_provider = register(
        project_name="you-work",
        auto_instrument=True
    )
except ImportError:
    pass

__all__ = ["root_agent"]