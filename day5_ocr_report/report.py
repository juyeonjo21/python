"""docx 템플릿 채우기, 결과 CSV 만들기.

템플릿의 {{ }} 자리는 각각 한 run에 들어 있으므로 run 단위로 글자만 바꿔 서식을 유지한다.
"""
import copy
import io
import re
from datetime import datetime

import pandas as pd
from docx import Document

import judge

TEMPLATE_PATH = "docs/report_template.docx"
DEFAULT_STANDARD = "FCC Part 15 Subpart B Class B"
ROW_MARK = "{{r."
PLACEHOLDER = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def _fmt(value, spec):
    return "-" if value is None else format(value, spec)


def build_remarks(judged, notes=None):
    """FAIL·확인필요 항목과 사유. notes: {파일명: OCR 비고} (있으면 덧붙임)."""
    notes = notes or {}
    lines = []
    for no, j in enumerate(judged, start=1):
        if j["result"] == judge.PASS:
            continue
        line = f"No.{no} {j['file']}: {j['result']} — {j['reason']}"
        note = notes.get(j["file"])
        note = note.strip() if isinstance(note, str) else ""  # NaN 등은 무시
        if note:
            line += f" (판독 비고: {note})"
        lines.append(line)
    return "\n".join(lines) if lines else "특이사항 없음"


def table_rows(judged, limit):
    """측정 결과 표 한 줄씩의 {{r.*}} 값 (모두 문자열)."""
    rows = []
    for no, j in enumerate(judged, start=1):
        rows.append({
            "no": str(no),
            "freq_mhz": _fmt(None if j["freq_ghz"] is None else j["freq_ghz"] * 1000, ".3f"),
            "power_uw": _fmt(j["power_uw"], ".6g"),
            "dbm": _fmt(j["dbm"], ".2f"),
            "dbuv_m": _fmt(j["measured"], ".2f"),
            "limit": _fmt(limit, ".1f"),
            "margin": _fmt(j["margin"], ".2f"),
            "verdict": j["result"],
        })
    return rows


def _set_run_text(run, text):
    """줄바꿈은 Word 줄바꿈(<w:br/>)으로 넣는다."""
    parts = text.split("\n")
    run.text = parts[0]
    for part in parts[1:]:
        run.add_break()
        run.add_text(part)


def _fill_paragraph(paragraph, values, prefix=""):
    for run in paragraph.runs:
        if "{{" not in run.text:
            continue
        text = run.text
        def sub(m):
            key = m.group(1)
            if prefix:
                if not key.startswith(prefix):
                    return m.group(0)
                key = key[len(prefix):]
            return str(values.get(key, m.group(0)))
        new = PLACEHOLDER.sub(sub, text)
        if new != text:
            _set_run_text(run, new)


def _iter_paragraphs(container):
    for p in container.paragraphs:
        yield p
    for table in getattr(container, "tables", []):
        for row in table.rows:
            for cell in row.cells:
                yield from _iter_paragraphs(cell)


def _expand_row_table(doc, rows):
    """{{r.*}}가 있는 표 행을 결과 건수만큼 복제해 채운다."""
    for table in doc.tables:
        for tpl_row in table.rows:
            if ROW_MARK not in "".join(c.text for c in tpl_row.cells):
                continue
            tpl_tr = tpl_row._tr
            anchor = tpl_tr
            for values in rows:
                new_tr = copy.deepcopy(tpl_tr)
                anchor.addnext(new_tr)
                anchor = new_tr
            tpl_tr.getparent().remove(tpl_tr)
            # 복제된 행을 채운다 (table.rows는 매번 XML에서 다시 읽음)
            filled = [r for r in table.rows if ROW_MARK in "".join(c.text for c in r.cells)]
            for row, values in zip(filled, rows):
                for cell in row.cells:
                    for p in _iter_paragraphs(cell):
                        _fill_paragraph(p, values, prefix="r.")
            return


def build_report(info, judged, summary, cf, limit, notes=None, template_path=TEMPLATE_PATH):
    """보고서 docx를 bytes로 만든다.

    info: doc_no, test_date, test_name, sample_name, tester, reviewer, standard
    """
    doc = Document(template_path)
    _expand_row_table(doc, table_rows(judged, limit))

    values = {
        "doc_no": info.get("doc_no", ""),
        "test_date": info.get("test_date", ""),
        "test_name": info.get("test_name", ""),
        "sample_name": info.get("sample_name", ""),
        "tester": info.get("tester", ""),
        "reviewer": info.get("reviewer", ""),
        "standard": info.get("standard") or DEFAULT_STANDARD,
        "cf_db": f"{cf:.1f}",
        "total": str(summary["total"]),
        "pass_cnt": str(summary["pass"]),
        "fail_cnt": str(summary["fail"]),
        "verdict": summary["overall"],
        "remarks": build_remarks(judged, notes),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    containers = [doc]
    for section in doc.sections:
        containers += [section.header, section.footer]
    for container in containers:
        for p in _iter_paragraphs(container):
            _fill_paragraph(p, values)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def report_filename(doc_no):
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", str(doc_no).strip()) or "문서번호없음"
    return f"{safe}_RE보고서.docx"


def results_csv(rows, judged, limit):
    """추출값 + 판정 결과 CSV (엑셀에서 한글이 깨지지 않도록 utf-8-sig)."""
    records = []
    for no, (r, j) in enumerate(zip(rows, judged), start=1):
        records.append({
            "No.": no,
            "파일": j["file"],
            "마커 주파수": r.get("marker_freq"),
            "주파수 단위": r.get("freq_unit"),
            "마커 전력": r.get("marker_power"),
            "전력 단위": r.get("power_unit"),
            "주파수(GHz)": j["freq_ghz"],
            "전력(µW)": j["power_uw"],
            "전력(dBm)": None if j["dbm"] is None else round(j["dbm"], 2),
            "측정값(dBµV/m)": None if j["measured"] is None else round(j["measured"], 2),
            "Limit(dBµV/m)": limit,
            "마진(dB)": j["margin"],
            "판정": j["result"],
            "사유": j["reason"],
            "판독 비고": r.get("note"),
        })
    return pd.DataFrame(records).to_csv(index=False).encode("utf-8-sig")
