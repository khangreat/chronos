"""Importers package. Importing it registers all built-in importers."""

from .base import (  # noqa: F401
    BrowserImporter,
    all_importers,
    get_importer,
    register,
)
from . import firefox  # noqa: F401  (registers Firefox/Mullvad/Tor)
from . import chromium  # noqa: F401  (registers Chrome/Edge/Brave/Vivaldi/Opera)
from . import html_import  # noqa: F401  (registers HTML)
from . import history  # noqa: F401  (registers Firefox/Chrome/Edge/Brave history)
