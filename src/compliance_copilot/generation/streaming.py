"""Incremental extraction of the ``answer`` text from a streamed JSON document.

The model returns ``{"status": ..., "answer": "...", "citations": [...], ...}``. While it is
being written, only the ``answer`` string is useful to show; the rest (citations) is needed
for verification and arrives after it. ``AnswerStream.feed`` takes raw JSON fragments and
returns the newly decoded answer text, handling escapes that are split across fragments.
"""

from __future__ import annotations

import re

_KEY = re.compile(r'"answer"\s*:\s*"')
_SIMPLE = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}


class AnswerStream:
    def __init__(self) -> None:
        self._buf = ""
        self._pos: int | None = None
        self.done = False

    def feed(self, fragment: str) -> str:
        self._buf += fragment
        if self.done:
            return ""
        if self._pos is None:
            m = _KEY.search(self._buf)
            if not m:
                return ""
            self._pos = m.end()
        b, i, out = self._buf, self._pos, []
        while i < len(b):
            ch = b[i]
            if ch == '"':
                self.done = True
                i += 1
                break
            if ch != "\\":
                out.append(ch)
                i += 1
                continue
            if i + 1 >= len(b):
                break  # escape split across fragments: wait for the rest
            n = b[i + 1]
            if n != "u":
                out.append(_SIMPLE.get(n, n))
                i += 2
                continue
            if i + 6 > len(b):
                break
            cp = int(b[i + 2 : i + 6], 16)
            if 0xD800 <= cp < 0xDC00:  # high surrogate: needs its pair (e.g. emoji)
                if i + 12 > len(b):
                    break
                low = int(b[i + 8 : i + 12], 16)
                out.append(chr(0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00)))
                i += 12
                continue
            out.append(chr(cp))
            i += 6
        self._pos = i
        return "".join(out)
