"""Media rules (no Frappe, tested offline): what Meta accepts per kind, naming files safely, sizes in words.

The limits are Meta's documented values as of Oct 2026 and are UNVERIFIED against live Meta (M1 re-checks them):
image 5 MB (jpeg, png), video 16 MB (mp4, 3gp), audio 16 MB (aac, amr, mp3, mp4, ogg opus), document 100 MB,
sticker 100 KB (static webp) or 500 KB (animated webp).
"""

import os
import re

MB = 1024 * 1024
KB = 1024

# kind -> {mime type: preferred extension}
TYPES = {
	"image": {"image/jpeg": ".jpg", "image/png": ".png"},
	"video": {"video/mp4": ".mp4", "video/3gpp": ".3gp"},
	"audio": {
		"audio/aac": ".aac",
		"audio/amr": ".amr",
		"audio/mpeg": ".mp3",
		"audio/mp4": ".m4a",
		"audio/ogg": ".ogg",
	},
	"document": {
		"application/pdf": ".pdf",
		"application/msword": ".doc",
		"application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
		"application/vnd.ms-excel": ".xls",
		"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
		"application/vnd.ms-powerpoint": ".ppt",
		"application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
		"text/plain": ".txt",
	},
	"sticker": {"image/webp": ".webp"},
}
LIMITS = {"image": 5 * MB, "video": 16 * MB, "audio": 16 * MB, "document": 100 * MB, "sticker": 500 * KB}
# What can be shown or played inside the inbox; everything else is a download card.
INLINE = ("image", "video", "audio", "sticker")
CAPTION_KINDS = ("image", "video", "document")  # audio and sticker cannot carry a caption
MAX_CAPTION = 1024
RECEIVE_CAP = 100 * MB  # we never download more than the largest thing Meta can deliver

_EXTRA_EXTENSIONS = {"image/jpg": ".jpg", "audio/opus": ".ogg", "audio/x-m4a": ".m4a", "video/quicktime": ".mov"}


def clean_mime(value):
	"""'audio/ogg; codecs=opus' -> 'audio/ogg'."""
	return str(value or "").split(";")[0].strip().lower()


def kind_for_mime(mime):
	"""image / video / audio / document / sticker for a mime type, or None when WhatsApp cannot send it."""
	mime = clean_mime(mime)
	if mime == "image/webp":
		return "sticker"
	for kind, types in TYPES.items():
		if mime in types:
			return kind
	return None


def extension_for(mime):
	"""A file extension taken from the mime type (never from a header string); '' when unknown."""
	mime = clean_mime(mime)
	for types in TYPES.values():
		if mime in types:
			return types[mime]
	return _EXTRA_EXTENSIONS.get(mime, "")


def safe_filename(name, mime="", fallback="file"):
	"""A file name with no path, no odd characters and an extension that fits the mime type."""
	base = os.path.basename(str(name or "").replace("\\", "/")).strip().strip(".")
	stem, ext = os.path.splitext(base)
	stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem).strip(" ._-")[:80] or fallback
	ext = re.sub(r"[^A-Za-z0-9.]", "", ext).lower()[:8]
	wanted = extension_for(mime)
	if wanted and ext != wanted and not (ext == ".jpeg" and wanted == ".jpg"):
		ext = wanted
	return stem + ext


def human_size(n):
	n = int(n or 0)
	if n < KB:
		return f"{n} B"
	if n < MB:
		return f"{n / KB:.0f} KB"
	return f"{n / MB:.1f} MB"


def _a(word):
	return ("an " if word[0] in "aeiou" else "a ") + word


def check_upload(mime, size):
	"""(ok, kind, plain-words message) for a file a person wants to send."""
	kind = kind_for_mime(mime)
	if not kind:
		return False, None, "WhatsApp cannot send this kind of file. Use an image (JPG, PNG), a PDF or Office document, a video (MP4) or an audio file."
	size = int(size or 0)
	if size <= 0:
		return False, kind, "The file is empty."
	limit = LIMITS[kind]
	if size > limit:
		return False, kind, f"This {kind} is {human_size(size)}; WhatsApp accepts at most {human_size(limit)} for {_a(kind)}."
	return True, kind, ""


def check_caption(kind, caption):
	caption = str(caption or "").strip()
	if not caption:
		return True, ""
	if kind not in CAPTION_KINDS:
		return False, f"{_a(kind).capitalize()} cannot have a caption."
	if len(caption) > MAX_CAPTION:
		return False, f"The caption is longer than {MAX_CAPTION} characters."
	return True, ""


def serve_as(mime, filename=""):
	"""(content type, 'inline' or 'attachment') for sending a stored file back to a browser.
	Only the kinds the inbox shows itself are served inline, and only with the type WE recorded; everything else
	(including anything that could run as a page) is a plain download with a neutral type."""
	mime = clean_mime(mime)
	kind = kind_for_mime(mime)
	if kind in INLINE and mime in TYPES.get(kind, {}):
		return mime, "inline"
	if kind == "sticker":
		return "image/webp", "inline"
	if mime == "application/pdf":
		return mime, "attachment"
	return "application/octet-stream", "attachment"


_SIGNATURES = (
	(b"\xff\xd8\xff", "image/jpeg"),
	(b"\x89PNG\r\n\x1a\n", "image/png"),
	(b"%PDF-", "application/pdf"),
	(b"OggS", "audio/ogg"),
)


def sniff(content):
	"""The type a file's first bytes show, for the kinds that are easy to recognise; None when not recognisable.
	Used to refuse a file whose name says one thing and whose bytes say another (an .exe renamed .pdf)."""
	head = bytes(content[:16]) if content else b""
	for signature, mime in _SIGNATURES:
		if head.startswith(signature):
			return mime
	if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
		return "image/webp"
	if head[4:8] == b"ftyp":
		return "video/mp4"
	return None


def check_content(mime, content):
	"""(ok, message): the bytes must not contradict the claimed type. Unrecognised bytes pass only for types that have no
	simple signature (Office, text, audio other than ogg)."""
	mime = clean_mime(mime)
	seen = sniff(content)
	if seen is None:
		strict = {"image/jpeg", "image/png", "application/pdf", "image/webp"}
		return (mime not in strict, "" if mime not in strict else "The file's contents do not look like its type, so it was not sent.")
	same = seen == mime or (seen == "video/mp4" and mime in ("video/mp4", "audio/mp4", "video/3gpp")) or (seen == "audio/ogg" and mime == "audio/ogg")
	return (same, "" if same else "The file's contents do not look like its type, so it was not sent.")


def shared_file_visible(row, today, allowed_teams, admin=False):
	"""May a rep be offered this library file? `row` has enabled, scope, team, valid_until (a date or None)."""
	if not row.get("enabled"):
		return False
	until = row.get("valid_until")
	if until and until < today:
		return False
	if admin or row.get("scope") != "Team":
		return True
	return row.get("team") in allowed_teams
