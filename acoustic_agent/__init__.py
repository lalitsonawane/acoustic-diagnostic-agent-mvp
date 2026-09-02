"""Acoustic diagnostic agent: signal synthesis, feature extraction, detection and decision logic.

The package is UI-agnostic. ``app.py`` (Streamlit) and ``acoustic_agent.cli`` are thin
front-ends over :func:`acoustic_agent.pipeline.analyze`.
"""

from __future__ import annotations

__version__ = "0.2.0"

# Bump whenever the feature definitions or scoring rule change so that stored results
# can be told apart. Recorded in every run-log row and work-order payload.
FEATURE_VERSION = "features-v3-welch-transient-envelope"

__all__ = ["FEATURE_VERSION", "__version__"]
