# OCR 분석 성적서 자동 작성

스펙트럼 분석기 화면 이미지에서 마커 주파수·전력을 OCR로 읽고, PASS/FAIL을 판정한 뒤
업로드한 워드(.docx) 양식의 빈자리에 채워 DOCX / PDF로 내려받는 웹 프로그램입니다.

## 실행

```bash
cd ocr_pj
./run.sh                 # 패키지 설치 후 실행, 브라우저 자동 열림
# 또는
pip3 install -r requirements.txt
python3 main.py          # http://127.0.0.1:8765
```

- macOS 전용 (OCR에 macOS Vision 프레임워크 사용, 외부 전송 없음)
- Python 3.10 이상

## 사용 순서

1. 사진 업로드 (또는 상단 **샘플 불러오기**: `samples/images` 20장 + `samples/docs/report_template.docx`)
2. 워드 양식 업로드
3. 추출값 확인·수정 (노란 칸 = 가려진 표시값을 그래프로 추정한 값), 기입 정보 확인
4. **양식 채워서 생성** → 문서별 DOCX / PDF / ZIP 다운로드 (다운로드 전에 파일명 입력 창이 뜸)

## 폴더 구조

```
ocr_pj/
├── main.py              실행 파일
├── run.sh               설치+실행 스크립트
├── requirements.txt
├── ocr_app/
│   ├── server.py        웹 서버(FastAPI) · API
│   ├── extractor.py     OCR(macOS Vision) + 가려진 값 그래프 추정
│   ├── calc.py          dBm·dBµV/m 환산, FCC Part 15 Class B 판정
│   ├── filler.py        DOCX 양식 채우기 ({{치환자}} / 빈칸 양식)
│   ├── pdf_render.py    DOCX → PDF 변환 (reportlab)
│   ├── assets.py        보고서에 넣을 이미지(판정표 등) 생성
│   └── static/index.html  화면
├── samples/             테스트용 이미지·양식
└── output/              생성 파일 (실행할 때마다 비워짐)
```

## 판정 산식

- 측정값(dBµV/m) = 10·log10(µW/1000) + 107 + CF (CF 기본값 -52 dB는 테스트용 가정값)
- 마진(dB) = Limit − 측정값, 마진 ≥ 0 → PASS
