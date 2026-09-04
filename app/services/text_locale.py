"""Deterministic locale normalization shared by every Input modality."""

from __future__ import annotations

import unicodedata
from functools import lru_cache


@lru_cache(maxsize=2)
def _opencc_converter(config: str):
    try:
        from opencc import OpenCC

        return OpenCC(config)
    except (ImportError, OSError, RuntimeError):
        return None


def normalize_content_text(text: str, *, locale: str = "zh-TW") -> str:
    """Normalize Unicode and, for Taiwan locales, convert to Taiwanese Hant.

    The transformation is source-agnostic and deterministic.  It fixes script
    variation only; it never guesses domain terms or silently changes numbers.
    """
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    normalized_locale = str(locale or "").replace("_", "-").casefold()
    if normalized_locale not in {"zh", "zh-tw", "zh-hant", "zh-hant-tw"}:
        return normalized
    # Script conversion only: phrase-level Taiwan substitutions (for example
    # 設備→裝置 or 台→臺) would alter literal source evidence and field labels.
    converter = _opencc_converter("s2t")
    if converter is not None:
        # 「台」 is valid and overwhelmingly common in Taiwanese company and
        # place names. OpenCC's generic S2T maps it to「臺」, which would mutate
        # exact names even when the source was already Traditional Chinese.
        protected = normalized.replace("台", "\ue000")
        return converter.convert(protected).replace("\ue000", "台")
    # Fail-soft for minimal installations. Production pins OpenCC; this map
    # keeps the most common workflow vocabulary interoperable in dev tools.
    return normalized.translate(
        str.maketrans(
            {
                "发": "發",
                "复": "復",
                "归": "歸",
                "压": "壓",
                "门": "門",
                "锁": "鎖",
                "责": "責",
                "机": "機",
                "关": "關",
                "应": "應",
                "进": "進",
                "员": "員",
                "资": "資",
                "处": "處",
                "为": "為",
                "业": "業",
                "产": "產",
                "线": "線",
                "录": "錄",
                "频": "頻",
                "视": "視",
            }
        )
    )
