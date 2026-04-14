"""pixel_forge package init.

Suppresses the noisy `google.generativeai` deprecation warning at import
time so that `pf` CLI subprocesses produce clean JSON on stdout/stderr.
The warning is informational only — pixel-forge will switch to the new
`google.genai` package separately, but in the meantime we don't want
this leaking into every test that subprocess-parses the CLI output.
"""
from __future__ import annotations

import warnings

warnings.filterwarnings(
    "ignore",
    category=FutureWarning,
    message=r"(?s).*google\.generativeai.*",
)
