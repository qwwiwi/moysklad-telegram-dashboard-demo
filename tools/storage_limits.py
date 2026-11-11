"""Bound private document storage before accepting additional uploads."""
from contextlib import closing
from pathlib import Path


def check_storage(folder, incoming, user_id):
    from intake_store import connect
    folder = Path(folder)
    total = sum(p.stat().st_size for p in folder.iterdir() if p.is_file())
    with closing(connect()) as db:
        paths = [r[0] for r in db.execute("SELECT storage_path FROM journal WHERE user_id=? AND storage_path IS NOT NULL", (user_id,))]
    used = sum(Path(p).stat().st_size for p in paths if Path(p).is_file())
    if total + incoming > 5 * 1024**3 or used + incoming > 1024**3:
        raise ValueError("Storage quota reached")
