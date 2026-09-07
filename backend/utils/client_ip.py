"""Real client IP extraction for app endpoints sitting behind the nginx proxy."""


def get_client_ip(request) -> str:
    """Prefers the first X-Forwarded-For entry (nginx sets it), then uvicorn's
    socket peer as a fallback. Returns "" when no IP is available so callers can
    skip IP-keyed limits."""
    if request is None:
        return ""
    try:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    except Exception:
        pass
    return request.client.host if request.client else ""