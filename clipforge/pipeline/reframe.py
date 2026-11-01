"""Reenquadramento 16:9 -> 9:16 seguindo o rosto de quem fala.

Amostra frames do trecho, detecta rostos (OpenCV), suaviza a posição e agrupa
em "planos" estáveis. Cada plano vira uma posição fixa de câmera; a troca entre
planos é um corte seco (como faria um editor humano), sem tremedeira.
"""
from __future__ import annotations

import statistics

import cv2

_cascade = None


def _detector():
    global _cascade
    if _cascade is None:
        _cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    return _cascade


def analyze(video_path: str, start: float, end: float, sample_fps: float = 3.0) -> dict:
    """Retorna {src_w, src_h, faces_ratio, shots:[(t0, t1, center_x_px)]}.

    Os tempos dos planos são relativos ao início do corte.
    """
    cap = cv2.VideoCapture(video_path)
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    det = _detector()

    samples: list[tuple[float, float | None]] = []
    t = start
    step = 1.0 / sample_fps
    scale = 480 / max(src_w, 1)
    while t < end:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        small = cv2.resize(frame, (0, 0), fx=scale, fy=scale)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        faces = det.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(int(30 * scale * 2), int(30 * scale * 2)))
        cx = None
        if len(faces):
            # Maior rosto = quem está em destaque
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            cx = (x + w / 2) / scale
        samples.append((t - start, cx))
        t += step
    cap.release()

    found = [c for _, c in samples if c is not None]
    faces_ratio = len(found) / len(samples) if samples else 0.0
    duration = end - start
    if not found:
        return {"src_w": src_w, "src_h": src_h, "faces_ratio": 0.0, "shots": [(0.0, duration, src_w / 2)]}

    # Preenche lacunas com o último valor conhecido
    filled, last = [], found[0]
    for ts, c in samples:
        last = c if c is not None else last
        filled.append((ts, last))

    # Mediana móvel para remover ruído do detector
    win = max(1, int(sample_fps))
    smooth = []
    for i, (ts, _) in enumerate(filled):
        vals = [c for _, c in filled[max(0, i - win): i + win + 1]]
        smooth.append((ts, statistics.median(vals)))

    # Agrupa em planos: novo plano quando o centro muda mais que 12% da largura
    # e permanece assim por pelo menos ~1s.
    crop_w = src_h * 9 / 16
    threshold = max(src_w * 0.12, crop_w * 0.25)
    shots: list[list] = []
    cur_start, cur_vals = 0.0, [smooth[0][1]]
    pending: list[tuple[float, float]] = []
    for ts, c in smooth[1:]:
        ref = statistics.median(cur_vals)
        if abs(c - ref) > threshold:
            pending.append((ts, c))
            if pending[-1][0] - pending[0][0] >= 1.0:
                shots.append([cur_start, pending[0][0], ref])
                cur_start, cur_vals, pending = pending[0][0], [p[1] for p in pending], []
        else:
            cur_vals.extend(p[1] for p in pending)
            pending = []
            cur_vals.append(c)
    shots.append([cur_start, duration, statistics.median(cur_vals + [p[1] for p in pending])])

    return {"src_w": src_w, "src_h": src_h, "faces_ratio": faces_ratio, "shots": [tuple(s) for s in shots]}


def crop_x_expression(shots: list[tuple], src_w: int, crop_w: int) -> str:
    """Expressão ffmpeg para o x do filtro crop, por plano."""

    def clamp(cx: float) -> int:
        return int(max(0, min(src_w - crop_w, cx - crop_w / 2)))

    expr = str(clamp(shots[-1][2]))
    for t0, t1, cx in reversed(shots[:-1]):
        expr = f"if(lt(t\\,{t1:.3f})\\,{clamp(cx)}\\,{expr})"
    return expr
