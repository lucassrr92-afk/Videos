"""Legendas animadas estilo "Hormozi/MrBeast" em ASS (libass).

- Blocos de 1 a 3 palavras, em caixa alta, fonte pesada com contorno grosso.
- A palavra falada no momento fica destacada (cor + leve "pop" de escala).
- Título de gancho no topo nos primeiros segundos.
"""
from __future__ import annotations

from pathlib import Path

PRESETS = {
    # nome: (cor primária, cor de destaque, contorno)  — cores ASS: &HBBGGRR&
    "amarelo": ("&H00FFFFFF", "&H0000E5FF", "&H00000000"),
    "verde": ("&H00FFFFFF", "&H0000FF7F", "&H00000000"),
    "rosa": ("&H00FFFFFF", "&H00B469FF", "&H00000000"),
    "branco": ("&H00FFFFFF", "&H00FFFFFF", "&H00000000"),
}


def _ts(t: float) -> str:
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(word: str) -> str:
    return word.replace("{", "").replace("}", "").replace("\\", "").strip()


def chunk_words(words: list[dict], max_words: int = 3, max_gap: float = 0.6, max_chars: int = 18) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        if cur and (
            len(cur) >= max_words
            or w["start"] - cur[-1]["end"] > max_gap
            or sum(len(x["word"]) + 1 for x in cur) + len(w["word"]) > max_chars
            or cur[-1]["word"].rstrip().endswith((".", "?", "!"))
        ):
            chunks.append(cur)
            cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def build_ass(
    words: list[dict],
    out_path: Path,
    width: int,
    height: int,
    hook_title: str = "",
    hook_seconds: float = 3.0,
    font: str = "Inter Black",
    preset: str = "amarelo",
    font_size: int = 92,
) -> Path:
    """`words` devem ter tempos relativos ao início do corte já final."""
    primary, highlight, outline = PRESETS.get(preset, PRESETS["amarelo"])
    margin_v = int(height * 0.30)  # acima da UI das plataformas
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},{font_size},{primary},{highlight},{outline},&H80000000,-1,0,0,0,100,100,0,0,1,7,3,2,60,60,{margin_v},1
Style: Hook,{font},{int(font_size * 0.78)},&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,18,0,8,80,80,{int(height * 0.12)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    if hook_title:
        lines.append(
            f"Dialogue: 1,{_ts(0)},{_ts(hook_seconds)},Hook,,0,0,0,,"
            r"{\fad(150,250)\t(0,180,\fscx108\fscy108)\t(180,320,\fscx100\fscy100)}" + _clean(hook_title).upper()
        )

    for chunk in chunk_words(words):
        chunk_end = chunk[-1]["end"]
        for i, w in enumerate(chunk):
            start = w["start"]
            end = chunk[i + 1]["start"] if i + 1 < len(chunk) else max(chunk_end, start + 0.25)
            parts = []
            for j, x in enumerate(chunk):
                txt = _clean(x["word"]).upper()
                if j == i:
                    parts.append(
                        r"{\c" + highlight + r"\fscx112\fscy112\t(0,90,\fscx118\fscy118)\t(90,180,\fscx112\fscy112)}"
                        + txt + r"{\c" + primary + r"\fscx100\fscy100}"
                    )
                else:
                    parts.append(txt)
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Caption,,0,0,0,,{' '.join(parts)}")

    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return out_path
