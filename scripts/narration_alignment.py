"""Read real ASR boundaries without inventing per-character timestamps."""
from __future__ import annotations

import math
import re
import unicodedata


def normalize(text: str) -> str:
    return re.sub(r'[\W_]', '', unicodedata.normalize('NFKC', str(text))).lower()


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    return float(value)


def words_from_asr(data: dict) -> list[dict]:
    words = []
    previous = -1.0
    for segment in data.get('segments', []):
        for raw in segment.get('words', []):
            text = normalize(raw.get('text', raw.get('word', '')))
            if not text:
                continue
            start, end = finite(raw.get('start'), 'word.start'), finite(raw.get('end'), 'word.end')
            if start < 0 or end <= start or start < previous:
                raise ValueError('ASR words have invalid or non-monotonic time boundaries')
            probability = raw.get('probability')
            if probability is not None:
                probability = finite(probability, 'word.probability')
                if not 0 <= probability <= 1:
                    raise ValueError('word.probability outside 0..1')
            words.append({'text': text, 'raw': raw.get('text', raw.get('word', '')),
                          'start': start, 'end': end, 'probability': probability})
            previous = start
    if not words:
        raise ValueError('ASR contains no timed words; run word-timestamp transcription')
    return words


def occurrences(words: list[dict], text: str) -> list[dict]:
    needle = normalize(text)
    if not needle:
        raise ValueError('Anchor must contain spoken text')
    joined = ''.join(w['text'] for w in words)
    char_to_word, starts = [], set()
    for index, word in enumerate(words):
        starts.add(len(char_to_word))
        char_to_word.extend([index] * len(word['text']))
    result, offset = [], 0
    while (position := joined.find(needle, offset)) >= 0:
        first, last = char_to_word[position], char_to_word[position + len(needle) - 1]
        probabilities = [w['probability'] for w in words[first:last + 1]]
        result.append({'word_index': first, 'last_word_index': last,
                       'at_word_boundary': position in starts,
                       'start': words[first]['start'], 'end': words[last]['end'],
                       'minimum_probability': min(probabilities) if all(p is not None for p in probabilities) else None})
        offset = position + 1
    return result
