import re


def user_slug_from_identity(user) -> str:
	"""Prefer explicit username if present, else email local-part; slugify."""
	raw = getattr(user, "username", None) or (user.email.split("@")[0] if getattr(user, "email", None) else "user")
	slug = re.sub(r"[^a-z0-9._-]+", "-", raw.lower()).strip("-._")
	return slug or "user"