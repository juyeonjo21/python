"""단위 변환, dB 계산, PASS/FAIL 판정 (순수 계산, AI 사용 금지)."""
import math

DEFAULT_CF = -51.5           # dB
DEFAULT_LIMIT = 54.0         # dBµV/m
DEFAULT_FREQ_MIN = 2.4035    # GHz
DEFAULT_FREQ_MAX = 2.4060    # GHz

PASS = "PASS"
FAIL = "FAIL"
CHECK = "확인필요"

FREQ_TO_GHZ = {"Hz": 1e-9, "kHz": 1e-6, "MHz": 1e-3, "GHz": 1.0}
POWER_TO_UW = {"pW": 1e-6, "nW": 1e-3, "µW": 1.0, "mW": 1e3, "W": 1e6}


def _clean(value):
    """None·NaN·숫자가 아닌 값은 None, 그 외는 float."""
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else value


def _norm_power_unit(unit):
    if not isinstance(unit, str):
        return None
    unit = unit.strip()
    if unit[:1] in ("u", "μ"):
        unit = "µ" + unit[1:]
    return unit


def to_ghz(value, unit):
    """주파수를 GHz로. 값이나 단위를 알 수 없으면 None."""
    value = _clean(value)
    factor = FREQ_TO_GHZ.get(unit.strip() if isinstance(unit, str) else None)
    if value is None or factor is None:
        return None
    return round(value * factor, 9)  # 부동소수 오차 제거 (1 Hz 단위)


def to_uw(value, unit):
    """전력을 µW로. 값이나 단위를 알 수 없으면 None."""
    value = _clean(value)
    factor = POWER_TO_UW.get(_norm_power_unit(unit))
    if value is None or factor is None:
        return None
    return value * factor


def uw_to_dbm(uw):
    """dBm = 10·log10(µW / 1000). 0 이하 값은 계산 불가 → None."""
    if uw is None or uw <= 0:
        return None
    return 10 * math.log10(uw / 1000)


def measured_dbuv_m(dbm, cf):
    """측정값(dBµV/m) = dBm + 107 + CF."""
    if dbm is None:
        return None
    return dbm + 107 + cf


def margin_db(limit, measured):
    """마진 = Limit − 측정값."""
    if measured is None:
        return None
    return limit - measured


def judge_row(row, cf=DEFAULT_CF, limit=DEFAULT_LIMIT,
              freq_min=DEFAULT_FREQ_MIN, freq_max=DEFAULT_FREQ_MAX, use_freq=True):
    """결과 한 건을 판정한다. 반환: 계산값 + result(PASS/FAIL/확인필요) + reason."""
    freq_ghz = to_ghz(row.get("marker_freq"), row.get("freq_unit"))
    power_uw = to_uw(row.get("marker_power"), row.get("power_unit"))
    dbm = uw_to_dbm(power_uw)
    measured = measured_dbuv_m(dbm, cf)
    margin = margin_db(limit, measured)
    if margin is not None:
        margin = round(margin, 2)  # 보고서 표시 자릿수와 판정을 일치시킨다

    out = {
        "file": row.get("file"),
        "freq_ghz": freq_ghz,
        "power_uw": power_uw,
        "dbm": dbm,
        "measured": measured,
        "margin": margin,
    }

    missing = []
    if freq_ghz is None:
        missing.append("주파수")
    if power_uw is None:
        missing.append("전력")
    elif dbm is None:
        missing.append("전력(0 이하)")
    if missing:
        return {**out, "result": CHECK, "reason": f"{'·'.join(missing)} 값 확인 필요"}

    reasons = []
    if use_freq and not (freq_min <= freq_ghz <= freq_max):
        reasons.append(f"주파수 {freq_ghz:.6f} GHz가 허용 범위({freq_min}~{freq_max} GHz) 밖")
    if margin < 0:
        reasons.append(f"마진 {margin:.2f} dB (Limit 초과)")
    if reasons:
        return {**out, "result": FAIL, "reason": "; ".join(reasons)}
    return {**out, "result": PASS, "reason": ""}


def judge_all(rows, **criteria):
    return [judge_row(r, **criteria) for r in rows]


def summarize(judged):
    """총 건수, PASS, FAIL, 확인필요, 종합판정."""
    results = [j["result"] for j in judged]
    summary = {
        "total": len(results),
        "pass": results.count(PASS),
        "fail": results.count(FAIL),
        "check": results.count(CHECK),
    }
    summary["overall"] = "부적합/확인필요" if summary["fail"] or summary["check"] else "적합"
    return summary
