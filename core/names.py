"""File names made from text."""


def safe_stem(title: str, limit: int = 80, fallback: str = "cover") -> str:
    """A file name stem from a title: no characters Windows forbids, spaces collapsed."""
    s = "".join("_" if ch in '<>:"/\\|?*' or ord(ch) < 32 else ch for ch in title).strip(" .")
    s = " ".join(s.split())
    return s[:limit].rstrip(" .") or fallback
