"""DOCX → PDF 변환 (reportlab, 외부 프로그램 불필요).

단락(정렬·크기·굵기·들여쓰기), 표(열 너비·병합·음영), 그림을 문서 순서대로 옮긴다.
Word와 완전히 같지는 않지만 양식 구조를 그대로 보존한다.
"""
import io
from xml.sax.saxutils import escape

from docx import Document
from docx.oxml.ns import qn
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT, FONT_B = "KR", "KR-B"
_registered = False


def _register_fonts():
    global _registered
    if _registered:
        return
    # 한글+기호(µ, − 등)를 모두 가진 TrueType 글꼴 우선
    candidates = [
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    ]
    for path in candidates:
        try:
            pdfmetrics.registerFont(TTFont(FONT, path))
            pdfmetrics.registerFont(TTFont(FONT_B, path))
            break
        except Exception:
            continue
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_B, italic=FONT, boldItalic=FONT_B)
    _registered = True


def _glyph_safe(text):
    """글꼴에 없는 글자는 모양이 같은 글자로 대체."""
    face = pdfmetrics.getFont(FONT).face
    return "".join(c if ord(c) in face.charToGlyph or c in "\n\t" else
                   {"µ": "μ", "−": "-", "✓": "v"}.get(c, c) for c in text)


ALIGN = {"center": TA_CENTER, "right": TA_RIGHT, "both": TA_JUSTIFY, "distribute": TA_JUSTIFY}


def _val(el, path, attr="w:val"):
    if el is None:
        return None
    x = el.find(path)
    return None if x is None else x.get(qn(attr))


class Renderer:
    def __init__(self, doc):
        self.doc = doc
        self.styles = {}
        st = doc.styles.element
        for s in st.findall(qn("w:style")):
            self.styles[s.get(qn("w:styleId"))] = s
        dflt = st.find(qn("w:docDefaults"))
        self.default_sz = 10.0
        if dflt is not None:
            sz = dflt.find(".//" + qn("w:sz"))
            if sz is not None:
                self.default_sz = int(sz.get(qn("w:val"))) / 2

    # ---- 서식 해석
    def _style_prop(self, style_id, tag):
        seen = set()
        while style_id and style_id not in seen:
            seen.add(style_id)
            s = self.styles.get(style_id)
            if s is None:
                return None
            for path in ("w:rPr/" + tag, "w:pPr/" + tag):
                x = s.find(qn(path.split("/")[0]) + "/" + qn(path.split("/")[1]))
                if x is not None:
                    return x
            bo = s.find(qn("w:basedOn"))
            style_id = bo.get(qn("w:val")) if bo is not None else None
        return None

    def _run_props(self, r, p):
        rpr = r.find(qn("w:rPr"))
        ppr = p.find(qn("w:pPr"))
        pstyle = _val(ppr, qn("w:pStyle"))
        rstyle = _val(rpr, qn("w:rStyle"))

        def lookup(tag):
            for src in (rpr,):
                if src is not None and src.find(qn(tag)) is not None:
                    return src.find(qn(tag))
            for sid in (rstyle, pstyle):
                x = self._style_prop(sid, tag)
                if x is not None:
                    return x
            return None

        sz = lookup("w:sz")
        size = int(sz.get(qn("w:val"))) / 2 if sz is not None else self.default_sz
        b = lookup("w:b")
        bold = b is not None and b.get(qn("w:val"), "1") not in ("0", "false")
        col = lookup("w:color")
        color = col.get(qn("w:val")) if col is not None else None
        if color in (None, "auto"):
            color = "000000"
        return size, bold, color

    def _para_size(self, p):
        """빈 단락 높이용: 단락 기호 크기."""
        ppr = p.find(qn("w:pPr"))
        sz = None
        if ppr is not None and ppr.find(qn("w:rPr")) is not None:
            sz = ppr.find(qn("w:rPr")).find(qn("w:sz"))
        if sz is None:
            sz = self._style_prop(_val(ppr, qn("w:pStyle")), "w:sz")
        return int(sz.get(qn("w:val"))) / 2 if sz is not None else self.default_sz

    # ---- 블록 변환
    def paragraph(self, p, avail_w):
        ppr = p.find(qn("w:pPr"))
        jc = _val(ppr, qn("w:jc"))
        if jc is None:
            x = self._style_prop(_val(ppr, qn("w:pStyle")), "w:jc")
            jc = x.get(qn("w:val")) if x is not None else None
        ind = ppr.find(qn("w:ind")) if ppr is not None else None
        left = int(ind.get(qn("w:left"), 0) or 0) / 20 if ind is not None else 0
        shd = ppr.find(qn("w:shd")) if ppr is not None else None
        bg = shd.get(qn("w:fill")) if shd is not None else None

        parts, images, max_size = [], [], 0
        for r in p.iter(qn("w:r")):
            size, bold, color = self._run_props(r, p)
            for child in r:
                if child.tag == qn("w:t"):
                    txt = escape(_glyph_safe(child.text or "")).replace("  ", " &nbsp;")
                    if txt:
                        max_size = max(max_size, size)
                        t = f'<font size="{size}" color="#{color}">{txt}</font>'
                        parts.append(f"<b>{t}</b>" if bold else t)
                elif child.tag == qn("w:br"):
                    parts.append("<br/>")
                elif child.tag == qn("w:tab"):
                    parts.append("&nbsp;&nbsp;&nbsp;&nbsp;")
                elif child.tag == qn("w:drawing"):
                    img = self._image(child, avail_w)
                    if img is not None:
                        images.append(img)
        out = []
        text = "".join(parts)
        if text.strip():
            size = max_size or self.default_sz
            style = ParagraphStyle(
                "p", fontName=FONT, fontSize=size, leading=size * 1.45,
                alignment=ALIGN.get(jc, TA_LEFT), leftIndent=min(left, avail_w * 0.5),
                backColor=colors.HexColor("#" + bg) if bg and bg not in ("auto", "FFFFFF") else None,
                wordWrap="CJK",
            )
            out.append(Paragraph(text, style))
        for img in images:
            img.hAlign = {"center": "CENTER", "right": "RIGHT"}.get(jc, "LEFT")
            out.append(img)
        if not out:
            out.append(Spacer(1, self._para_size(p) * 1.2))
        return out

    def _image(self, drawing, avail_w):
        blip = drawing.find(".//" + qn("a:blip"))
        ext = drawing.find(".//" + qn("wp:extent"))
        if blip is None:
            return None
        rid = blip.get(qn("r:embed"))
        part = self.doc.part.related_parts.get(rid)
        if part is None:
            return None
        w = int(ext.get("cx")) / 12700 if ext is not None else 200
        h = int(ext.get("cy")) / 12700 if ext is not None else 150
        if w > avail_w:
            h, w = h * avail_w / w, avail_w
        return Image(io.BytesIO(part.blob), width=w, height=h)

    def table(self, tbl, avail_w):
        grid = [int(g.get(qn("w:w"))) / 20 for g in tbl.findall(qn("w:tblGrid") + "/" + qn("w:gridCol"))]
        total = sum(grid) or avail_w
        scale = min(1.0, avail_w / total)
        grid = [g * scale for g in grid]
        ncol = len(grid)
        data, cmds, vmerge_start = [], [], {}
        trs = tbl.findall(qn("w:tr"))
        for ri, tr in enumerate(trs):
            row = [""] * ncol
            ci = 0
            for tc in tr.findall(qn("w:tc")):
                tcpr = tc.find(qn("w:tcPr"))
                span = int(_val(tcpr, qn("w:gridSpan")) or 1)
                vm = tcpr.find(qn("w:vMerge")) if tcpr is not None else None
                width = sum(grid[ci:ci + span]) - 6
                if ci >= ncol:
                    break
                if vm is not None and vm.get(qn("w:val")) != "restart":
                    start = vmerge_start.get(ci)
                    if start is not None:
                        cmds.append(("SPAN", (ci, start), (min(ci + span, ncol) - 1, ri)))
                else:
                    content = []
                    for el in tc:
                        if el.tag == qn("w:p"):
                            content += self.paragraph(el, width)
                        elif el.tag == qn("w:tbl"):
                            content.append(self.table(el, width))
                    row[ci] = content
                    if vm is not None:
                        vmerge_start[ci] = ri
                    else:
                        vmerge_start.pop(ci, None)
                    if span > 1:
                        cmds.append(("SPAN", (ci, ri), (min(ci + span, ncol) - 1, ri)))
                fill = None
                shd = tcpr.find(qn("w:shd")) if tcpr is not None else None
                if shd is not None:
                    fill = shd.get(qn("w:fill"))
                if fill and fill not in ("auto", "FFFFFF"):
                    cmds.append(("BACKGROUND", (ci, ri), (min(ci + span, ncol) - 1, ri), colors.HexColor("#" + fill)))
                valign = _val(tcpr, qn("w:vAlign"))
                if valign == "center":
                    cmds.append(("VALIGN", (ci, ri), (ci, ri), "MIDDLE"))
                ci += span
            data.append(row)
        # 병합 해제 범위 보정(SPAN 중복 제거)
        cmds = [c for i, c in enumerate(cmds) if c not in cmds[:i]]
        t = Table(data, colWidths=grid, repeatRows=0)
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#444444")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ] + cmds))
        return t


def docx_to_pdf(docx_path, pdf_path):
    _register_fonts()
    doc = Document(docx_path)
    sec = doc.sections[0]
    pw, ph = (sec.page_width or 8.27 * inch * 914400 / 72) / 12700, (sec.page_height or 11.69 * inch) / 12700
    lm = (sec.left_margin or 914400) / 12700
    rm = (sec.right_margin or 914400) / 12700
    tm = (sec.top_margin or 914400) / 12700
    bm = (sec.bottom_margin or 914400) / 12700
    avail = pw - lm - rm
    r = Renderer(doc)
    story = []
    for el in doc.element.body.iterchildren():
        if el.tag == qn("w:p"):
            story += r.paragraph(el, avail)
        elif el.tag == qn("w:tbl"):
            story.append(r.table(el, avail))
    SimpleDocTemplate(pdf_path, pagesize=(pw, ph), leftMargin=lm, rightMargin=rm,
                      topMargin=tm, bottomMargin=bm).build(story)
    return pdf_path
