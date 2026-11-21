# SPDX-FileCopyrightText: Apple Inc.
# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: APSL-2.0

"""The phone's hyphenation: Liang's patterns applied the way CoreFoundation does.

    python -m dedala.twin.hyphenate word [word...]       where each word may break, en_US

Apple compiles its LinguisticData tries from the TeX community's patterns: here hyph-utf8's
(`hyphenation/hyph-<tag>.tex`, from the tex-hyphen project, under the notice it carries), with the patterns the
phone's own differ by (`ADJUSTED`, found by comparing where each breaks words). Apple also keeps some 1,300 exception
words, many of them its products, places and teams, which no open file holds: with Knuth's fourteen instead, 22 of
56,772 lines the phone laid out broke elsewhere than on it. `before` transcribes
`CFStringGetHyphenationLocationBeforeIndex` down through `__CFHyphenationGetHyphenationLocations` (the word's
apostrophes, camel-case boundaries, exception words) and `__CFHyphenationGetHyphensForString` (the pattern loop)
from Apple's open-source CoreFoundation.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = {"en_US": ("hyph-en-us.tex",)}
ADJUSTED = {"en_US": {"added": ("ick1e", ".mc5", "c3kee"), "dropped": ("ck", "cki", "gw", "polyphono", "schroding", "traversab")}}
MAX_PATTERN = 8
LOOKAHEAD = 20
APOSTROPHES = "'’"
ELISIONS = "cdjlnst"
CONTRACTIONS = ("re", "ve", "ll", "er", "ed")
EXCEPTION = 0xF0000000


def patterns(path):
    """A TeX file's patterns (\\patterns{…}) and exception words (\\hyphenation{…}), keyed as CoreFoundation's tries key
    them: a pattern by its letters, with the levels before each letter and after the last packed three bits each, the
    first highest; an exception by the word, with every bit but those after its hyphenated letters set."""
    text = open(path, encoding="utf-8").read()
    entries = dict(pattern(token) for token in block(text, "patterns"))
    for token in block(text, "hyphenation"):
        bits = 0
        position = 0
        for character in token:
            if character == "-":
                bits |= 1 << (position - 1)
            else:
                position += 1
        entries[token.replace("-", "").lower().encode("utf-8")] = ~bits & 0xFFFFFFFF
    return entries


def pattern(token):
    letters = re.sub(r"\d", "", token)
    levels = [0] * (len(letters) + 1)
    position = 0
    for character in token:
        if character.isdigit():
            levels[position] = int(character)
        else:
            position += 1
    packed = 0
    for level in levels:
        packed = packed * 8 + level
    return letters.encode("utf-8"), packed


def block(text, command):
    """The words of a TeX file's \\command{…}, comments left out."""
    if f"\\{command}{{" not in text:
        return []
    body = text.split(f"\\{command}{{", 1)[1].split("}", 1)[0]
    return [word for line in body.splitlines() for word in line.split("%", 1)[0].split()]


class Hyphenator:
    tries = {}

    @classmethod
    def entries(cls, language="en_US"):
        if language not in cls.tries:
            paths = [os.path.join(HERE, "hyphenation", name) for name in FILES.get(language, ())]
            entries = {key: value for path in paths for key, value in patterns(path).items()} if paths else None
            if entries is not None:
                adjusted = ADJUSTED.get(language, {})
                for letters in adjusted.get("dropped", ()):
                    entries.pop(letters.encode("utf-8"), None)
                entries.update(pattern(token) for token in adjusted.get("added", ()))
            cls.tries[language] = entries
        return cls.tries[language]

    @classmethod
    def available(cls, language="en_US"):
        return cls.entries(language) is not None

    @staticmethod
    def trimmed(text):
        """The letters CoreFoundation hyphenates within a word: without a leading apostrophe or French elision
        (l', qu'), without a trailing apostrophe or English contraction ('s, 're)."""
        n = len(text)
        prefix = 0
        if text[0] in APOSTROPHES:
            prefix = 1
        elif text[0] in ELISIONS and text[1] in APOSTROPHES:
            prefix = 2
        elif text[0] == "q" and text[1] == "u" and text[2] in APOSTROPHES:
            prefix = 3
        rest = n - prefix
        if rest <= 0:
            return 0, 0
        last = n - 1
        if text[last] in APOSTROPHES:
            last = n - 2
        elif rest != 1:
            if text[n - 2] in APOSTROPHES and text[n - 1] in "dst":
                last = n - 3
            elif rest > 2 and text[n - 3] in APOSTROPHES and text[n - 2:] in CONTRACTIONS:
                last = n - 4
        if last < prefix or last == prefix:
            return 0, n
        return prefix, last - prefix + 1

    @classmethod
    def before(cls, token, index, language="en_US"):
        """The offset where the token (a word as ICU segments it) may be hyphenated before `index`, else None."""
        entries = cls.entries(language)
        text = token[:index + LOOKAHEAD]
        if entries is None or len(text) <= 4:
            return None
        prefix, m = cls.trimmed(text)
        if m <= 4:
            return None
        word = text[prefix:prefix + m]
        exception = entries.get(word.lower().encode("utf-8"), 0)
        if exception >= EXCEPTION:
            if exception == 0xFFFFFFFF:
                return None
            bits = ~exception & 0xFFFFFFFF
            location = prefix + 1 + (bits & -bits).bit_length() - 1
            return location if location < index else None
        location = cls.liang(word, entries, index - prefix)
        return None if location is None else prefix + location

    @staticmethod
    def liang(word, entries, limit):
        """`__CFHyphenationGetHyphensForString` asked for one location: the rightmost odd level at or before `limit`."""
        n = len(word)
        text = "." + word.lower() + "."
        chars = [c.encode("utf-8") for c in text]
        levels = [0] * (n + 3)
        for end in range(n + 2, 1, -1):
            start = max(0, end - MAX_PATTERN)
            if start > limit:
                continue
            if end <= n and 2 < end - 1 and end + 1 < n and word[end - 2].islower() and word[end - 1].isupper():
                levels[end] = 9
            for start in range(start, end):
                if start > limit:
                    break
                payload = entries.get(b"".join(chars[start:end]), 0)
                if not payload or payload >= EXCEPTION:
                    continue
                for slot in range(end, start - 1, -1):
                    if levels[slot] < payload & 7:
                        levels[slot] = payload & 7
                    payload >>= 3
        if n < 4:
            return None
        for position in range(n, 3, -1):
            if levels[position - 1] & 1 and position - 1 <= limit:
                return position - 2
        return None

    @classmethod
    def points(cls, word, language="en_US"):
        """Every location the phone finds walking back from the word's end, left to right."""
        points = []
        index = len(word)
        while index > 0:
            location = cls.before(word, index, language)
            if location is None or location <= 0:
                break
            points.append(location)
            index = location
        return points[::-1]


if __name__ == "__main__":
    for word in sys.argv[1:]:
        points = Hyphenator.points(word)
        print("-".join(word[a:b] for a, b in zip([0] + points, points + [len(word)])))
