"""Swipe typing for BetterFrame Keyboard.

You hold the trigger on a word's first letter, sweep through the letters, and let go. The swipe is compared
with the path each candidate word would trace over the keyboard you're using right now (any layout, any
language), and more common words are preferred. Word lists: words/<language>.txt, most common first.
"""
import math
import os
from operator import sub as _sub
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
N = 32  # points each path is resampled to


def _resample(pts, n=N):
    if len(pts) == 1:
        return pts * n
    d = [0.0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        d.append(d[-1] + math.hypot(x1 - x0, y1 - y0))
    total = d[-1]
    if total <= 1e-6:
        return [pts[0]] * n
    out, j = [], 0
    for i in range(n):
        t = total * i / (n - 1)
        while j < len(d) - 2 and d[j + 1] < t:
            j += 1
        seg = d[j + 1] - d[j] or 1e-6
        a = (t - d[j]) / seg
        out.append((pts[j][0] + (pts[j + 1][0] - pts[j][0]) * a, pts[j][1] + (pts[j + 1][1] - pts[j][1]) * a))
    return out


def _length(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


LIGATURES = {"œ": "oe", "æ": "ae", "ß": "ss", "ĳ": "ij"}  # letters swiped as two keys when they have no key of their own


def _base(c):
    """é -> e, ü -> u ... (the key a letter lives on when it has no key of its own)."""
    return unicodedata.normalize("NFD", c)[0]


def _dtw(a, b, band=5):
    """Average distance between two paths after letting them stretch against each other (dynamic time warping)."""
    n = len(a)
    inf = float("inf")
    prev = [inf] * (n + 1)
    prev[0] = 0.0
    for i in range(1, n + 1):
        cur = [inf] * (n + 1)
        ax, ay = a[i - 1]
        for j in range(max(1, i - band), min(n, i + band) + 1):
            bx, by = b[j - 1]
            c = math.hypot(ax - bx, ay - by)
            cur[j] = c + min(prev[j], prev[j - 1], cur[j - 1])
        prev = cur
    return prev[n] / n


def _passes(path, letters):
    """How closely the swipe passes over each letter of a word, in order: the best way to match each letter
    to a point on the path, moving forward only. Returns (average, worst) distance in the path's units."""
    n = len(path)
    inf = float("inf")
    prev = None
    worst_of = []
    for li, (kx, ky) in enumerate(letters):
        d = [math.hypot(px - kx, py - ky) for px, py in path]
        if prev is None:
            cur = d[:]
            best = [(v, v) for v in d]  # (sum, worst) along the best chain ending here
        else:
            cur, nb = [inf] * n, [None] * n
            run, run_b = inf, None
            for j in range(n):
                if prev[j] < run:
                    run, run_b = prev[j], best[j]
                if run_b is not None:
                    cur[j] = run + d[j]
                    nb[j] = (cur[j], max(run_b[1], d[j]))
            best = nb
        prev = cur
    j = min(range(n), key=lambda i: prev[i])
    return prev[j] / len(letters), best[j][1]


class Decoder:
    def __init__(self):
        self.lists = {}
        self.index = {}
        self.w_freq, self.w_len, self.w_ends = 0.03, 0.08, 0.12
        self.w_pass, self.w_worst, self.pass_max = 0.3, 0.3, 1.6

    def available(self, lang2):
        return os.path.exists(os.path.join(HERE, "words", lang2 + ".txt"))

    def words(self, lang2):
        if not lang2:
            return []
        if lang2 not in self.lists:
            try:
                with open(os.path.join(HERE, "words", lang2 + ".txt"), encoding="utf-8") as f:
                    self.lists[lang2] = [w.strip() for w in f if w.strip()]
            except OSError:
                self.lists[lang2] = []
        return self.lists[lang2]

    def _index(self, lang2, keys):
        """(first key, last key) -> [(rank, word, key sequence)] for the keyboard as it is now."""
        sig = (lang2, tuple(sorted(keys.items())))
        if sig in self.index:
            return self.index[sig]
        idx = {}
        for rank, w in enumerate(self.words(lang2)):
            seq = []
            for c in w:
                k = c if c in keys else _base(c)
                parts = [k] if k in keys else [x for x in LIGATURES.get(c, "")] if all(x in keys for x in LIGATURES.get(c, "-")) else None
                if not parts:
                    seq = None
                    break
                for k in parts:
                    if not seq or seq[-1] != k:
                        seq.append(k)
            if not seq or len(seq) < 2:
                continue
            idx.setdefault((seq[0], seq[-1]), []).append([rank, w, seq, None])  # last: its shape, worked out once
        if len(self.index) > 6:
            self.index.clear()
        self.index[sig] = idx
        return idx

    def _seq(self, w, keys):
        seq = []
        for c in w:
            k = c if c in keys else _base(c)
            parts = [k] if k in keys else list(LIGATURES.get(c, ""))
            for k in parts:
                if not seq or seq[-1] != k:
                    seq.append(k)
        return seq

    def decode(self, lang2, path, keys, keyw, n=4):
        """path: laser points over the keyboard (pixels); keys: letter -> key centre (pixels); keyw: key width.
        Returns up to n words, best first."""
        if len(path) < 2 or not keys:
            return []
        idx = self._index(lang2, keys)
        sx, sy = path[0]
        ex, ey = path[-1]
        near = lambda x, y, r: [k for k, (kx, ky) in keys.items() if math.hypot(kx - x, ky - y) <= r * keyw]
        starts, ends = near(sx, sy, 1.25), near(ex, ey, 1.25)
        user = _resample(path)
        ux, uy = [p[0] for p in user], [p[1] for p in user]
        ulen = _length(path) / keyw
        scored = []
        shapes = {}
        for a in starts:
            for b in ends:
                for e in idx.get((a, b), ()):
                    rank, w, seq, shape = e
                    if shape is None:   # a word's ideal path never changes for this keyboard: work it out once
                        ideal = [keys[k] for k in seq]
                        shape = e[3] = (ideal, _length(ideal), None)
                    ideal, ilen = shape[0], shape[1] / keyw
                    if ilen > ulen * 2.2 + 1.5 or ulen > ilen * 2.2 + 1.5:
                        continue
                    if shape[2] is None:
                        r = _resample(ideal)
                        shape = e[3] = (ideal, shape[1], r, [q[0] for q in r], [q[1] for q in r])
                    shapes[w] = shape
                    dist = sum(map(math.hypot, map(_sub, ux, shape[3]), map(_sub, uy, shape[4]))) / (N * keyw)
                    # small shapes errors matter most; common words win ties
                    # where you start and let go matter most (people land on the first and last letter)
                    ends_off = (math.hypot(sx - ideal[0][0], sy - ideal[0][1]) + math.hypot(ex - ideal[-1][0], ey - ideal[-1][1])) / keyw
                    score = dist + self.w_freq * math.log(rank + 20) + self.w_len * abs(ilen - ulen) / (ilen + 1) + self.w_ends * ends_off
                    scored.append((score, rank, w))
        scored.sort()
        # second pass on the best few: compare with time warping, so a wobbly hand or uneven speed
        # doesn't make the right word look worse
        # second pass on the best few: compare with time warping (a wobbly hand or uneven speed doesn't make the
        # right word look worse), and check the swipe really went over every letter of the word, in order -
        # a word whose letters you never went near is never picked, however common it is
        best, far = [], []
        fine = _resample(path, 64)
        for score, rank, w in scored[:60]:
            ideal, ilen, ipts = shapes[w][:3]
            ilen /= keyw
            ends_off = (math.hypot(sx - ideal[0][0], sy - ideal[0][1]) + math.hypot(ex - ideal[-1][0], ey - ideal[-1][1])) / keyw
            dtw = _dtw(user, ipts) / keyw
            avg, worst = _passes(fine, ideal)
            avg, worst = avg / keyw, worst / keyw
            sc = (dtw + self.w_pass * avg + self.w_freq * math.log(rank + 20) + self.w_len * abs(ilen - ulen) / (ilen + 1)
                  + self.w_ends * ends_off)
            (best if worst <= self.pass_max else far).append((sc + self.w_worst * max(0.0, worst - 0.7), rank, w))
        scored = sorted(best) + sorted(far)
        out = []
        for _, _, w in scored:
            if w not in out:
                out.append(w)
            if len(out) >= n:
                break
        return out
