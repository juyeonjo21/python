import csv
import io

from docx import Document

import judge
import report

INFO = {"doc_no": "HCT-2026-001", "test_date": "2026-11-03", "test_name": "방사성 방출 (RE)",
        "sample_name": "시료A", "tester": "홍길동", "reviewer": "김검토"}


def make_rows(n=20):
    rows = [{"file": f"img_{i:02d}.png", "marker_freq": 2.405095, "freq_unit": "GHz",
             "marker_power": 100.0, "power_unit": "µW", "readable": True, "note": ""}
            for i in range(1, n + 1)]
    rows[16].update(marker_power=0.64183, power_unit="mW")
    rows[17].update(marker_power=1.0, power_unit="mW")                       # FAIL (마진)
    rows[18].update(marker_power=None, power_unit=None, note="전력 값이 가려짐")  # 확인필요
    rows[19].update(marker_freq=float("nan"), freq_unit=None)                 # 확인필요 (NaN)
    return rows


def build(rows=None):
    rows = rows or make_rows()
    judged = judge.judge_all(rows)
    summary = judge.summarize(judged)
    notes = {r["file"]: r["note"] for r in rows}
    data = report.build_report(INFO, judged, summary, cf=-51.5, limit=54.0, notes=notes)
    return Document(io.BytesIO(data)), judged


def all_text(doc):
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts += [c.text for c in row.cells]
    return "\n".join(parts)


def result_table(doc):
    return next(t for t in doc.tables if t.rows[0].cells[0].text == "No.")


def test_no_placeholder_left():
    doc, _ = build()
    assert "{{" not in all_text(doc)


def test_result_table_has_one_row_per_result():
    doc, _ = build()
    rows = result_table(doc).rows[1:]
    assert len(rows) == 20
    assert [r.cells[0].text for r in rows] == [str(i) for i in range(1, 21)]


def test_row_values():
    doc, _ = build()
    rows = result_table(doc).rows
    assert [c.text for c in rows[1].cells] == ["1", "2405.095", "100", "-10.00", "45.50", "54.0", "8.50", "PASS"]
    assert rows[17].cells[2].text == "641.83"          # 0.64183 mW → 641.83 µW
    assert rows[19].cells[2].text == "-"               # 전력 없음
    assert rows[19].cells[7].text == "확인필요"


def test_header_and_summary_fields():
    doc, _ = build()
    text = all_text(doc)
    for value in ["HCT-2026-001", "2026-11-03", "시료A", "홍길동", "김검토",
                  report.DEFAULT_STANDARD, "-51.5 dB (가정치)", "부적합/확인필요"]:
        assert value in text
    summary_table = next(t for t in doc.tables if t.rows[0].cells[0].text == "총 측정 건수")
    assert [c.text for c in summary_table.rows[1].cells] == ["20", "17", "1", "부적합/확인필요"]


def test_row_formatting_kept():
    template = Document(report.TEMPLATE_PATH)
    tpl_run = result_table(template).rows[1].cells[1].paragraphs[0].runs[-1]
    doc, _ = build()
    for row in result_table(doc).rows[1:]:
        run = row.cells[1].paragraphs[0].runs[-1]
        assert run._r.rPr.xml == tpl_run._r.rPr.xml
        assert row.cells[1]._tc.tcPr.xml == result_table(template).rows[1].cells[1]._tc.tcPr.xml


def test_remarks_list_fail_and_check():
    doc, judged = build()
    remarks = all_text(doc)
    assert "No.18 img_18.png: FAIL" in remarks
    assert "No.19 img_19.png: 확인필요" in remarks
    assert "판독 비고: 전력 값이 가려짐" in remarks
    assert "No.20 img_20.png: 확인필요" in remarks
    assert "nan" not in remarks
    assert "img_01.png" not in report.build_remarks(judged)


def test_remarks_all_pass():
    judged = judge.judge_all(make_rows()[:3])
    assert report.build_remarks(judged) == "특이사항 없음"


def test_report_filename():
    assert report.report_filename("HCT-2026-001") == "HCT-2026-001_RE보고서.docx"
    assert report.report_filename("A/B 1") == "A_B_1_RE보고서.docx"


def test_results_csv():
    rows = make_rows()
    judged = judge.judge_all(rows)
    data = report.results_csv(rows, judged, 54.0)
    assert data.startswith("﻿".encode())
    records = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    assert len(records) == 20
    assert float(records[16]["전력(µW)"]) == 641.83
    assert records[18]["판정"] == "확인필요"
