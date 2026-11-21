"""Dangerous goods in the QUOTE. Owner: Riky. Detection (reading attachments) is Erik's; this module decides what we send."""
from .quote import apply, describe, mode, read_declaration  # noqa: F401
from .attach import attachment_text, check_mail, scan_attachments  # noqa: F401
from .facts import compare, override, packing_facts  # noqa: F401

import os as _os
if _os.environ.get("DG_OCR_WARMUP", "1") == "1":       # start the OCR worker in the background (macOS only, never raises)
    from .attach import warm_up as _warm_up
    _warm_up()
