"""스펙트럼 분석기 화면 이미지에서 마커 주파수/전력 값을 추출한다.

1차: macOS Vision 프레임워크 OCR(pyobjc)로 텍스트 인식
2차: 마커 표시값이 가려진 경우(회색 빗금 박스) 그래프의 마커 위치로 값을 추정
"""
import json
import math
import re
from pathlib import Path

import Quartz
import Vision
from Foundation import NSURL
from PIL import Image

UNIT_TO_UW = {"pW": 1e-6, "nW": 1e-3, "uW": 1.0, "mW": 1e3, "W": 1e6}
UNIT_TO_MHZ = {"Hz": 1e-6, "kHz": 1e-3, "MHz": 1.0, "GHz": 1e3}


def run_ocr(path):
    """이미지의 텍스트 줄과 위치(정규화 좌표, 원점 좌상단)를 돌려준다."""
    url = NSURL.fileURLWithPath_(str(Path(path).resolve()))
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if src is None:
        raise ValueError("이미지를 열 수 없습니다")
    cg = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)

    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(False)
    req.setRecognitionLanguages_(["en-US", "ko-KR"])
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg, None)
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"OCR 실패: {err}")

    lines = []
    for obs in req.results() or []:
        cand = obs.topCandidates_(1)
        if not cand:
            continue
        b = obs.boundingBox()  # 원점 좌하단 → 좌상단으로 변환
        lines.append({
            "text": str(cand[0].string()), "conf": float(cand[0].confidence()),
            "x": b.origin.x, "y": 1.0 - (b.origin.y + b.size.height), "w": b.size.width, "h": b.size.height,
        })
    return {"width": Quartz.CGImageGetWidth(cg), "height": Quartz.CGImageGetHeight(cg), "lines": lines}


def _norm(text):
    # OCR 오인식 보정: µ→u, HZ→Hz, KHz→kHz, 'UW'→'uW'
    t = text.replace("µ", "u").replace("μ", "u")
    t = re.sub(r"(?i)([kmg]?)hz\b", lambda m: {"": "Hz", "k": "kHz", "m": "MHz", "g": "GHz"}[m.group(1).lower()], t)
    t = re.sub(r"(?<=\d)\s*UW\b", " uW", t)
    t = re.sub(r"(?<=\d)\s*(p|n|u|m)?W\b", lambda m: " " + (m.group(1) or "") + "W", t)
    return t


def _parse_freq(text):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(GHz|MHz|kHz|Hz)", _norm(text))
    return (float(m.group(1)) * UNIT_TO_MHZ[m.group(2)], m.group(0)) if m else (None, None)


def _parse_power(text):
    m = re.search(r"(\d*\.?\d+)\s*(pW|nW|uW|mW|W)\b", _norm(text))
    return (float(m.group(1)) * UNIT_TO_UW[m.group(2)], m.group(0)) if m else (None, None)


def _is_gray(p):
    r, g, b = p[:3]
    return abs(r - g) < 12 and abs(g - b) < 12 and 70 < r < 210


def _occluded(px, box):
    """영역 안에 회색 빗금(가림 박스) 픽셀이 일정량 이상이면 가려진 것으로 본다."""
    x0, y0, x1, y1 = box
    cnt = sum(1 for y in range(y0, y1, 2) for x in range(x0, x1, 2) if _is_gray(px[x, y]))
    return cnt > 300


def _plot_frame(px, w, h):
    """그래프 테두리(밝은 회색 선, 두께 수 px)의 중심 좌표를 찾는다."""
    my = int(h * 0.5)
    mx = int(w * 0.4)
    border = lambda p: all(160 < c < 205 for c in p[:3]) and abs(p[0] - p[2]) < 20

    def center(coords, get):
        first = next(c for c in coords if border(get(c)))
        step = 1 if coords[1] > coords[0] else -1
        last = first
        while border(get(last + step)):
            last += step
        return (first + last) / 2

    left = center(range(int(w * 0.03), int(w * 0.2)), lambda x: px[x, my])
    right = center(range(int(w * 0.86), int(w * 0.6), -1), lambda x: px[x, my])
    top = center(range(int(h * 0.17), int(h * 0.4)), lambda y: px[mx, y])
    bottom = center(range(int(h * 0.92), int(h * 0.6), -1), lambda y: px[mx, y])
    return left, right, top, bottom


def _estimate_from_graph(img, start_mhz, stop_mhz, ref_uw, db_div):
    """그래프 상의 마커(초록 마름모) x위치와 트레이스(노란선) y위치로 주파수·전력을 추정."""
    px = img.load()
    w, h = img.size
    left, right, top, bottom = _plot_frame(px, w, h)
    green = [(x, y) for y in range(int(top) + 3, int(bottom) - 2) for x in range(int(left) + 3, int(right) - 2)
             if (lambda p: p[1] > 180 and p[0] < 120 and p[2] < 120)(px[x, y])]
    if not green:
        return None, None
    mx = round(sum(p[0] for p in green) / len(green))
    freq = start_mhz + (mx - left) / (right - left) * (stop_mhz - start_mhz)
    trace = [y for y in range(int(top) + 3, int(bottom) - 2)
             if (lambda p: p[0] > 170 and p[1] > 170 and p[2] < 110)(px[mx, y])]
    power = None
    if trace:
        ty = sum(trace) / len(trace)
        div_px = (bottom - top) / 10
        power = ref_uw * 10 ** (-(ty - top) / div_px * db_div / 10)
    return freq, power


def _refine_with_suffix(estimate, suffix_text, decimals):
    """가림 박스 오른쪽으로 보이는 끝자리(예: '95')에 맞춰 추정값을 보정."""
    digits = re.sub(r"\D", "", suffix_text or "")
    if len(digits) < 2 or estimate is None:
        return estimate
    n = len(digits)
    scale = 10 ** decimals
    base = round(estimate * scale)
    mod = 10 ** n
    target = int(digits[-n:])
    cand = [(base // mod + k) * mod + target for k in (-1, 0, 1)]
    best = min(cand, key=lambda c: abs(c - base))
    if abs(best - base) > mod * 0.6:
        return estimate
    return best / scale


def extract(path):
    """이미지 1장 → 측정값 dict. notes에 추정/보정 사유를 남긴다."""
    data = run_ocr(path)
    W, H = data["width"], data["height"]
    lines = data["lines"]
    img = Image.open(path).convert("RGB")
    px = img.load()

    def find(pred):
        return next((l for l in lines if pred(l)), None)

    def text_at(label):
        lab = find(lambda l: l["text"].strip().lower().startswith(label.lower()) and l["x"] > 0.8)
        if not lab:
            return None
        below = [l for l in lines if l["x"] > 0.8 and 0 < l["y"] - lab["y"] < 0.09]
        return min(below, key=lambda l: l["y"])["text"] if below else None

    res = {"file": Path(path).name, "notes": []}

    sample = find(lambda l: "SAMPLE" in l["text"].upper())
    m = re.search(r"SAMPLE\s*(\d+)", sample["text"].upper()) if sample else None
    res["sample"] = m.group(1) if m else ""

    start = _parse_freq(text_at("Start Freq") or "")[0]
    stop = _parse_freq(text_at("Stop Freq") or "")[0]
    center = _parse_freq(text_at("Center Freq") or "")[0]
    ref_line = find(lambda l: l["text"].strip().startswith("Ref"))
    ref_uw = _parse_power(ref_line["text"])[0] if ref_line else None
    div_line = find(lambda l: "dB/div" in l["text"])
    db_div = float(re.search(r"(\d+(?:\.\d+)?)", div_line["text"]).group(1)) if div_line else 10.0
    res.update(start_mhz=start, stop_mhz=stop, center_mhz=center)

    # 마커 판독 영역: 오른쪽 위(그래프 위, 소프트키 왼쪽)
    readout = [l for l in lines if l["y"] < 0.19 and 0.45 < l["x"] < 0.84 and l["y"] > 0.08]
    freq_lines = [l for l in readout if l["y"] < 0.135]
    pow_lines = [l for l in readout if l["y"] >= 0.135]
    freq_txt = " ".join(l["text"] for l in sorted(freq_lines, key=lambda l: l["x"]))
    pow_txt = " ".join(l["text"] for l in sorted(pow_lines, key=lambda l: l["x"]))

    x0, x1 = int(W * 0.55), int(W * 0.83)
    freq_hidden = _occluded(px, (x0, int(H * 0.10), x1, int(H * 0.137)))
    pow_hidden = _occluded(px, (x0, int(H * 0.139), x1, int(H * 0.176)))

    freq, freq_raw = _parse_freq(freq_txt.replace("Mkr1", ""))
    power, pow_raw = _parse_power(pow_txt)
    res["ocr_freq"] = freq_raw or ""
    res["ocr_power"] = pow_raw or ""
    res["freq_source"] = res["power_source"] = "ocr"

    if (freq_hidden or freq is None or power is None or pow_hidden) and None not in (start, stop, ref_uw):
        est_f, est_p = _estimate_from_graph(img, start, stop, ref_uw, db_div)
        if freq_hidden or freq is None:
            freq = _refine_with_suffix(est_f / 1000, freq_raw, 6) * 1000 if est_f else None
            res["freq_source"] = "graph"
            res["notes"].append(f"마커 주파수 표시가 가려져 그래프 마커 위치로 추정 (판독된 일부: '{freq_raw or '-'}')")
        if pow_hidden or power is None:
            power = round(est_p, 2) if est_p else None
            res["power_source"] = "graph"
            res["notes"].append(f"마커 전력 표시가 가려져 트레이스 높이로 추정 (판독된 일부: '{pow_raw or '-'}')")

    res["freq_mhz"] = round(freq, 6) if freq is not None else None
    res["power_uw"] = round(power, 4) if power is not None else None
    if res["freq_mhz"] is None or res["power_uw"] is None:
        res["notes"].append("값을 판독하지 못함 — 수동 입력 필요")
    return res


def power_to_dbm(power_uw):
    return 10 * math.log10(power_uw / 1000)


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        print(json.dumps(extract(p), ensure_ascii=False))
