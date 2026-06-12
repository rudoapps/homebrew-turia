"""Message entity representing a single message in a conversation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class ImageAttachment:
    """An image attached to a message."""

    data: str  # base64-encoded image data
    media_type: str  # e.g. "image/png", "image/jpeg"


@dataclass
class Message:
    """A single message in a conversation.

    Attributes:
        role: The sender role — "user", "assistant", or "system".
        content: The text content of the message.
        images: Optional list of image attachments (base64-encoded).
        model: The model that generated this message (for assistant messages).
    """

    role: str
    content: str
    images: List[ImageAttachment] = field(default_factory=list)
    model: Optional[str] = None

    def has_images(self) -> bool:
        """Return True if this message has image attachments."""
        return len(self.images) > 0
