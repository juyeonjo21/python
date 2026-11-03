"""DOCX 양식 채우기.

- 치환자 양식({{key}}, {{r.key}} 행 반복): report_template.docx 형태
- 라벨 양식(빈 칸/빈 'o' 항목/XX%·x분 등 자리표시): 구현 결과물·성능평가·최종 보고서 형태

양식에 없는 항목은 만들지 않고, 양식에 이미 있는 빈 자리만 채운다.
"""
import copy
import re

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

PH = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


# ---------------------------------------------------------------- 공통 유틸
def replace_in_paragraph(p, old, new):
    """run이 쪼개져 있어도 서식(첫 run 기준)을 유지하며 문자열을 치환."""
    while True:
        runs = p.runs
        full = "".join(r.text for r in runs)
        idx = full.find(old)
        if idx < 0 or not runs:
            return
        pos, start_run = 0, None
        for i, r in enumerate(runs):
            if start_run is None and pos + len(r.text) > idx:
                start_run, offset = i, idx - pos
            pos += len(r.text)
        remaining = len(old)
        i = start_run
        first = True
        while remaining > 0 and i < len(runs):
            t = runs[i].text
            o = offset if first else 0
            take = min(len(t) - o, remaining)
            runs[i].text = t[:o] + (new if first else "") + t[o + take:]
            remaining -= take
            first = False
            i += 1


def _template_rpr(p):
    """새 run에 쓸 서식: 마지막 run의 rPr → 단락 기호 rPr 순으로 차용."""
    if p.runs and p.runs[-1]._r.rPr is not None:
        return copy.deepcopy(p.runs[-1]._r.rPr)
    ppr = p._p.pPr
    if ppr is not None and ppr.find(qn("w:rPr")) is not None:
        rpr = copy.deepcopy(ppr.find(qn("w:rPr")))
        rpr.tag = qn("w:rPr")
        return rpr
    return None


def append_text(p, text, bold=None, size=None, font=None):
    rpr = _template_rpr(p)
    run = p.add_run(text)
    if rpr is not None:
        if run._r.rPr is not None:
            run._r.remove(run._r.rPr)
        run._r.insert(0, rpr)
    if bold is not None:
        run.bold = bold
    if size is not None:
        run.font.size = Pt(size)
    if font:
        run.font.name = font
        rfonts = run._r.rPr.find(qn("w:rFonts"))
        for k in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
            rfonts.set(qn(k), font)
    return run


def set_cell_lines(cell, lines, align=None, **kw):
    """빈 셀에 여러 줄 텍스트를 첫 단락 서식을 복제해 넣는다."""
    base = cell.paragraphs[0]
    prev = base
    for i, line in enumerate(lines):
        if i == 0:
            p = base
        else:
            new = copy.deepcopy(base._p)
            for r in new.findall(qn("w:r")):
                new.remove(r)
            prev._p.addnext(new)
            p = Paragraph(new, cell)
        if align is not None:
            p.alignment = align
        append_text(p, line, **kw)
        prev = p


def iter_block(doc):
    """본문 단락/표를 문서 순서대로."""
    for el in doc.element.body.iterchildren():
        if el.tag == qn("w:p"):
            yield Paragraph(el, doc)
        elif el.tag == qn("w:tbl"):
            yield Table(el, doc)


def row_cells(row):
    """병합 셀 중복 없이 실제 tc만."""
    return [_Cell(tc, row) for tc in row._tr.findall(qn("w:tc"))]


def all_paragraphs(doc):
    yield from doc.paragraphs
    for t in doc.tables:
        for row in t.rows:
            for c in row_cells(row):
                yield from c.paragraphs


def has_placeholders(doc):
    return any(PH.search(p.text) for p in all_paragraphs(doc))


# ---------------------------------------------------------------- 치환자 양식
def fill_placeholder_doc(doc, values, rows):
    """{{key}}는 values, {{r.key}}가 있는 표 행은 rows 수만큼 복제."""
    for t in doc.tables:
        for row in list(t.rows):
            text = "".join(c.text for c in row_cells(row))
            if "{{r." not in text:
                continue
            tr = row._tr
            anchor = tr
            for r in rows:
                new_tr = copy.deepcopy(tr)
                anchor.addnext(new_tr)
                anchor = new_tr
                for tc in new_tr.findall(qn("w:tc")):
                    for p in _Cell(tc, row).paragraphs:
                        for key in PH.findall(p.text):
                            if key.startswith("r."):
                                replace_in_paragraph(p, "{{" + key + "}}", str(r.get(key[2:], "")))
            tr.getparent().remove(tr)
    for p in all_paragraphs(doc):
        for key in PH.findall(p.text):
            if key in values:
                replace_in_paragraph(p, "{{" + key + "}}", str(values[key]))


# ---------------------------------------------------------------- 라벨 양식
TOPICS = [("extract", "Raw Data"), ("judge", "pass/fail"), ("report", "성적서"),
          ("improve", "향후 개선"), ("summary", "종합 정리"), ("issue", "미해결"), ("plan", "향후 계획")]


def topic_of(text):
    return next((k for k, kw in TOPICS if kw in text), None)


def _is_blank_o(text):
    return re.fullmatch(r"\s*o\s*", text) is not None


def fill_label_doc(doc, ctx):
    """ctx: labels, sections, metrics, images, code, desc, summary, eval, issue, plan"""
    topic = None
    for block in iter_block(doc):
        if isinstance(block, Paragraph):
            t = block.text
            if t.strip() and not t.strip().startswith("o"):
                topic = topic_of(t) or topic
                if re.match(r"\s*\d+\.", t) and not topic_of(t):
                    topic = None
                continue
            # 'o 문제 상황:' 처럼 콜론 뒤가 비어 있으면 채움
            m = re.fullmatch(r"\s*o\s*(문제 상황|수행 과정|수행 결과)\s*:\s*", t)
            if m and topic in ctx["sections"]:
                append_text(block, " " + ctx["sections"][topic][m.group(1)])
            elif re.fullmatch(r"\s*o\s*종합 평가\s*:\s*", t):
                append_text(block, " " + ctx["eval"])
            elif "(전체 수행 결과 요약 및 특이사항 서술)" in t:
                replace_in_paragraph(block, "(전체 수행 결과 요약 및 특이사항 서술)", ctx["summary"])
            elif _is_blank_o(t) and topic in ctx["cases"]:
                append_text(block, ctx["cases"][topic])
            continue

        # ---- 표
        rows = block.rows
        cells_text = [[c.text.strip() for c in row_cells(r)] for r in rows]

        # 1) 라벨 | 빈칸
        for r, texts in zip(rows, cells_text):
            cells = row_cells(r)
            for i, lab in enumerate(texts[:-1]):
                if lab in ctx["labels"] and texts[i + 1] == "":
                    set_cell_lines(cells[i + 1], [ctx["labels"][lab]])

        # 2) 성능 표: 행 첫 칸으로 항목 판별 후 자리표시 치환
        for r, texts in zip(rows, cells_text):
            tp = topic_of(texts[0]) if texts else None
            if tp not in ctx["metrics"]:
                continue
            mt = ctx["metrics"][tp]
            for c in row_cells(r):
                for p in c.paragraphs:
                    replace_in_paragraph(p, "XX%", f"{mt['value']}%")
                    if re.search(r"(?<![가-힣A-Za-z])X건", p.text):
                        replace_in_paragraph(p, "X건", f"{mt['n']}건")
                    if "현재 x분" in p.text:
                        replace_in_paragraph(p, "현재 x분", f"현재 {mt['after_min']}분")
                    if "달성 / 미달성" in p.text:
                        replace_in_paragraph(p, "달성 / 미달성", "달성" if mt["achieved"] else "미달성")

        # 3) <소스코드>/<구현사진> 다음 빈 행, '• 설명 :'
        flat = [(r, row_cells(r)) for r in rows]
        mode, used = None, 0
        for r, cells in flat:
            txt = "".join(c.text for c in cells).strip()
            if txt in ("<소스코드>", "<구현사진>"):
                mode = txt
                continue
            if txt == "" and mode == "<소스코드>" and topic in ctx["code"]:
                set_cell_lines(cells[0], ctx["code"][topic].splitlines(), align=0, size=7.5, font="Consolas")
            elif txt == "" and mode == "<구현사진>":
                imgs = ctx["images"].get(topic) or ctx["images"].get("default", [])
                if used < len(imgs):
                    p = cells[0].paragraphs[0]
                    p.alignment = 1
                    p.add_run().add_picture(imgs[used], width=Cm(ctx.get("image_width_cm", 12)))
                    used += 1
            elif re.fullmatch(r"•\s*설명\s*:", txt) and topic in ctx["desc"]:
                append_text(cells[0].paragraphs[-1], ctx["desc"][topic])
            elif txt:
                mode = None

        # 4) 빈 단일 칸 표(미해결 이슈/향후 계획)
        if len(rows) == 1 and len(row_cells(rows[0])) == 1 and cells_text[0][0] == "" and topic in ("issue", "plan"):
            set_cell_lines(row_cells(rows[0])[0], ctx[topic])


def fill(template_path, out_path, values, rows, ctx):
    doc = Document(template_path)
    if has_placeholders(doc):
        fill_placeholder_doc(doc, values, rows)
        kind = "placeholder"
    else:
        fill_label_doc(doc, ctx)
        kind = "label"
    doc.save(out_path)
    return kind
