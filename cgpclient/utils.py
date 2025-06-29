import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

REQUEST_TIMEOUT_SECS = 30
CHUNK_SIZE_BYTES = 8192

APIM_BASE_URL = "api.service.nhs.uk"


class CGPClientException(Exception):
    pass


def md5sum(filename: Path) -> str:
    """Compute the MD5 checksum of the file in chunks"""
    md5 = hashlib.md5()
    with open(filename, "rb") as f:
        for chunk in iter(lambda: f.read(128 * md5.block_size), b""):
            md5.update(chunk)
    return md5.hexdigest()


def create_uuid() -> str:
    """Create a UUID string"""
    return str(uuid.uuid4())


def get_current_datetime() -> str:
    """Return the current datetime in ISO format in the UTC timezone"""
    return datetime.now(timezone.utc).isoformat()
