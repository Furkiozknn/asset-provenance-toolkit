"""One write path for every backend that rewrites a user's file in place.

A backend that calls ``Path.write_bytes`` on the asset itself truncates it
first and then writes; a failure in between (disk full, the process killed,
a network filesystem dropping out) leaves a half-written file where a
complete one used to be. For a generated video that is the only copy of an
expensive render, that is data loss. So the new bytes go to a sibling temp
file and are renamed over the original, which POSIX and Windows both do
atomically within one directory.

Details that keep the replacement faithful and safe:

* The temp file is created with ``mkstemp`` - a random name opened with
  ``O_EXCL`` - never a fixed, guessable name. In a shared directory a fixed
  name lets someone else plant a symlink there first and have this tool
  write the asset's bytes through it into a file of their choosing.
* The original's permission bits are copied onto the temp file before the
  rename - otherwise an asset kept at 0600 would come back at a different
  mode. A file that did not exist yet (a new sidecar) gets the usual
  umask-derived mode, as ``open(path, "w")`` would have given it.
* A symlink is resolved first, so the file it points at is replaced and the
  link itself stays a link.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO, Callable


def _umask_default_mode() -> int:
    # os.umask can only be read by setting it; restore it immediately.
    current = os.umask(0)
    os.umask(current)
    return 0o666 & ~current


def write_atomic_with(path: str | Path, write: Callable[[BinaryIO], None]) -> None:
    """Replace `path` atomically with whatever `write` puts into the file
    object it is handed. Streaming form, for backends that copy large byte
    ranges instead of building the whole file in memory."""
    target = Path(os.path.realpath(path))
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".aprov-tmp", dir=target.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            write(fh)
        if target.exists():
            shutil.copymode(target, tmp)
        else:
            os.chmod(tmp, _umask_default_mode())
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_atomic(path: str | Path, payload: bytes) -> None:
    write_atomic_with(path, lambda fh: fh.write(payload))
