"""
YouTube transkript metni için veri temizleme (text post-processing).
LLM beslemesi veya kullanıcı okuması için uygun hale getirir.
"""
import re
from typing import List, Optional, Union


# Zaman damgası desenleri: 00:00:12 --> 00:00:15, 00:00.000 --> 00:00.500, vb.
TIMESTAMP_PATTERN = re.compile(
    r"\d{1,2}:\d{2}(?::\d{2})?(?:\.\d{1,3})?\s*-->\s*\d{1,2}:\d{2}(?::\d{2})?(?:\.\d{1,3})?",
    re.IGNORECASE,
)
# Tekil zaman damgası: 00:01:23 veya 01:23
SINGLE_TIMESTAMP_PATTERN = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\.\d{1,3})?\b")
# HTML etiketleri
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
# Köşeli parantez içi ses efektleri: [Music], [Applause], [Laughter], vb.
SOUND_EFFECT_PATTERN = re.compile(r"\[[^\]]*\]")


def remove_timestamps(text: str) -> str:
    """Zaman damgalarını (00:00:12 --> 00:00:15) ve tekil zamanları temizler."""
    text = TIMESTAMP_PATTERN.sub("", text)
    text = SINGLE_TIMESTAMP_PATTERN.sub("", text)
    return text


def remove_html_tags(text: str) -> str:
    """HTML etiketlerini tamamen kaldırır."""
    return HTML_TAG_PATTERN.sub("", text)


def remove_sound_effects(text: str) -> str:
    """[Music], [Applause], [Laughter] gibi köşeli parantez içi ses efektlerini kaldırır."""
    return SOUND_EFFECT_PATTERN.sub("", text)


def deduplicate_consecutive_words(text: str) -> str:
    """Peş peşe gelen aynı kelimeleri tekilleştirir (YouTube kekeleme düzeltmesi)."""
    words = text.split()
    if not words:
        return ""
    result = [words[0]]
    for w in words[1:]:
        if w != result[-1]:
            result.append(w)
    return " ".join(result)


def clean_text(
    text: str,
    remove_timestamps_flag: bool = True,
    remove_html: bool = True,
    remove_sound_effects_flag: bool = True,
    deduplicate_words: bool = True,
) -> str:
    """
    Ham transkript metnini temizler.
    """
    if not text or not text.strip():
        return ""

    t = text.strip()

    if remove_timestamps_flag:
        t = remove_timestamps(t)
    if remove_html:
        t = remove_html_tags(t)
    if remove_sound_effects_flag:
        t = remove_sound_effects(t)

    # Fazla boşlukları birleştir
    t = re.sub(r"\s+", " ", t).strip()

    if deduplicate_words:
        t = deduplicate_consecutive_words(t)

    return t


def split_into_paragraphs(
    text: str,
    max_sentences: int = 5,
    max_chars: int = 500,
) -> List[str]:
    """
    Metni mantıklı paragraflara böler.
    Her paragraf en fazla max_sentences cümle veya max_chars karakter olur.
    """
    if not text or not text.strip():
        return []

    # Cümle sınırları: . ! ? sonrası boşluk veya satır sonu
    sentence_end = re.compile(r"(?<=[.!?])\s+")
    sentences = [s.strip() for s in sentence_end.split(text) if s.strip()]
    if not sentences:
        return [text.strip()] if text.strip() else []

    paragraphs = []
    current = []
    current_len = 0

    for sent in sentences:
        current.append(sent)
        current_len += len(sent) + 1  # +1 boşluk

        if len(current) >= max_sentences or current_len >= max_chars:
            para = " ".join(current)
            paragraphs.append(para)
            current = []
            current_len = 0

    if current:
        paragraphs.append(" ".join(current))

    return paragraphs


def clean_transcript(
    segments: List[dict],
    *,
    remove_sound_effects_flag: bool = True,
    deduplicate_words: bool = True,
    split_paragraphs: bool = False,
    max_sentences: int = 5,
    max_chars: int = 500,
) -> Union[str, List[str]]:
    """
    Segment listesinden temiz metin üretir.
    segments: [{"text": "...", "start": 0, "duration": 1.5}, ...]

    split_paragraphs=True ise paragraf listesi, False ise tek metin döner.
    """
    texts = [s.get("text", "") for s in segments if s.get("text")]
    raw = " ".join(texts)

    cleaned = clean_text(
        raw,
        remove_timestamps_flag=True,
        remove_html=True,
        remove_sound_effects_flag=remove_sound_effects_flag,
        deduplicate_words=deduplicate_words,
    )

    if not cleaned:
        return [] if split_paragraphs else ""

    if split_paragraphs:
        return split_into_paragraphs(cleaned, max_sentences=max_sentences, max_chars=max_chars)
    return cleaned
