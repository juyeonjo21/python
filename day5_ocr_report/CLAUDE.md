# CLAUDE.md — OCR 판정 보고서 앱 (Streamlit)

## 프로젝트 한 줄 설명
스펙트럼 분석기 화면 이미지에서 마커 주파수·전력을 AI로 읽고, 기준에 따라 PASS/FAIL을 판정해
report_template.docx 양식으로 보고서를 만드는 Streamlit 앱. 상세 요구사항은 @PRD.md

## 폴더 구조
- app.py            : Streamlit 화면 (화면 코드만)
- ocr.py            : 이미지 → AI 호출 → JSON 결과
- judge.py          : 단위 변환, dB 계산, 판정 (AI 사용 금지, 순수 계산)
- report.py         : docx 템플릿 채우기
- images/           : 실습 이미지 20장 (수정 금지)
- docs/report_template.docx : 보고서 양식 (수정 금지, {{ }} 자리만 채움)
- tests/            : pytest 테스트

## 작업 규칙
- 한 번에 PRD의 마일스톤 하나만 구현하고, 끝나면 멈춰서 확인 방법을 알려준다.
- 계산과 판정은 judge.py의 함수로만 한다. AI에게 계산을 시키지 않는다.
- API 키는 화면에서 입력받아 st.session_state에만 둔다. 코드·파일·로그에 남기지 않는다.
- 모델명은 app.py 맨 위 MODEL 상수 한 곳에서 관리한다.
- 읽지 못한 값은 추측하지 말고 None으로 두고, 판정은 "확인필요"로 한다.
- 새 기능을 넣으면 tests/에 테스트를 추가하고 pytest를 실행한다.
- 화면 문구는 한국어로 쓴다.

## 실행
- 설치: pip install -r requirements.txt
- 실행: streamlit run app.py
- 테스트: pytest -q

## 자주 겪은 문제와 해결
- (작업하면서 계속 추가한다)
- `pytest`/`python` 명령이 없다고 나올 때: `python3 -m pip install -r requirements.txt` 후 `python3 -m pytest -q`로 실행한다.
- 표(st.data_editor)를 거치면 None이 NaN으로 바뀐다: judge.py는 NaN도 None으로 보고 "확인필요"로 판정한다. 특이사항에 "nan"이 찍히지 않게 비고도 문자열일 때만 쓴다.
- 경계값 판정이 부동소수 오차로 틀어질 수 있다 (예: 2406.000 MHz → 2.4060000000000001 GHz): 주파수는 GHz로 바꾼 뒤 소수 9자리(1 Hz)로 반올림하고, 마진은 보고서 표시와 같은 소수 2자리로 반올림한 뒤 판정한다.
- 보고서 서식 유지: 템플릿의 {{ }}는 각각 한 run에 들어 있어 run 글자만 바꾸면 서식이 유지된다. 템플릿을 Word에서 다시 저장해 {{ }}가 여러 run으로 쪼개지면 치환이 안 되므로, tests/test_report.py의 "{{ 가 남지 않음" 테스트로 확인한다.
- 측정 결과 표 행 복제: {{r.*}} 행(w:tr)을 deepcopy해 결과 건수만큼 붙이고 원본 행은 지운다. 행 서식(셀 음영·테두리)은 복제로 그대로 따라온다.
- 템플릿 요약 표에 "확인필요" 칸이 없다 (템플릿 수정 금지): 확인필요 건수는 종합판정("부적합/확인필요")과 특이사항으로 보여준다. {{standard}}는 PRD 입력 항목에 없어 화면에 "적용 규격" 입력칸(기본 FCC Part 15 Subpart B Class B)을 추가했다.
- 실행 중인 앱에 코드 수정이 바로 반영되지 않을 때: 브라우저 새로고침 또는 우측 상단 "Rerun"을 누른다 (watchdog 미설치라 자동 감지가 느림).
- streamlit AppTest로 화면을 시험할 때 at.text_input[i]는 사이드바 포함 순서라 인덱스가 헷갈린다: 라벨로 찾는다.
- 완료 기준 확인은 실제 추출이 필요하다 (API 키는 저장 금지라 Claude가 직접 못 돌림): 사용자가 앱에서 내려받은 보고서/CSV로 확인한다.
