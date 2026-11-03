"""OCR 분석 성적서 자동 작성 — 실행 파일.

사용법:
    python3 main.py              # http://127.0.0.1:8765 에서 실행하고 브라우저 열기
    python3 main.py --port 9000  # 포트 변경
    python3 main.py --no-browser # 브라우저 자동 열기 끔
"""
import argparse

from ocr_app.server import run

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="OCR 분석 성적서 자동 작성")
    ap.add_argument("--port", type=int, default=None, help="서버 포트 (기본 8765, 환경변수 PORT)")
    ap.add_argument("--no-browser", action="store_true", help="브라우저 자동 열기 끄기")
    args = ap.parse_args()
    run(port=args.port, open_browser=not args.no_browser)
