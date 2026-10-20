import re
from urllib.parse import quote
from fastapi import Response

# Types that are safe to render in the browser; anything else (html, svg, ...) is forced to download
INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp", "image/gif"}


def make_content_disposition(disposition_type: str, filename: str) -> str:
    # Sanitize ASCII fallback (remove quotes, commas, semicolons, backslashes)
    safe_ascii = re.sub(r'[\",;\\/\x00-\x1f\x7f-\xff]', '_', filename)
    encoded = quote(filename)
    return f"{disposition_type}; filename=\"{safe_ascii}\"; filename*=utf-8''{encoded}"


def file_response(content: bytes, filename: str, media_type: str | None, disposition: str) -> Response:
    if media_type not in INLINE_TYPES:
        media_type, disposition = "application/octet-stream", "attachment"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": make_content_disposition(disposition, filename),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
