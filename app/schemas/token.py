from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenPayload(BaseModel):
    """JWT payload shape.

    ``sub`` holds the user e-mail (login identity).
    ``tenant_id`` is embedded at token creation so middleware can read it
    without a DB round-trip (see ``app/middleware/request_logging.py``).
    """

    sub: Optional[str] = None
    tenant_id: Optional[UUID] = None
