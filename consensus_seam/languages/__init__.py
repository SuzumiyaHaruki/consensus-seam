"""Target-language backends."""

from .base import LanguageBackend
from .go import GoBackend

__all__ = ["LanguageBackend", "GoBackend"]
