import math

import pytest

from judge import (
    CHECK, FAIL, PASS, judge_all, judge_row, margin_db, measured_dbuv_m,
    summarize, to_ghz, to_uw, uw_to_dbm,
)


def row(freq=2.405095, freq_unit="GHz", power=641.83, power_unit="µW", file="img.png"):
    return {"file": file, "marker_freq": freq, "freq_unit": freq_unit,
            "marker_power": power, "power_unit": power_unit}


# --- 단위 변환 ---

def test_mw_to_uw():
    assert to_uw(0.64183, "mW") == pytest.approx(641.83)


def test_nw_to_uw():
    assert to_uw(500, "nW") == pytest.approx(0.5)


def test_uw_variants():
    assert to_uw(10, "uW") == 10
    assert to_uw(10, "μW") == 10  # 그리스 문자 mu


def test_freq_to_ghz():
    assert to_ghz(2405.095, "MHz") == 2.405095
    assert to_ghz(2405095, "kHz") == 2.405095
    assert to_ghz(2.405095, "GHz") == 2.405095


def test_unknown_or_missing_is_none():
    assert to_uw(None, "µW") is None
    assert to_uw(float("nan"), "µW") is None
    assert to_uw(1.0, None) is None
    assert to_uw(1.0, "dBm") is None
    assert to_ghz(2.4, None) is None


# --- 계산 ---

def test_dbm():
    assert uw_to_dbm(1000) == pytest.approx(0.0)
    assert uw_to_dbm(1) == pytest.approx(-30.0)
    assert uw_to_dbm(0) is None


def test_measured_and_margin():
    dbm = uw_to_dbm(1000)              # 0 dBm
    measured = measured_dbuv_m(dbm, -51.5)
    assert measured == pytest.approx(55.5)
    assert margin_db(54.0, measured) == pytest.approx(-1.5)


# --- 판정 ---

def test_pass():
    # 641.83 µW → -1.926 dBm → 53.57 dBµV/m → 마진 0.43
    j = judge_row(row())
    assert j["result"] == PASS
    assert j["margin"] == pytest.approx(0.43)


def test_mw_row_same_as_uw_row():
    assert judge_row(row(power=0.64183, power_unit="mW"))["margin"] == judge_row(row())["margin"]


def test_fail_by_margin():
    j = judge_row(row(power=1000))
    assert j["result"] == FAIL
    assert "마진" in j["reason"]


def test_margin_zero_is_pass():
    # 측정값 = Limit 이 되도록 Limit 설정
    measured = measured_dbuv_m(uw_to_dbm(641.83), -51.5)
    assert judge_row(row(), limit=measured)["result"] == PASS


def test_freq_boundaries_inclusive():
    assert judge_row(row(freq=2.4035))["result"] == PASS
    assert judge_row(row(freq=2.4060))["result"] == PASS
    assert judge_row(row(freq=2403.5, freq_unit="MHz"))["result"] == PASS


def test_freq_out_of_range_fails():
    j = judge_row(row(freq=2.4061))
    assert j["result"] == FAIL
    assert "주파수" in j["reason"]
    assert judge_row(row(freq=2.4034))["result"] == FAIL


def test_freq_criterion_off():
    assert judge_row(row(freq=2.5), use_freq=False)["result"] == PASS


def test_missing_power_is_check():
    j = judge_row(row(power=None, power_unit=None))
    assert j["result"] == CHECK
    assert j["margin"] is None
    assert "전력" in j["reason"]


def test_missing_freq_is_check():
    j = judge_row(row(freq=float("nan"), freq_unit=None))
    assert j["result"] == CHECK
    assert "주파수" in j["reason"]


def test_custom_cf_and_limit():
    # CF를 1 dB 올리면 마진이 1 dB 줄어든다
    base = judge_row(row())["margin"]
    assert judge_row(row(), cf=-50.5)["margin"] == pytest.approx(base - 1)
    assert judge_row(row(), cf=-50.5)["result"] == FAIL
    assert judge_row(row(), cf=-50.5, limit=55.0)["result"] == PASS


# --- 요약 ---

def test_summary_counts_and_overall():
    judged = judge_all([row(), row(power=1000), row(power=None)])
    s = summarize(judged)
    assert (s["total"], s["pass"], s["fail"], s["check"]) == (3, 1, 1, 1)
    assert s["overall"] == "부적합/확인필요"


def test_summary_all_pass():
    s = summarize(judge_all([row(), row()]))
    assert s["overall"] == "적합"


def test_summary_check_only_is_not_ok():
    s = summarize(judge_all([row(), row(power=None)]))
    assert s["overall"] == "부적합/확인필요"
