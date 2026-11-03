#!/bin/zsh
# OCR 분석 성적서 자동 작성 실행 (macOS)
cd "$(dirname "$0")"
pip3 install -q -r requirements.txt
python3 main.py "$@"
