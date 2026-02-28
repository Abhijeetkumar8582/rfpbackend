"""Generate custom user IDs: first 10 UUID-like chars + '-' + DDMMYYYYHHMMSS."""
import uuid
from datetime import datetime, timezone


def generate_user_id() -> str:
    """
    Generate a user ID: 10-char UUID prefix (U + 9 hex) + '-' + current time.
    Example: U8189cf674-19022026155529
    """
    hex_part = uuid.uuid4().hex[:9]  # first 9 hex chars
    prefix = f"U{hex_part}"  # 10 chars total, e.g. U8189cf674
    now = datetime.now(timezone.utc)
    time_part = now.strftime("%d%m%Y%H%M%S")  # DDMMYYYYHHMMSS, e.g. 19022026155529
    return f"{prefix}-{time_part}"
