import json
from types import SimpleNamespace

from ocr import KEYS, extract_marker, normalize_result


def fake_client(content=None, error=None):
    def create(**kwargs):
        if error:
            raise error
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_normal_result_has_all_keys():
    raw = {"marker_freq": 2.405095, "freq_unit": "GHz", "marker_power": 641.83,
           "power_unit": "µW", "readable": True, "note": ""}
    result = normalize_result(raw, "img_01.png")
    assert list(result) == KEYS
    assert result["file"] == "img_01.png"
    assert result["marker_freq"] == 2.405095
    assert result["marker_power"] == 641.83
    assert result["readable"] is True


def test_hidden_power_stays_none():
    raw = {"marker_freq": 2.405095, "freq_unit": "GHz", "marker_power": None,
           "power_unit": None, "readable": False, "note": "전력 값이 가려짐"}
    result = normalize_result(raw, "img_19.png")
    assert result["marker_power"] is None
    assert result["readable"] is False
    assert result["note"] == "전력 값이 가려짐"


def test_non_numeric_value_becomes_none():
    raw = {"marker_freq": "2.40?095", "freq_unit": "GHz", "marker_power": "641.83",
           "power_unit": "µW", "readable": True, "note": ""}
    result = normalize_result(raw, "x.png")
    assert result["marker_freq"] is None
    assert result["marker_power"] == 641.83
    assert result["readable"] is False
    assert result["note"]


def test_unit_spelling_is_normalized():
    for spelling in ("uW", "μW", "µW"):
        assert normalize_result({"power_unit": spelling}, "x.png")["power_unit"] == "µW"
    assert normalize_result({"power_unit": "mW"}, "x.png")["power_unit"] == "mW"
    assert normalize_result({"freq_unit": "ghz"}, "x.png")["freq_unit"] == "GHz"
    assert normalize_result({"power_unit": "dBm"}, "x.png")["power_unit"] is None


def test_mw_value_is_not_converted():
    raw = {"marker_freq": 2.405095, "freq_unit": "GHz", "marker_power": 0.64183,
           "power_unit": "mW", "readable": True, "note": ""}
    result = normalize_result(raw, "img_17.png")
    assert result["marker_power"] == 0.64183
    assert result["power_unit"] == "mW"


def test_extract_uses_client_response():
    content = json.dumps({"marker_freq": 2.405095, "freq_unit": "GHz", "marker_power": 641.83,
                          "power_unit": "µW", "readable": True, "note": ""})
    result = extract_marker(b"png", "img_01.png", "key", "model", client=fake_client(content))
    assert result["readable"] is True
    assert result["marker_power"] == 641.83


def test_api_error_returns_failure_without_raising():
    result = extract_marker(b"png", "img_05.png", "sk-secret", "model",
                            client=fake_client(error=RuntimeError("bad key sk-secret")))
    assert result["note"].startswith("추출 실패")
    assert "sk-secret" not in result["note"]
    assert result["readable"] is False
    assert result["marker_freq"] is None


def test_broken_json_returns_failure():
    result = extract_marker(b"png", "img_06.png", "key", "model", client=fake_client("not json"))
    assert result["note"].startswith("추출 실패")
