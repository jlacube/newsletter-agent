"""
HTML file output for dry-run mode and email failure fallback.

Spec refs: FR-031, FR-034, FR-035.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def save_newsletter_html(
    html_content: str, output_dir: str, newsletter_date: str
) -> str:
    """Save newsletter HTML to disk.

    Args:
        html_content: Complete HTML newsletter string.
        output_dir: Directory to save the file in. Created if it does not exist.
        newsletter_date: Date string in YYYY-MM-DD format for the filename.

    Returns:
        Absolute path of the saved file.

    Raises:
        IOError: If the directory cannot be created or the file cannot be written.
    """
    output_path = Path(output_dir) / f"{newsletter_date}-newsletter.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")
    resolved = str(output_path.resolve())
    logger.info("Newsletter saved to %s", resolved)
    return resolved
