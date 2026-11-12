"""Rule-based Hangul pronunciation for Rioplatense (Buenos Aires) Spanish.

    >>> to_hangul("¿Dónde está mi celular?")
    '¿돈데 에스따 미 셀룰라르?'
    >>> to_hangul("Me llamo Ana. ¿Tenés la llave?")
    '메 샤모 아나. ¿떼네스 라 샤베?'
    >>> to_hangul("Mañana voy al baño. Hablo español.")
    '마냐나 보이 알 바뇨. 아블로 에스빠뇰.'
    >>> to_hangul("Che, ¿querés un mate? Yo soy de Corea.")
    '체, ¿께레스 운 마떼? 쇼 소이 데 꼬레아.'

Conventions (Korean-friendly, Argentine accent):
- c/qu/k → ㄲ, t → ㄸ, p → ㅃ (Spanish stops are unaspirated)
- ll / y + vowel → 샤 셰 시 쇼 슈 (Buenos Aires 'sh'), ñ → 냐 녜 니 뇨 뉴
- ce/ci/z/s → ㅅ (seseo), ge/gi/j → ㅎ, h silent, v = b → ㅂ
- intervocalic l doubles (hola → 올라); final s/r/d… become 스/르/드
- vowel sequences are written as separate syllables (bueno → 부에노)
"""
from __future__ import annotations

import re
import unicodedata

# choseong indexes
CHO = {"g": 0, "kk": 1, "n": 2, "d": 3, "tt": 4, "r": 5, "m": 6, "b": 7, "pp": 8, "s": 9,
       "": 11, "ch": 14, "p": 17, "h": 18}
# jungseong indexes
VOW = {"a": 0, "e": 5, "i": 20, "o": 8, "u": 13, "eu": 18}
Y_VOW = {"a": 2, "e": 7, "i": 20, "o": 12, "u": 17}  # ya ye i yo yu
# jongseong indexes
JONG = {"": 0, "n": 4, "l": 8, "m": 16}

# phoneme -> choseong key
ONSET = {"b": "b", "d": "d", "f": "p", "G": "g", "H": "h", "K": "kk", "l": "r", "m": "m", "n": "n",
         "p": "pp", "r": "r", "R": "r", "S": "s", "t": "tt", "C": "ch", "L": "s", "N": "n"}
CLUSTER_FIRST = set("bKdfGpt")  # C + l/r onset clusters
VOWELS = set("aeiou")


def _phonemes(word: str) -> list[str]:
    w = word.lower().replace("ñ", "\x00").replace("ü", "w")  # keep ñ/ü before stripping accents
    w = unicodedata.normalize("NFD", w)
    w = "".join(c for c in w if unicodedata.category(c) != "Mn").replace("\x00", "ñ")
    out: list[str] = []
    i = 0
    while i < len(w):
        c, nxt = w[i], w[i + 1] if i + 1 < len(w) else ""
        nxt2 = w[i + 2] if i + 2 < len(w) else ""
        if c == "c" and nxt == "h": out.append("C"); i += 2; continue
        if c == "l" and nxt == "l": out.append("L"); i += 2; continue
        if c == "r" and nxt == "r": out.append("R"); i += 2; continue
        if c == "q" and nxt == "u": out.append("K"); i += 2; continue
        if c == "g" and nxt == "u" and nxt2 in ("e", "i"): out.append("G"); i += 2; continue
        if c == "c": out.append("S" if nxt in ("e", "i") else "K"); i += 1; continue
        if c == "g": out.append("H" if nxt in ("e", "i") else "G"); i += 1; continue
        if c == "y": out.append("L" if nxt in VOWELS else "i"); i += 1; continue
        mapping = {"z": "S", "s": "S", "j": "H", "v": "b", "k": "K", "ñ": "N", "w": "u", "h": None, "x": "KS"}
        if c in mapping:
            if mapping[c]: out.extend(mapping[c])
            i += 1; continue
        if c in VOWELS or c in "bdflmnprt":
            out.append(c)
        i += 1
    return out


def _syl(cho: str, vow: int, jong: str = "") -> str:
    return chr(0xAC00 + (CHO[cho] * 21 + vow) * 28 + JONG[jong])


def _word(word: str) -> str:
    ph = _phonemes(word)
    sylls: list[list] = []  # [cho, vow_index, jong]
    i = 0
    while i < len(ph):
        p = ph[i]
        nxt = ph[i + 1] if i + 1 < len(ph) else ""
        if p in VOWELS:
            sylls.append(["", VOW[p], ""]); i += 1; continue
        # consonant + vowel -> onset
        if nxt in VOWELS:
            if p == "l" and sylls and sylls[-1][2] == "" and i > 0 and ph[i - 1] in VOWELS:
                sylls[-1][2] = "l"  # intervocalic l: hola -> 올라
            vow = Y_VOW[nxt] if p in ("L", "N") else VOW[nxt]
            sylls.append([ONSET[p], vow, ""]); i += 2; continue
        # C + l/r + vowel cluster: first consonant gets its own 'ㅡ' syllable
        nxt2 = ph[i + 2] if i + 2 < len(ph) else ""
        if p in CLUSTER_FIRST and nxt in ("l", "r") and nxt2 in VOWELS:
            sylls.append([ONSET[p], VOW["eu"], "l" if nxt == "l" else ""]); i += 1; continue
        # coda
        if p in ("n", "m", "l") and sylls and sylls[-1][2] == "":
            sylls[-1][2] = p; i += 1; continue
        if p in ("L", "N"):
            sylls.append([ONSET[p], VOW["i"], ""]); i += 1; continue
        sylls.append([ONSET[p], VOW["eu"], ""]); i += 1
    return "".join(_syl(*s) for s in sylls)


def to_hangul(text: str) -> str:
    return re.sub(r"[^\W\d_]+", lambda m: _word(m.group(0)), text)


if __name__ == "__main__":
    import doctest, sys
    doctest.testmod()
    for t in sys.argv[1:]:
        print(t, "→", to_hangul(t))
