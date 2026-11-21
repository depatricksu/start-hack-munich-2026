"""Dangerous goods in the QUOTE. Owner: Riky. Detection (reading attachments) is Erik's; this module decides what we send."""
from .quote import apply, describe, mode, read_declaration  # noqa: F401
from .attach import attachment_text, check_mail, scan_attachments  # noqa: F401
