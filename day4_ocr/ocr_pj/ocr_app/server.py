"""OCR 분석 성적서 자동 작성 — 웹 서버.

이미지 → 데이터 추출 → DOCX 양식 채우기 → DOCX/PDF 다운로드
실행: python3 main.py  (http://127.0.0.1:8765)
"""
import datetime as dt
import inspect
import io
import os
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from . import assets, calc, extractor, filler
from .pdf_render import docx_to_pdf

BASE = Path(__file__).parent
ROOT = BASE.parent
WORK = ROOT / "output"
WORK.mkdir(exist_ok=True)
SAMPLE_IMAGES = ROOT / "samples" / "images"
SAMPLE_TEMPLATES = [ROOT / "samples" / "docs" / "report_template.docx"]

app = FastAPI(title="OCR 분석 성적서 자동 작성")
SESSIONS = {}  # sid -> {"images": {name: path}, "templates": {name: path}, "results": {...}}


def _session(sid):
    if sid not in SESSIONS:
        d = WORK / sid
        (d / "images").mkdir(parents=True, exist_ok=True)
        (d / "templates").mkdir(exist_ok=True)
        (d / "result").mkdir(exist_ok=True)
        SESSIONS[sid] = {"dir": d, "images": {}, "templates": {}, "results": {}}
    return SESSIONS[sid]


def _safe(name):
    return re.sub(r"[\\/:*?\"<>|]", "_", Path(name).name)


@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE / "static" / "index.html").read_text(encoding="utf-8")


@app.post("/api/session")
def new_session():
    sid = uuid.uuid4().hex[:12]
    _session(sid)
    return {"sid": sid}


@app.post("/api/{sid}/images")
async def upload_images(sid: str, files: list[UploadFile] = File(...)):
    s = _session(sid)
    out = []
    for f in files:
        name = _safe(f.filename)
        if not re.search(r"\.(png|jpe?g|bmp|tiff?|gif|webp)$", name, re.I):
            continue
        path = s["dir"] / "images" / name
        path.write_bytes(await f.read())
        s["images"][name] = path
        try:
            row = extractor.extract(path)
        except Exception as e:  # OCR 실패도 행으로 남겨 수동 입력 가능하게
            row = {"file": name, "sample": "", "freq_mhz": None, "power_uw": None,
                   "freq_source": "none", "power_source": "none", "notes": [f"OCR 실패: {e}"]}
        out.append(row)
    out.sort(key=lambda r: r["file"])
    return {"rows": out}


@app.get("/api/{sid}/image/{name}")
def get_image(sid: str, name: str):
    p = _session(sid)["images"].get(name)
    if not p:
        raise HTTPException(404)
    return FileResponse(p)


@app.post("/api/{sid}/templates")
async def upload_templates(sid: str, files: list[UploadFile] = File(...)):
    s = _session(sid)
    out = []
    for f in files:
        name = _safe(f.filename)
        if not name.lower().endswith(".docx"):
            continue
        path = s["dir"] / "templates" / name
        path.write_bytes(await f.read())
        s["templates"][name] = path
        doc = filler.Document(path)
        kind = "치환자 양식 ({{…}})" if filler.has_placeholders(doc) else "라벨 양식 (빈칸 채우기)"
        keys = sorted({k for p in filler.all_paragraphs(doc) for k in filler.PH.findall(p.text)})
        out.append({"name": name, "kind": kind, "placeholders": keys})
    return {"templates": out}


@app.post("/api/{sid}/load-samples")
def load_samples(sid: str):
    """samples/ 폴더의 이미지와 report_template.docx를 업로드한 것처럼 불러온다 (테스트용)."""
    s = _session(sid)
    rows, temps = [], []
    for p in sorted(SAMPLE_IMAGES.glob("*")):
        if re.search(r"\.(png|jpe?g)$", p.name, re.I):
            dst = s["dir"] / "images" / p.name
            shutil.copy(p, dst)
            s["images"][p.name] = dst
            rows.append(extractor.extract(dst))
    for p in SAMPLE_TEMPLATES:
        if not p.exists():
            continue
        dst = s["dir"] / "templates" / p.name
        shutil.copy(p, dst)
        s["templates"][p.name] = dst
        doc = filler.Document(dst)
        temps.append({"name": p.name,
                      "kind": "치환자 양식 ({{…}})" if filler.has_placeholders(doc) else "라벨 양식 (빈칸 채우기)"})
    return {"rows": rows, "templates": temps}


# ------------------------------------------------------------------ 생성
class Row(BaseModel):
    file: str
    freq_mhz: float | None = None
    power_uw: float | None = None
    freq_source: str = "ocr"
    power_source: str = "ocr"
    notes: list[str] = []


class GenerateReq(BaseModel):
    rows: list[Row]
    fields: dict[str, str]
    templates: list[str]


def default_fields():
    """비어 있는 항목에 들어갈 가상(테스트) 데이터 기본값."""
    today = dt.date.today()
    return {
        "doc_no": f"HCT-RE-{today:%Y%m%d}-001",
        "test_date": f"{today:%Y-%m-%d}",
        "test_name": "2.4 GHz 대역 방사성 방출(RE) 측정",
        "tester": "홍길동",
        "reviewer": "김검토",
        "standard": "FCC Part 15 Subpart B Class B",
        "sample_name": "2.4 GHz 무선 모듈 (교육용 시료 TM-24)",
        "cf_db": "-52.0",
        "remarks": "",
        "company": "(주)테스트랩",
        "course": "AI 활용 시험·인증 업무 자동화(AX) 실무 과정",
        "period": f"{today - dt.timedelta(days=21):%Y.%m.%d} ~ {today:%Y.%m.%d}",
        "before_min": "30",
        "after_min": "3",
    }


@app.get("/api/defaults")
def defaults():
    return default_fields()


def _code_snippet(fn, max_lines=18):
    lines = inspect.getsource(fn).splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["    # ... (이하 생략)"]
    return "\n".join(lines)


def build_label_ctx(fields, rows, summary, images):
    n = summary["total"]
    ocr_ok = sum(r["freq_source"] == "ocr" and r["power_source"] == "ocr" and r["freq_mhz"] is not None
                 and r["power_uw"] is not None for r in rows)
    # 정답 비율: 화면값을 직접 판독(추정 아님)해 확정된 건수 기준. 사용자가 입력하면 그 값을 사용
    judged = sum(r["verdict"] in ("PASS", "FAIL") and r["freq_source"] == "ocr" and r["power_source"] == "ocr"
                 for r in rows)
    acc_ext = float(fields["acc_extract"]) if fields.get("acc_extract") else (round(ocr_ok / n * 100, 1) if n else 0)
    acc_jdg = float(fields["acc_judge"]) if fields.get("acc_judge") else (round(judged / n * 100, 1) if n else 0)
    before, after = int(fields["before_min"]), int(fields["after_min"])
    reduce = round((before - after) / before * 100, 1) if before else 0
    est = [r for r in rows if r["freq_source"] != "ocr" or r["power_source"] != "ocr"]
    est_txt = ", ".join(r["file"] for r in est) or "없음"
    fails = ", ".join(r["file"] for r in rows if r["verdict"] == "FAIL") or "없음"

    return {
        "labels": {
            "성명": fields["tester"], "훈련생 성함": fields["tester"], "기업명": fields["company"],
            "수행 기간": fields["period"], "훈련과정 명": fields["course"],
        },
        "sections": {
            "judge": {
                "문제 상황": "측정값을 사람이 dBµV/m로 환산하고 Limit과 비교해 판정하여 계산 실수와 판정 편차가 발생함",
                "수행 과정": "추출값 → dBm → dBµV/m(보정계수 CF 적용) 환산 후 FCC Part 15 Class B Limit과 마진을 계산하는 판정 로직 구현",
                "수행 결과": f"{n}건 자동 판정 (PASS {summary['pass_cnt']}건 / FAIL {summary['fail_cnt']}건), 판정 기준이 일관되게 적용됨",
            },
            "report": {
                "문제 상황": f"판정 결과를 성적서 양식에 수기로 옮겨 적어 건당 약 {before}분이 소요되고 오기입 위험이 있음",
                "수행 과정": "DOCX 양식의 치환자·빈칸을 인식해 측정표·요약·판정을 자동 기입하고 DOCX/PDF로 내려받는 웹 프로그램 구축",
                "수행 결과": f"성적서 작성 시간 {before}분 → {after}분 (약 {reduce}% 감소)",
            },
        },
        "cases": {
            "extract": f"스펙트럼 분석기 화면 캡처 {n}건에서 마커 주파수·전력을 자동 추출 (직접 판독 {ocr_ok}건, 가림 보정 {n - ocr_ok}건: {est_txt})",
            "judge": f"추출값을 dBµV/m로 환산해 FCC Part 15 Class B Limit과 비교, {n}건 중 PASS {summary['pass_cnt']}건 / FAIL {summary['fail_cnt']}건 자동 판정 (FAIL: {fails})",
            "report": f"판정 결과를 방사성 방출 시험결과 보고서 양식에 자동 기입하여 DOCX·PDF 생성, 작성 시간 {before}분 → {after}분",
            "improve": "가려지거나 흐린 화면에 대한 추정 정확도 향상, 다른 계측기 화면 양식 추가 지원, LIMS 연동 검토",
        },
        "metrics": {
            "extract": {"value": acc_ext, "n": n, "achieved": acc_ext >= 90, "after_min": after},
            "judge": {"value": acc_jdg, "n": n, "achieved": acc_jdg >= 90, "after_min": after},
            "report": {"value": reduce, "n": n, "achieved": reduce >= 50, "after_min": after},
        },
        "eval": f"추출 정확도 {acc_ext}%, 판정 정확도 {acc_jdg}%, 성적서 작성 시간 {reduce}% 감소로 목표 대비 "
                + ("전 항목 달성" if acc_ext >= 90 and acc_jdg >= 90 and reduce >= 50 else "일부 항목 미달성"),
        "summary": f"이미지 {n}건 자동 추출·판정·성적서 기입 완료 (PASS {summary['pass_cnt']} / FAIL {summary['fail_cnt']}). "
                   f"표시값이 가려진 이미지({est_txt})는 그래프 위치로 추정하여 보고서 특이사항에 표기함.",
        "code": {
            "extract": _code_snippet(extractor.extract),
            "judge": _code_snippet(calc.judge),
            "report": _code_snippet(filler.fill_placeholder_doc),
        },
        "desc": {
            "extract": "macOS Vision OCR로 화면 텍스트를 읽고, 가림 박스가 감지되면 그래프의 마커·트레이스 위치로 값을 추정",
            "judge": "dBµV/m = 10·log10(µW/1000) + 107 + CF, 마진 = Limit − 측정값, 마진 ≥ 0 이면 PASS",
            "report": "업로드한 DOCX 양식의 치환자·빈칸을 인식하여 자동 기입 후 DOCX/PDF로 다운로드",
        },
        "images": images,
        "issue": [f"화면 표시값이 가려진 이미지({est_txt})는 그래프 기반 추정값으로, 원본 측정 데이터 확인 필요"],
        "plan": ["계측기 원시 데이터(CSV) 직접 연동 및 다양한 계측기 화면 양식 학습", "판정 결과 LIMS 자동 등록 기능 추가 훈련"],
        "image_width_cm": 12,
    }


@app.post("/api/{sid}/generate")
def generate(sid: str, req: GenerateReq):
    s = _session(sid)
    fields = default_fields() | {k: v for k, v in req.fields.items() if str(v).strip()}
    try:
        cf = float(fields["cf_db"])
    except ValueError:
        raise HTTPException(400, "보정계수(CF)는 숫자여야 합니다")

    rows = [r.model_dump() for r in req.rows]
    judged, summary = calc.judge(rows, cf)

    if not fields.get("remarks"):
        notes = [f"#{r['no']} {r['file']}: {n}" for r in judged for n in r["notes"]]
        fails = [f"#{r['no']}({r['freq_mhz']:.3f} MHz, 마진 {r['margin']:.2f} dB)" for r in judged if r["verdict"] == "FAIL"]
        parts = []
        if fails:
            parts.append("FAIL 항목: " + ", ".join(fails))
        parts += notes
        fields["remarks"] = " / ".join(parts) if parts else "특이사항 없음"

    now = dt.datetime.now()
    values = fields | {k: str(v) for k, v in summary.items()} | {"generated_at": f"{now:%Y-%m-%d %H:%M}"}
    values["cf_db"] = f"{cf:g}"

    out_dir = s["dir"] / "result" / now.strftime("%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    # '구현사진' 등에 넣을 이미지
    first = next((r for r in judged if r["freq_mhz"] is not None and r["power_uw"] is not None), None)
    imgs = {}
    if first:
        imgs["extract"] = [assets.annotate_sample(s["images"][first["file"]], first, out_dir / "_ocr.png")] \
            if first["file"] in s["images"] else []
    imgs["judge"] = [assets.verdict_table(judged, summary, out_dir / "_verdict.png")]
    names = [Path(t).stem + "_작성.docx" for t in req.templates]
    imgs["report"] = [assets.report_card(values, names, out_dir / "_report.png"), imgs["judge"][0]]
    imgs = {k: [str(p) for p in v] for k, v in imgs.items()}

    ctx = build_label_ctx(fields, judged, summary, imgs)
    rows_fmt = [calc.fmt_row(r) for r in judged]

    results = []
    for t in req.templates:
        src = s["templates"].get(t)
        if not src:
            continue
        out = out_dir / (Path(t).stem + "_작성.docx")
        kind = filler.fill(src, out, values, rows_fmt, ctx)
        pdf = out.with_suffix(".pdf")
        pdf_err = None
        try:
            docx_to_pdf(str(out), str(pdf))
        except Exception as e:
            pdf_err = str(e)
        rid = uuid.uuid4().hex[:8]
        s["results"][rid] = {"docx": out, "pdf": pdf if not pdf_err else None}
        results.append({"id": rid, "name": out.name, "kind": kind, "pdf_error": pdf_err})
    s["last"] = [r["id"] for r in results]
    return {"results": results, "rows": judged, "summary": summary, "values": values}


def _download_name(name, ext, fallback):
    """사용자가 정한 파일명(확장자 없으면 붙임). 비었거나 경로 문자가 있으면 정리."""
    name = _safe((name or "").strip()) or fallback
    return name if name.lower().endswith("." + ext) else f"{name}.{ext}"


@app.get("/api/{sid}/download/{rid}.{fmt}")
def download(sid: str, rid: str, fmt: str, inline: bool = False, name: str = ""):
    r = _session(sid)["results"].get(rid)
    if not r or fmt not in ("docx", "pdf") or not r[fmt]:
        raise HTTPException(404)
    p = r[fmt]
    # inline=1: 브라우저 안에서 PDF 미리보기
    return FileResponse(p, filename=_download_name(name, fmt, p.stem),
                        content_disposition_type="inline" if inline else "attachment")


@app.get("/api/{sid}/download-all.zip")
def download_all(sid: str, fmt: str = "all", name: str = ""):
    s = _session(sid)
    fmts = ("docx", "pdf") if fmt == "all" else (fmt,)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rid in s.get("last", []):
            for f in fmts:
                p = s["results"][rid].get(f)
                if p:
                    z.write(p, p.name)
    buf.seek(0)
    fname = _download_name(name, "zip", "results")
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"})


def run(port=None, open_browser=True):
    """이전 작업 파일을 비우고 서버 실행."""
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(exist_ok=True)
    port = port or int(os.environ.get("PORT", 8765))
    if open_browser:
        import threading
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    uvicorn.run(app, host="127.0.0.1", port=port)
