__version__ = "0.1.0"

# Public Python API (thin subprocess wrapper over the CLI). Importing these
# lazily would avoid pulling subprocess at import time, but they're cheap and
# the contract is the point of the package, so export them at the top level.
from .api import (  # noqa: E402,F401
    CookRequest,
    CookResult,
    CookStatus,
    cancel,
    get_artifacts,
    get_result,
    get_status,
    run_cook,
    run_judge,
    run_report,
    run_resume,
)

__all__ = [
    "__version__",
    "CookRequest",
    "CookStatus",
    "CookResult",
    "run_cook",
    "run_judge",
    "run_report",
    "run_resume",
    "cancel",
    "get_status",
    "get_result",
    "get_artifacts",
]
