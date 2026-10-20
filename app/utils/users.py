import hashlib
import re

# Gmail local parts are unique per mailbox, so they keep the plain (legacy) folder name
LEGACY_DOMAINS = {"gmail.com", "googlemail.com"}


def slug_for_email(email: str | None) -> str:
	"""Per-user media folder name. Must be unique per user: two accounts sharing a folder could read
	or overwrite each other's files (e.g. bob@gmail.com vs bob@outlook.com)."""
	if not email:
		return "user"
	local, _, domain = email.lower().partition("@")
	slug = re.sub(r"[^a-z0-9._-]+", "-", local).strip("-._") or "user"
	if domain in LEGACY_DOMAINS:
		return slug
	# Gmail local parts can't contain "-", so this can never collide with a Gmail folder
	return f"{slug}-{hashlib.sha256(email.lower().encode()).hexdigest()[:12]}"


def user_slug_from_identity(user) -> str:
	return slug_for_email(getattr(user, "email", None))
