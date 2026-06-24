"""Common Pydantic schemas shared across domains."""
from __future__ import annotations

from pydantic import BaseModel


class Message(BaseModel):
    message: str
