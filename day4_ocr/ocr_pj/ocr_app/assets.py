"""보고서에 넣을 '구현사진'용 이미지 생성 (추출 결과 오버레이, 판정표, 보고서 요약 카드)."""
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "/System/Library/Fonts/AppleSDGothicNeo.ttc"


def _font(size, bold=False):
    try:
        return ImageFont.truetype(FONT_PATH, size, index=6 if bold else 0)
    except OSError:
        return ImageFont.load_default()


def annotate_sample(src, row, out):
    """원본 화면 위에 추출된 값을 표시한 이미지."""
    im = Image.open(src).convert("RGB")
    im.thumbnail((1200, 900))
    d = ImageDraw.Draw(im)
    w, h = im.size
    box = (int(w * 0.05), int(h * 0.30), int(w * 0.62), int(h * 0.56))
    d.rectangle(box, fill=(255, 255, 255), outline=(30, 90, 200), width=4)
    f, fb = _font(int(h * 0.032)), _font(int(h * 0.036), True)
    x, y = box[0] + 18, box[1] + 14
    d.text((x, y), f"OCR 추출 결과 · {row['file']}", font=fb, fill=(20, 50, 120))
    lines = [
        f"마커 주파수 : {row['freq_mhz']:.3f} MHz  ({'OCR' if row['freq_source'] == 'ocr' else '그래프 추정'})",
        f"마커 전력   : {row['power_uw']:.2f} µW  ({'OCR' if row['power_source'] == 'ocr' else '그래프 추정'})",
        f"판정 : {row['verdict']}  (마진 {row['margin']:.2f} dB)" if row.get("margin") is not None else "판정 : -",
    ]
    for i, t in enumerate(lines):
        d.text((x, y + int(h * 0.055) * (i + 1)), t, font=f, fill=(0, 0, 0))
    im.save(out)
    return out


def verdict_table(rows, summary, out):
    """판정 결과 표 이미지."""
    cols = ["No.", "파일", "주파수(MHz)", "전력(µW)", "dBµV/m", "Limit", "마진(dB)", "판정"]
    widths = [60, 150, 170, 130, 120, 90, 120, 110]
    rh, head = 34, 56
    W = sum(widths) + 40
    H = head + rh * (len(rows) + 1) + 30
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    fb, f = _font(22, True), _font(19)
    d.text((20, 14), f"PASS/FAIL 자동 판정 결과  —  총 {summary['total']}건 · PASS {summary['pass_cnt']} · FAIL {summary['fail_cnt']}",
           font=fb, fill=(20, 50, 120))
    y = head
    x = 20
    for c, w in zip(cols, widths):
        d.rectangle((x, y, x + w, y + rh), fill=(31, 78, 121), outline=(180, 180, 180))
        d.text((x + 8, y + 6), c, font=f, fill="white")
        x += w
    for r in rows:
        y += rh
        x = 20
        fmt = lambda v, n: "-" if v is None else f"{v:.{n}f}"
        vals = [str(r["no"]), r.get("file", ""), fmt(r.get("freq_mhz"), 3), fmt(r.get("power_uw"), 2),
                fmt(r.get("dbuv_m"), 2), fmt(r.get("limit"), 1), fmt(r.get("margin"), 2), r["verdict"]]
        for i, (v, w) in enumerate(zip(vals, widths)):
            bg = (255, 255, 255)
            if i == 7:
                bg = (220, 245, 225) if v == "PASS" else (252, 222, 222) if v == "FAIL" else (240, 240, 240)
            d.rectangle((x, y, x + w, y + rh), fill=bg, outline=(200, 200, 200))
            d.text((x + 8, y + 7), v, font=f, fill=(0, 0, 0))
            x += w
    im.save(out)
    return out


def report_card(values, files, out):
    """성적서 자동 기입 결과 요약 카드."""
    W, H = 1100, 120 + 44 * (len(files) + 7)
    im = Image.new("RGB", (W, H), (246, 248, 251))
    d = ImageDraw.Draw(im)
    fb, f = _font(28, True), _font(21)
    d.rectangle((0, 0, W, 70), fill=(31, 78, 121))
    d.text((24, 18), "성적서 자동 기입 · 생성 결과", font=fb, fill="white")
    y = 90
    for k, label in [("doc_no", "문서번호"), ("test_date", "시험일"), ("test_name", "시험명"),
                     ("verdict", "종합판정"), ("generated_at", "생성일시")]:
        d.text((30, y), f"{label}", font=f, fill=(90, 90, 90))
        d.text((220, y), str(values.get(k, "")), font=f, fill=(0, 0, 0))
        y += 44
    d.line((30, y, W - 30, y), fill=(200, 200, 200), width=2)
    y += 16
    d.text((30, y), "생성 파일", font=f, fill=(90, 90, 90))
    for name in files:
        d.text((220, y), f"✓ {name}", font=f, fill=(20, 110, 60))
        y += 44
    im.save(out)
    return out
