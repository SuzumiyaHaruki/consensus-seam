"""目标语言后端。"""

from .base import LanguageBackend
from .go import GoBackend

__all__ = ["LanguageBackend", "GoBackend"]
