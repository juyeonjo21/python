"""측정값 환산 및 PASS/FAIL 판정 (report_template.docx 각주의 산식 그대로)."""
import math

# FCC Part 15 Subpart B Class B, 3 m (dBµV/m)
FCC_CLASS_B_3M = [(30, 88, 40.0), (88, 216, 43.5), (216, 960, 46.0), (960, float("inf"), 54.0)]


def fcc_limit(freq_mhz):
    for lo, hi, lim in FCC_CLASS_B_3M:
        if lo <= freq_mhz < hi:
            return lim
    return None


def judge(rows, cf_db):
    """rows: [{freq_mhz, power_uw, ...}] → 판정 컬럼이 추가된 rows와 요약."""
    out = []
    for i, r in enumerate(rows, 1):
        f, p = r.get("freq_mhz"), r.get("power_uw")
        row = dict(r, no=i)
        if f is None or p is None or p <= 0:
            row.update(dbm=None, dbuv_m=None, limit=None, margin=None, verdict="판정불가")
        else:
            dbm = 10 * math.log10(p / 1000)
            dbuv = dbm + 107 + cf_db
            lim = fcc_limit(f)
            margin = None if lim is None else lim - dbuv
            row.update(dbm=dbm, dbuv_m=dbuv, limit=lim, margin=margin,
                       verdict="판정불가" if margin is None else ("PASS" if margin >= 0 else "FAIL"))
        out.append(row)
    pass_cnt = sum(r["verdict"] == "PASS" for r in out)
    fail_cnt = sum(r["verdict"] == "FAIL" for r in out)
    summary = {
        "total": len(out),
        "pass_cnt": pass_cnt,
        "fail_cnt": fail_cnt,
        "verdict": "FAIL" if fail_cnt else ("PASS" if pass_cnt == len(out) and out else "보류"),
    }
    return out, summary


def fmt_row(r):
    """보고서 표에 들어갈 문자열 형태."""
    f = lambda v, d: "-" if v is None else f"{v:.{d}f}"
    return {
        "no": str(r["no"]),
        "freq_mhz": f(r.get("freq_mhz"), 3),
        "power_uw": f(r.get("power_uw"), 2),
        "dbm": f(r.get("dbm"), 2),
        "dbuv_m": f(r.get("dbuv_m"), 2),
        "limit": f(r.get("limit"), 1),
        "margin": f(r.get("margin"), 2),
        "verdict": r["verdict"],
    }
