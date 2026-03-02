"""V2 Validation — look-ahead bias detection, robustness scoring."""

from .lookahead import (
    detect_look_ahead,
    LookAheadConfig,
    LookAheadResult,
    LookAheadTestPoint,
    SignalSnapshot,
)
from .robustness import (
    score_robustness,
    RobustnessConfig,
    RobustnessResult,
    WindowResult,
)

__all__ = [
    # Look-ahead
    "detect_look_ahead",
    "LookAheadConfig",
    "LookAheadResult",
    "LookAheadTestPoint",
    "SignalSnapshot",
    # Robustness
    "score_robustness",
    "RobustnessConfig",
    "RobustnessResult",
    "WindowResult",
]
