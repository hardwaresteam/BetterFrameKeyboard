"""Input conversion for BetterFrame Keyboard: what turns typed sounds or codes into real text.

  Japanese  kana -> kanji, whole sentences at once (Mozc's open dictionary and its word-to-word costs)
  Chinese   Zhuyin or Pinyin -> characters and phrases (McBopomofo's data), Traditional or Simplified
            Cangjie and Quick codes -> characters (Cangjie 5 table)
  Korean    jamo -> Hangul syllables (built in, no dictionary needed)

Dictionaries live in ime/ and are opened straight from disk (memory-mapped) the first time they're needed, so a
language you don't use costs nothing, and the one you do use loads instantly.
"""
import mmap
import os
import struct
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "ime")


# --------------------------------------------------------------------------- dictionary file (tools/build_ime.py)
class Table:
    """Sorted keys -> values, read straight from the file."""

    def __init__(self, path):
        with open(path, "rb") as f:
            self.mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        assert self.mm[:4] == b"BFT1"
        n = struct.unpack_from("<I", self.mm, 4)[0]
        self.n = n
        mv = memoryview(self.mm)
        self.koff = mv[8:8 + 4 * (n + 1)].cast("I")
        self.voff = mv[8 + 4 * (n + 1):8 + 8 * (n + 1)].cast("I")
        self.kbase = 8 + 8 * (n + 1)
        self.vbase = self.kbase + self.koff[n]

    def key(self, i):
        return self.mm[self.kbase + self.koff[i]:self.kbase + self.koff[i + 1]]

    def value(self, i):
        return self.mm[self.vbase + self.voff[i]:self.vbase + self.voff[i + 1]]

    def lower(self, k):
        lo, hi = 0, self.n
        while lo < hi:
            mid = (lo + hi) // 2
            if self.key(mid) < k:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def get(self, k):
        k = k.encode("utf-8") if isinstance(k, str) else k
        i = self.lower(k)
        return self.value(i) if i < self.n and self.key(i) == k else None

    def has_prefix(self, k):
        k = k.encode("utf-8") if isinstance(k, str) else k
        i = self.lower(k)
        return i < self.n and self.key(i).startswith(k)

    def starting(self, k, limit=2000):
        """(key, value) for keys that start with k, in key order."""
        k = k.encode("utf-8") if isinstance(k, str) else k
        i = self.lower(k)
        while i < self.n and limit > 0:
            kk = self.key(i)
            if not kk.startswith(k):
                break
            yield kk.decode("utf-8"), self.value(i)
            i += 1
            limit -= 1


_tables, _lock = {}, threading.Lock()


def table(name):
    with _lock:
        if name not in _tables:
            _tables[name] = Table(os.path.join(DATA, name))
        return _tables[name]


def available(kind):
    need = {"ja": ["ja.dic", "ja.con"], "zhuyin": ["zh.dic"], "pinyin": ["zh.dic"], "pinyin-s": ["zhs.dic"], "cangjie": ["cj.dic"], "quick": ["qk.dic"],
            "ko": [], "vi": []}.get(kind, [])
    return all(os.path.exists(os.path.join(DATA, n)) for n in need)


def hira(s):
    """Katakana -> hiragana (dictionary readings are in hiragana)."""
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def kata(s):
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)


# --------------------------------------------------------------------------- Japanese
class Japanese:
    UNK_ID = 1851  # 名詞,一般 (a plain noun): what an unknown word is treated as
    MAXLEN = 24

    def __init__(self):
        self.dic = table("ja.dic")
        with open(os.path.join(DATA, "ja.con"), "rb") as f:
            self.cmm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        self.N = struct.unpack_from("<I", self.cmm, 4)[0]
        self.con = memoryview(self.cmm)[8:].cast("h")
        self.pen = None
        try:  # how unlikely each kind of word is to start / end what you typed (Mozc's boundary rules)
            from array import array
            with open(os.path.join(DATA, "ja.bnd"), "rb") as f:
                self.pen = array("H", f.read())
        except OSError:
            pass
        self.cache = {}

    def conn(self, rid, lid):
        """Cost of a word with right-id rid followed by one with left-id lid."""
        return self.con[rid * self.N + lid]

    def entries(self, reading):
        """[(lid, rid, cost, surface)] for a reading, cheapest first."""
        if reading in self.cache:
            return self.cache[reading]
        v = self.dic.get(reading)
        out = []
        if v:
            i = 0
            while i < len(v):
                lid, rid, cost, n = struct.unpack_from("<HHhB", v, i)
                i += 7
                out.append((lid, rid, cost, bytes(v[i:i + n]).decode("utf-8")))
                i += n
        if len(self.cache) > 4000:
            self.cache.clear()
        self.cache[reading] = out
        return out

    def lattice(self, s):
        """Every dictionary word that fits at each position: starts[i] = [(end, lid, rid, cost, surface)]."""
        L = len(s)
        starts = [[] for _ in range(L)]
        for i in range(L):
            for j in range(i + 1, min(L, i + self.MAXLEN) + 1):
                sub = s[i:j]
                if not self.dic.has_prefix(sub):
                    break
                for lid, rid, cost, surf in self.entries(sub)[:60]:
                    starts[i].append((j, lid, rid, cost, surf))
            # something always fits: the character itself (or a run of katakana / letters / digits) as an unknown word
            c = s[i]
            j = i + 1
            kind = _script(c)
            if kind in ("kata", "latin", "digit"):
                while j < L and _script(s[j]) == kind:
                    j += 1
                starts[i].append((j, self.UNK_ID, self.UNK_ID, 3000 + 500 * (j - i) if kind != "kata" else 4000, s[i:j]))
            starts[i].append((i + 1, self.UNK_ID, self.UNK_ID, 10000, c))
        return starts

    def best(self, s):
        """Cheapest way to write the whole reading: [(reading part, written as)]."""
        if not s:
            return []
        starts = self.lattice(s)
        L = len(s)
        # ends[j] = [(total cost, rid, back pointer)]
        ends = [[] for _ in range(L + 1)]
        ends[0] = [(0, 0, None)]
        for i in range(L):
            if not ends[i]:
                continue
            for (j, lid, rid, cost, surf) in starts[i]:
                if self.pen:
                    if i == 0:
                        cost += self.pen[2 * lid]
                    if j == L:
                        cost += self.pen[2 * rid + 1]
                bc, bp = None, None
                for e in ends[i]:
                    c = e[0] + self.conn(e[1], lid)
                    if bc is None or c < bc:
                        bc, bp = c, e
                ends[j].append((bc + cost, rid, (bp, i, j, surf)))
        best, back = None, None
        for e in ends[L]:
            c = e[0] + self.conn(e[1], 0)
            if best is None or c < best:
                best, back = c, e
        out = []
        while back and back[2]:
            prev, i, j, surf = back[2]
            out.append((s[i:j], surf))
            back = prev
        return out[::-1]

    def words_for(self, reading, n=12):
        """Ways to write exactly this reading as one word, most likely first."""
        es = self.entries(reading)
        ranked = sorted(es, key=lambda e: e[2] + self.conn(0, e[0]))
        out = []
        for e in ranked:
            if e[3] not in out:
                out.append(e[3])
            if len(out) >= n:
                break
        return out

    def candidates(self, s, n=24):
        """[(text, how many characters of the reading it uses)]: the whole sentence converted, the reading as one
        word, then the first word on its own (pick it and the rest stays to convert), then kana."""
        s2 = hira(s)
        out, seen = [], set()

        def add(text, used):
            if text and text not in seen:
                seen.add(text)
                out.append((text, used))
        path = self.best(s2)
        add("".join(w for _, w in path), len(s))
        for w in self.words_for(s2, 8):
            add(w, len(s))
        firsts = []
        if len(path) > 1:
            firsts.append(len(path[0][0]))
        for j in range(min(len(s2), self.MAXLEN), 0, -1):
            if j not in firsts and self.dic.get(s2[:j]) is not None:
                firsts.append(j)
        for j in firsts:
            for w in self.words_for(s2[:j], 6):
                add(w, j)
            if len(out) >= n:
                break
        add(s if s != s2 else s2, len(s))
        add(kata(s2), len(s))
        return out[:n]


def _script(c):
    if "ァ" <= c <= "ヺ" or c == "ー":
        return "kata"
    if c.isascii() and c.isalpha():
        return "latin"
    if c.isdigit():
        return "digit"
    return "other"


# --------------------------------------------------------------------------- Chinese
TONES = "ˊˇˋ˙"
INITIALS = "ㄅㄆㄇㄈㄉㄊㄋㄌㄍㄎㄏㄐㄑㄒㄓㄔㄕㄖㄗㄘㄙ"
MEDIALS = "ㄧㄨㄩ"
FINALS = "ㄚㄛㄜㄝㄞㄟㄠㄡㄢㄣㄤㄥㄦ"


def zhuyin_syllables(sym):
    """Split typed Zhuyin into syllables: [(sound, tone)]. tone is '' for the 1st tone (typed with Space),
    one of ˊˇˋ˙, or None when no tone was typed yet (then any tone matches)."""
    out, cur = [], ""

    def slot(c):
        return 0 if c in INITIALS else 1 if c in MEDIALS else 2 if c in FINALS else 3

    for c in sym:
        if c in TONES or c == " ":
            if cur:
                out.append((cur, "" if c == " " else c))
                cur = ""
            continue
        s = slot(c)
        if s == 3:
            continue
        if cur and slot(cur[-1]) >= s:  # e.g. a new initial after a vowel: a new syllable starts
            out.append((cur, None))
            cur = ""
        cur += c
    if cur:
        out.append((cur, None))
    return out


# Zhuyin -> Pinyin (toneless). Built once from the rules; Pinyin typing is read through it.
_PY_INIT = dict(zip("ㄅㄆㄇㄈㄉㄊㄋㄌㄍㄎㄏㄐㄑㄒㄓㄔㄕㄖㄗㄘㄙ",
                    ["b", "p", "m", "f", "d", "t", "n", "l", "g", "k", "h", "j", "q", "x", "zh", "ch", "sh", "r", "z", "c", "s"]))
_PY_FIN = dict(zip("ㄚㄛㄜㄝㄞㄟㄠㄡㄢㄣㄤㄥㄦ", ["a", "o", "e", "e", "ai", "ei", "ao", "ou", "an", "en", "ang", "eng", "er"]))


def bpmf_to_pinyin(b):
    ini = b[0] if b[0] in INITIALS else ""
    rest = b[len(ini):]
    med = rest[0] if rest and rest[0] in MEDIALS else ""
    fin = rest[len(med):]
    i = _PY_INIT.get(ini, "")
    f = _PY_FIN.get(fin, "") if fin else ""
    if not med:
        if not fin:
            return i + "i" if ini and ini in "ㄓㄔㄕㄖㄗㄘㄙ" else None  # (a bare ㄅ is no syllable in Pinyin)
        return i + f
    if med == "ㄧ":
        body = {"": "i", "ㄚ": "ia", "ㄛ": "io", "ㄝ": "ie", "ㄞ": "iai", "ㄠ": "iao", "ㄡ": "iu", "ㄢ": "ian", "ㄣ": "in",
                "ㄤ": "iang", "ㄥ": "ing"}.get(fin)
        if body is None:
            return None
        if not ini:
            return {"i": "yi", "in": "yin", "ing": "ying", "iu": "you"}.get(body, "y" + body[1:])
        return i + body
    if med == "ㄨ":
        body = {"": "u", "ㄚ": "ua", "ㄛ": "uo", "ㄞ": "uai", "ㄟ": "ui", "ㄢ": "uan", "ㄣ": "un", "ㄤ": "uang", "ㄥ": "ong"}.get(fin)
        if body is None:
            return None
        if not ini:
            return {"u": "wu", "ui": "wei", "un": "wen", "ong": "weng"}.get(body, "w" + body[1:])
        return i + body
    body = {"": "v", "ㄝ": "ve", "ㄢ": "van", "ㄣ": "vn", "ㄥ": "iong"}.get(fin)  # ㄩ: ü (typed v)
    if body is None:
        return None
    if not ini:
        return {"v": "yu", "ve": "yue", "van": "yuan", "vn": "yun", "iong": "yong"}[body]
    if ini in "ㄐㄑㄒ":
        return i + body.replace("v", "u")
    return i + body


class Chinese:
    """Phrases by sound, scored like McBopomofo: the sentence with the best total score wins."""

    def __init__(self, simplified=False):
        # Simplified: mainland words and how often they're used (zhs.dic); Traditional: Taiwan's (zh.dic)
        own = simplified and os.path.exists(os.path.join(DATA, "zhs.dic"))
        self.dic = table("zhs.dic" if own else "zh.dic")
        self.simplified = simplified and not own  # (no own list: convert the Traditional one)
        self.t2s = None
        self.cache = {}
        self._py = None

    # -- data
    def phrases(self, key):
        """[(reading with tones, phrase, score)] for a toneless key like 'ㄋㄧ-ㄏㄠ'."""
        if key in self.cache:
            return self.cache[key]
        v = self.dic.get(key)
        out = []
        if v:
            for rec in bytes(v).decode("utf-8").split("\x1e"):
                r, p, s = rec.split("\x1f")
                out.append((r, p, float(s)))
        if len(self.cache) > 6000:
            self.cache.clear()
        self.cache[key] = out
        return out

    def pinyin_map(self):
        """pinyin syllable -> Zhuyin sound (toneless), from every single-syllable reading in the dictionary."""
        if self._py is None:
            m = {}
            for k, _ in self.dic.starting(b"", limit=10 ** 7):
                if "-" in k:
                    continue
                py = bpmf_to_pinyin(k) if k and k[0] in INITIALS + MEDIALS + FINALS else None
                if py and py not in m:
                    m[py] = k
            self._py = m
            self._pypre = {p[:i] for p in m for i in range(1, len(p) + 1)}
        return self._py

    def conv(self, text):
        """Traditional -> Simplified when that's what you type."""
        if not self.simplified:
            return text
        if self.t2s is None:
            d = {}
            try:
                with open(os.path.join(DATA, "t2s.txt"), encoding="utf-8") as f:
                    for line in f:
                        a, _, b = line.rstrip("\n").partition("\t")
                        if a and b and a not in d:
                            d[a] = b
            except OSError:
                pass
            self.t2s = d
            self.t2s_max = max((len(k) for k in d), default=1)
        out, i = [], 0
        while i < len(text):
            for n in range(min(self.t2s_max, len(text) - i), 0, -1):
                if text[i:i + n] in self.t2s:
                    out.append(self.t2s[text[i:i + n]])
                    i += n
                    break
            else:
                out.append(text[i])
                i += 1
        return "".join(out)

    @staticmethod
    def _tones_fit(reading, tones):
        rs = reading.split("-")
        for r, t in zip(rs, tones):
            if t is None:
                continue
            rt = r[-1] if r and r[-1] in TONES else ""
            if rt != t:
                return False
        return True

    def words_at(self, sounds, tones, i, maxlen=6):
        """Phrases that start at syllable i: [(syllables used, phrase, score)], best first per length."""
        out = []
        for k in range(1, min(maxlen, len(sounds) - i) + 1):
            key = "-".join(sounds[i:i + k])
            got = {}
            for r, p, s in self.phrases(key):
                if self._tones_fit(r, tones[i:i + k]) and (p not in got or s > got[p]):
                    got[p] = s
            for p, s in got.items():
                out.append((k, p, s))
        return out

    def best(self, sounds, tones):
        """Best-scoring sentence over the syllables: [(syllables, phrase)]."""
        L = len(sounds)
        bestv = [None] * (L + 1)
        bestv[0] = (0.0, None)
        for i in range(L):
            if bestv[i] is None:
                continue
            ws = self.words_at(sounds, tones, i)
            if not any(k == 1 for k, _, _ in ws):  # a sound with no character: keep it as typed
                ws.append((1, sounds[i] + (tones[i] or ""), -100.0))
            for k, p, s in ws:
                v = bestv[i][0] + s
                if bestv[i + k] is None or v > bestv[i + k][0]:
                    bestv[i + k] = (v, (i, p))
        out, j = [], L
        while j > 0:
            i, p = bestv[j][1]
            out.append((j - i, p))
            j = i
        return out[::-1]

    def candidates(self, sounds, tones, n=30):
        """[(text, syllables used)]: the whole sentence, then phrases that start it (longest first)."""
        if not sounds:
            return []
        out, seen = [], set()

        def add(text, used):
            text = self.conv(text)
            if text not in seen:
                seen.add(text)
                out.append((text, used))
        path = self.best(sounds, tones)
        add("".join(p for _, p in path), len(sounds))
        first = path[0][0]  # the sentence's own first word and the other ways to write it come next
        ws = sorted(self.words_at(sounds, tones, 0), key=lambda e: (e[0] != first, -e[0], -e[2]))
        for k, p, s in ws:
            add(p, k)
            if len(out) >= n:
                break
        return out

    # -- Pinyin: split letters into syllables
    def pinyin_paths(self, letters):
        """Syllable splits of the letters: for each start, [(end, zhuyin sound)]."""
        m = self.pinyin_map()
        L = len(letters)
        edges = [[] for _ in range(L + 1)]
        for i in range(L):
            if letters[i] == "'":
                edges[i].append((i + 1, None))
                continue
            for j in range(i + 1, min(L, i + 6) + 1):
                p = letters[i:j]
                if p not in self._pypre:
                    break
                if p in m:
                    edges[i].append((j, m[p]))
        return edges

    def pinyin_candidates(self, letters, n=30):
        """[(text, letters used)] for typed Pinyin. Letters that don't make a syllable yet wait at the end."""
        edges = self.pinyin_paths(letters)
        L = len(letters)
        # best[pos] = (score, back) over letter positions; a word spans one or more syllables
        best = [None] * (L + 1)
        best[0] = (0.0, None)
        firsts, nexts = [], {}
        for i in range(L):
            if best[i] is None:
                continue
            for j, sounds, p, s in self._words_from(edges, i, letters):
                nexts.setdefault(i, set()).add(j)
                v = best[i][0] + s
                if best[j] is None or v > best[j][0]:
                    best[j] = (v, (i, p))
                if i == 0:
                    firsts.append((j, len(sounds), p, s))
        end = max(j for j in range(L + 1) if best[j] is not None)
        if end == 0:
            return []
        parts, j = [], end
        while j > 0:
            i, p = best[j][1]
            parts.append((j, p))
            j = i
        parts = parts[::-1]
        # only first words the rest can follow on from (no "ji" out of "jin...")
        ok = {end}
        for i in sorted(nexts, reverse=True):
            if nexts[i] & ok:
                ok.add(i)
        firsts = [f for f in firsts if f[0] in ok]
        first_end = parts[0][0]
        out, seen = [], set()

        def add(text, used):
            text = self.conv(text)
            if text not in seen:
                seen.add(text)
                out.append((text, used))
        add("".join(p for _, p in parts), end)
        for j, k, p, s in sorted(firsts, key=lambda e: (e[0] != first_end, -e[1], -e[3])):
            add(p, j)
            if len(out) >= n:
                break
        return out

    def _words_from(self, edges, i, letters, maxlen=6):
        """Phrases starting at letter i: (end letter, sounds, phrase, score)."""
        out = []
        stack = [(i, [])]
        while stack:
            pos, sounds = stack.pop()
            if sounds:
                key = "-".join(sounds)
                got = {}
                for r, p, s in self.phrases(key):
                    if p not in got or s > got[p]:
                        got[p] = s
                for p, s in got.items():
                    out.append((pos, list(sounds), p, s))
                if not got and len(sounds) == 1:
                    pass
            if len(sounds) >= maxlen:
                continue
            for j, snd in edges[pos]:
                if snd is None:  # an apostrophe between syllables
                    if sounds:
                        stack.append((j, sounds))
                    elif pos == i:
                        stack.append((j, sounds))
                    continue
                if sounds and not self.dic.has_prefix("-".join(sounds + [snd])):
                    continue
                stack.append((j, sounds + [snd]))
        return out


class Cangjie:
    def __init__(self, quick=False):
        self.quick = quick
        self.dic = table("qk.dic" if quick else "cj.dic")

    def candidates(self, code, n=40):
        """Characters for the code typed so far: exact matches first, then ones whose code starts that way."""
        if not code:
            return []
        v = self.dic.get(code)
        out = list(bytes(v).decode("utf-8")) if v else []
        if len(code) < (2 if self.quick else 5):
            more = []
            for k, val in self.dic.starting(code, limit=400):
                if k != code:
                    more.extend((len(k), i, c) for i, c in enumerate(bytes(val).decode("utf-8")))
            for _, _, c in sorted(more):
                if c not in out:
                    out.append(c)
                if len(out) >= n:
                    break
        return [(c, len(code)) for c in out[:n]]


# --------------------------------------------------------------------------- Korean (2-set / Dubeolsik)
_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG = ["", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ",
         "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]
_VV = {("ㅗ", "ㅏ"): "ㅘ", ("ㅗ", "ㅐ"): "ㅙ", ("ㅗ", "ㅣ"): "ㅚ", ("ㅜ", "ㅓ"): "ㅝ", ("ㅜ", "ㅔ"): "ㅞ", ("ㅜ", "ㅣ"): "ㅟ", ("ㅡ", "ㅣ"): "ㅢ"}
_CC = {("ㄱ", "ㅅ"): "ㄳ", ("ㄴ", "ㅈ"): "ㄵ", ("ㄴ", "ㅎ"): "ㄶ", ("ㄹ", "ㄱ"): "ㄺ", ("ㄹ", "ㅁ"): "ㄻ", ("ㄹ", "ㅂ"): "ㄼ",
       ("ㄹ", "ㅅ"): "ㄽ", ("ㄹ", "ㅌ"): "ㄾ", ("ㄹ", "ㅍ"): "ㄿ", ("ㄹ", "ㅎ"): "ㅀ", ("ㅂ", "ㅅ"): "ㅄ"}
_CC_SPLIT = {v: k for k, v in _CC.items()}


def _syl(cho, jung, jong=""):
    return chr(0xAC00 + (_CHO.index(cho) * 21 + _JUNG.index(jung)) * 28 + _JONG.index(jong))


def hangul(jamo):
    """Compose typed jamo into syllables, the way a Korean keyboard does (ㅎㅏㄴㄱㅡㄹ -> 한글)."""
    out = []
    cho = jung = jong = ""

    def flush():
        nonlocal cho, jung, jong
        if cho and jung:
            out.append(_syl(cho, jung, jong))
        else:
            out.append(cho + jung + jong)
        cho = jung = jong = ""

    for c in jamo:
        if c in _JUNG:  # vowel
            if jong:  # the last consonant moves on to start the new syllable: 각 + ㅏ -> 가가
                if jong in _CC_SPLIT:
                    keep, move = _CC_SPLIT[jong]
                else:
                    keep, move = "", jong
                jong = keep
                flush()
                cho, jung = move, c
            elif jung and (jung, c) in _VV:
                jung = _VV[(jung, c)]
            elif cho and not jung:
                jung = c
            else:
                flush()
                jung = c
        elif c in _CHO or c in _JONG:  # consonant
            if cho and jung and not jong and c in _JONG:
                jong = c
            elif cho and jung and jong and (jong, c) in _CC:
                jong = _CC[(jong, c)]
            else:
                if cho or jung or jong:
                    flush()
                cho = c
        else:
            if cho or jung or jong:
                flush()
            out.append(c)
    if cho or jung or jong:
        flush()
    return "".join(out)


# --------------------------------------------------------------------------- Vietnamese (Telex)
_VI_TONES = {"s": "́", "f": "̀", "r": "̉", "x": "̃", "j": "̣"}
_VI_VOWELS = "aăâeêioôơuưy"
_VI_SPECIAL = "ăâêôơư"


def _vi_tone_index(word):
    """Which letter of the word takes the tone mark (the modern rule)."""
    low = word.lower()
    idx = [i for i, ch in enumerate(low) if ch in _VI_VOWELS]
    if not idx:
        return None
    # the vowel cluster (one run of vowels); qu / gi: their u / i belong to the consonant
    start = idx[0]
    end = start
    while end + 1 < len(low) and low[end + 1] in _VI_VOWELS:
        end += 1
    if (low[start] == "u" and start > 0 and low[start - 1] == "q") or (low[start] == "i" and start > 0 and low[start - 1] == "g"):
        if end > start:
            start += 1
    cl = low[start:end + 1]
    special = [start + k for k, ch in enumerate(cl) if ch in _VI_SPECIAL]
    if special:
        return special[-1]
    if len(cl) == 1:
        return start
    if end + 1 < len(low):                     # a consonant follows: the last vowel
        return end
    if len(cl) == 2:
        return start + 1 if cl in ("oa", "oe", "uy") else start
    return start + 1


def telex(keys):
    """Typed letters -> Vietnamese, the Telex way: aa â, aw ă, ee ê, oo ô, ow ơ, uw ư, dd đ, and s f r x j for the
    five tones (z takes the tone off; the same tone key twice types the letter itself)."""
    out, tone = [], None
    for k in keys:
        lk = k.lower()
        up = k != lk
        prev = out[-1] if out else ""
        lp = prev.lower()
        if lk in _VI_TONES and any(ch.lower() in _VI_VOWELS for ch in out):
            if tone == lk:                    # twice: the letter itself, no tone
                tone = None
                out.append(k)
            else:
                tone = lk
            continue
        if lk == "z" and tone is not None:
            tone = None
            continue
        if lk == "d" and lp == "d":
            out[-1] = "Đ" if prev.isupper() else "đ"
            continue
        if lk in "aeo" and lp == lk:
            out[-1] = {"a": "â", "e": "ê", "o": "ô"}[lk]
            out[-1] = out[-1].upper() if prev.isupper() else out[-1]
            continue
        if lk == "w":
            # uo + w -> ươ ; a -> ă ; o -> ơ ; u -> ư ; nothing to change -> ư
            low = "".join(out).lower()
            j = max((low.rfind(v) for v in "aou"), default=-1)
            i = low.rfind("uo")
            if i >= 0 and all(ch not in _VI_VOWELS for ch in low[i + 2:]):
                for pos, rep in ((i, "ư"), (i + 1, "ơ")):
                    out[pos] = rep.upper() if out[pos].isupper() else rep
                continue
            if j >= 0 and all(ch not in _VI_VOWELS for ch in low[j + 1:]):
                rep = {"a": "ă", "o": "ơ", "u": "ư"}[low[j]]
                out[j] = rep.upper() if out[j].isupper() else rep
                continue
            out.append("Ư" if up else "ư")
            continue
        out.append(k)
    word = "".join(out)
    if tone:
        i = _vi_tone_index(word)
        if i is not None:
            import unicodedata
            word = word[:i] + unicodedata.normalize("NFC", word[i] + _VI_TONES[tone]) + word[i + 1:]
    return word


# --------------------------------------------------------------------------- what the keyboard talks to
class Composer:
    """Text being typed but not sent yet (shown in the word bar), and what it can turn into.

    kind: 'ja', 'zhuyin', 'pinyin', 'cangjie', 'quick' or 'ko'."""

    JA_MARKS = "、。，．？！「」『』・…〜ー"

    def __init__(self, kind, simplified=False):
        self.kind, self.simplified = kind, simplified
        self.units = []      # what was typed: kana, Zhuyin symbols, letters or jamo
        self.romaji = None   # Japanese typed in English letters (a languages.Romaji)
        self.engine = None
        self.cands, self.cands_for = [], None
        self.lock = threading.Lock()

    def _engine(self):
        if self.engine is None:
            k = self.kind
            self.engine = (Japanese() if k == "ja" else Chinese(self.simplified) if k in ("zhuyin", "pinyin") else
                           Cangjie(k == "quick") if k in ("cangjie", "quick") else False)
        return self.engine

    def warm(self):
        """Open the dictionary ahead of time (in the background)."""
        try:
            e = self._engine()
            if self.kind == "pinyin":
                e.pinyin_map()
        except Exception:
            pass

    def buf(self):
        return self.romaji.buf if self.romaji else ""

    def empty(self):
        return not self.units and not self.buf()

    def clear(self):
        self.units = []
        if self.romaji:
            self.romaji.reset()

    def key(self):
        return (tuple(self.units), self.buf())

    def text(self):
        """What's shown as typed so far."""
        if self.kind == "ko":
            return hangul(self.units)
        if self.kind == "vi":
            return telex(self.units)
        if self.kind == "zhuyin":
            return "".join(self.units).replace(" ", "")
        if self.kind in ("cangjie", "quick"):
            return "".join(RADICALS.get(c, c) for c in self.units)
        return "".join(self.units) + self.buf()

    def add(self, c):
        """Takes one typed character. False if it isn't part of what's being composed (then the keyboard types it)."""
        k = self.kind
        if k == "ja":
            if self.romaji is not None and ((c.isascii() and c.isalpha()) or (c == "'" and self.romaji.buf)):
                res = self.romaji.feed(c)
                if res:
                    _, out = res
                    keep = len(self.romaji.buf)
                    self.units.extend(out[:len(out) - keep] if keep else out)
                return True
            if "\u3041" <= c <= "\u30fa" or c in "ーゝゞヽヾ" or c in self.JA_MARKS or (c.isascii() and c.isalnum()):
                self._flush_romaji()
                self.units.append(c)
                return True
            return False
        if k == "zhuyin":
            if c in INITIALS + MEDIALS + FINALS + TONES or (c == " " and self.wants_space()):
                self.units.append(c)
                return True
            return False
        if k == "pinyin":
            if c.isascii() and (c.isalpha() or (c == "'" and self.units)):
                self.units.append(c.lower())
                return True
            return False
        if k in ("cangjie", "quick"):
            if c.isascii() and c.isalpha() and c.lower() != "z" and len(self.units) < (2 if k == "quick" else 5):
                self.units.append(c.lower())
                return True
            return False
        if k == "vi":
            if c.isascii() and c.isalpha():
                self.units.append(c)
                return True
            return False
        if k == "ko":
            if c in _CHO or c in _JUNG or c in _JONG:
                self.units.append(c)
                return True
            return False
        return False

    def _flush_romaji(self):
        if self.romaji and self.romaji.buf:
            res = self.romaji.flush()
            if res:
                self.units.extend(res[1])
            elif self.romaji.buf:
                self.units.extend(self.romaji.buf)
            self.romaji.reset()

    def back(self):
        if self.romaji and self.romaji.buf:
            self.romaji.back()
            return True
        if self.units:
            self.units.pop()
            return True
        return False

    def change_last(self, fn):
        """゛゜ / 小 keys: change the last kana typed (か -> が, つ -> っ). True if it did."""
        if self.units and not self.buf():
            n = fn(self.units[-1])
            if n:
                self.units[-1] = n
                return True
        return False

    def wants_space(self):
        """Zhuyin: Space right after a sound is its 1st tone."""
        if self.kind != "zhuyin" or not self.units:
            return False
        last = self.units[-1]
        return last not in TONES and last != " "

    def candidates(self):
        """[(text, units used)], for what's typed right now. Cached until it changes; safe to call from a
        background thread (it works on a copy)."""
        units, buf = list(self.units), self.buf()
        key = (tuple(units), buf)
        with self.lock:
            if self.cands_for == key:
                return self.cands
        try:
            out = self._compute(units, buf)
        except Exception:
            out = []
        with self.lock:
            if self.key() == key:
                self.cands, self.cands_for = out, key
        return out

    def ready(self):
        with self.lock:
            return self.cands_for == self.key()

    def _compute(self, units, buf):
        e = self._engine()
        k = self.kind
        if k == "ja":
            s = "".join(units) + ("ん" if buf in ("n", "nn") else "")
            if not s:
                return []
            out = e.candidates(s)
            if buf and buf not in ("n", "nn"):  # letters that aren't kana yet stay on the end of the sentence
                out = [(t + buf, u) for t, u in out[:1]] + out[1:]
            return out
        if k == "zhuyin":
            syl = zhuyin_syllables(units)
            sounds, tones = [a for a, _ in syl], [b for _, b in syl]
            return [(t, self._zhuyin_units(units, syl, u)) for t, u in e.candidates(sounds, tones)]
        if k == "pinyin":
            return e.pinyin_candidates("".join(units))
        if k in ("cangjie", "quick"):
            return e.candidates("".join(units))
        return []

    @staticmethod
    def _zhuyin_units(units, syl, used):
        """How many typed symbols make up the first `used` syllables."""
        if used >= len(syl):
            return len(units)
        got = zhuyin_syllables(units)
        n = 0
        for i in range(1, len(units) + 1):  # the shortest start of the input that holds those syllables
            part = zhuyin_syllables(units[:i])
            if len(part) >= used and part[:used] == got[:used]:
                n = i
                break
        return n or len(units)

    def take(self, text, used):
        """A candidate was picked: returns the text to type; what it didn't use stays to be converted."""
        if self.kind == "ja" and used >= len(self.units):
            self.units = []
            if self.romaji:
                self.romaji.reset()
        elif used < len(self.units):
            self.units = self.units[used:]
            while self.units and self.units[0] in ("'", " "):
                self.units.pop(0)
        else:
            self.units = []
            if self.romaji:
                self.romaji.reset()
        return text

    def raw(self):
        """Commit what's typed as it is (Japanese kana, Pinyin letters, Hangul)."""
        if self.kind == "ja":
            self._flush_romaji()
        t = self.text() if self.kind not in ("cangjie", "quick") else "".join(self.units)
        self.clear()
        return t


RADICALS = dict(zip("abcdefghijklmnopqrstuvwxyz", "日月金木水火土竹戈十大中一弓人心手口尸廿山女田難卜重"))
