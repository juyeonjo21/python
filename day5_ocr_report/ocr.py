"""이미지 → AI 비전 호출 → 마커 JSON 결과.

단위 변환·계산·판정은 하지 않는다 (judge.py 담당).
"""
import base64
import json
import mimetypes

from openai import OpenAI

KEYS = ["file", "marker_freq", "freq_unit", "marker_power", "power_unit", "readable", "note"]

FREQ_UNITS = {"hz": "Hz", "khz": "kHz", "mhz": "MHz", "ghz": "GHz"}
POWER_UNITS = {"pW", "nW", "µW", "mW", "W"}

PROMPT = """You are reading a screenshot of a spectrum analyzer.
Read ONLY the marker readout in the top-right of the plot area: the green text "Mkr1 <frequency> <unit>"
and the line directly below it "<power> <unit>".
Ignore every other number on the screen (Ref level, Center/Start/Stop Freq, Span, RBW, VBW, axis labels, side panel).

Return a JSON object with exactly these keys:
{"marker_freq": number or null, "freq_unit": string or null,
 "marker_power": number or null, "power_unit": string or null,
 "readable": true or false, "note": string}

Rules:
- Copy the numbers and units exactly as shown. Do not convert units. Do not round.
- If a value is hidden, covered, cut off, or not clearly legible, set that value and its unit to null.
  Never guess.
- readable is true only when all four values were read clearly.
- note: empty string if everything was read; otherwise a short Korean reason (e.g. "전력 값이 가려짐").
"""


def _to_float(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _norm_freq_unit(unit):
    if not isinstance(unit, str):
        return None
    return FREQ_UNITS.get(unit.strip().lower())


def _norm_power_unit(unit):
    if not isinstance(unit, str):
        return None
    unit = unit.strip()
    # uW, μW(그리스 문자 mu) → µW(micro sign)
    if unit[:1] in ("u", "μ"):
        unit = "µ" + unit[1:]
    return unit if unit in POWER_UNITS else None


def normalize_result(raw, filename):
    """AI 응답(dict)을 PRD의 7개 키로 맞춘다. 읽지 못한 값은 None."""
    if not isinstance(raw, dict):
        raw = {}
    result = {
        "file": filename,
        "marker_freq": _to_float(raw.get("marker_freq")),
        "freq_unit": _norm_freq_unit(raw.get("freq_unit")),
        "marker_power": _to_float(raw.get("marker_power")),
        "power_unit": _norm_power_unit(raw.get("power_unit")),
        "note": str(raw.get("note") or "").strip(),
    }
    all_read = all(result[k] is not None for k in ("marker_freq", "freq_unit", "marker_power", "power_unit"))
    result["readable"] = bool(raw.get("readable")) and all_read
    if not result["readable"] and not result["note"]:
        result["note"] = "값을 읽지 못함"
    return {k: result[k] for k in KEYS}


def _failure(filename, reason):
    return {
        "file": filename,
        "marker_freq": None,
        "freq_unit": None,
        "marker_power": None,
        "power_unit": None,
        "readable": False,
        "note": f"추출 실패: {reason}",
    }


def extract_marker(image_bytes, filename, api_key, model, client=None):
    """이미지 한 장에서 마커 값을 읽는다. 실패해도 예외를 던지지 않고 '추출 실패' 결과를 돌려준다."""
    try:
        client = client or OpenAI(api_key=api_key)
        mime = mimetypes.guess_type(filename)[0] or "image/png"
        data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        )
        raw = json.loads(response.choices[0].message.content)
        return normalize_result(raw, filename)
    except Exception as e:
        # 예외 메시지에 키 등 민감정보가 섞일 수 있어 예외 종류만 남긴다
        return _failure(filename, type(e).__name__)
