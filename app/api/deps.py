"""FastAPI dependencies — DB session, auth placeholder."""
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.database import get_db

# Type alias for dependency injection
DbSession = Annotated[Session, Depends(get_db)]

# TODO: add get_current_user when auth is implemented
# CurrentUser = Annotated[User, Depends(get_current_user)]
