"""One write path for every backend that rewrites a user's file in place.

A backend that calls ``Path.write_bytes`` on the asset itself truncates it
first and then writes; a failure in between (disk full, the process killed,
a network filesystem dropping out) leaves a half-written file where a
complete one used to be. For a generated video that is the only copy of an
expensive render, that is data loss. So the new bytes go to a sibling temp
file and are renamed over the original, which POSIX and Windows both do
atomically within one directory.

Two details keep the replacement faithful to the file it replaces:

* The original's permission bits are copied onto the temp file before the
  rename - otherwise an asset kept at 0600 would come back at the umask
  default and quietly become readable by others.
* A symlink is resolved first, so the file it points at is replaced and the
  link itself stays a link.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def write_atomic(path: str | Path, payload: bytes) -> None:
    target = Path(os.path.realpath(path))
    tmp = target.with_name(f".{target.name}.aprov-tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(payload)
        if target.exists():
            shutil.copymode(target, tmp)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
