MODEL = "gpt-5.6-luna"

from datetime import date

import pandas as pd
import streamlit as st

import judge
import report
from ocr import KEYS, extract_marker

COLUMN_LABELS = {
    "file": "파일",
    "marker_freq": "마커 주파수",
    "freq_unit": "주파수 단위",
    "marker_power": "마커 전력",
    "power_unit": "전력 단위",
    "readable": "판독 가능",
    "note": "비고",
}

st.set_page_config(page_title="OCR 판정 보고서", layout="wide")
st.title("OCR 판정 보고서")

with st.sidebar:
    st.header("설정")
    st.session_state["api_key"] = st.text_input(
        "API 키", type="password", value=st.session_state.get("api_key", "")
    )
    st.caption(f"모델: {MODEL}")
    st.caption("API 키는 이 화면 세션에만 보관되며 저장되지 않습니다.")

    st.header("판정 기준")
    cf = st.number_input("CF (dB)", value=judge.DEFAULT_CF, step=0.1, format="%.1f")
    limit = st.number_input("Limit (dBµV/m)", value=judge.DEFAULT_LIMIT, step=0.1, format="%.1f")
    use_freq = st.checkbox("주파수 기준 사용", value=True)
    freq_min = st.number_input(
        "주파수 하한 (GHz)", value=judge.DEFAULT_FREQ_MIN, step=0.0001, format="%.4f", disabled=not use_freq
    )
    freq_max = st.number_input(
        "주파수 상한 (GHz)", value=judge.DEFAULT_FREQ_MAX, step=0.0001, format="%.4f", disabled=not use_freq
    )
    if use_freq and freq_min > freq_max:
        st.error("주파수 하한이 상한보다 큽니다.")

st.subheader("1. 이미지 업로드")
uploaded = st.file_uploader(
    "스펙트럼 분석기 캡처 이미지 (PNG/JPG, 여러 장 가능)",
    type=["png", "jpg", "jpeg"],
    accept_multiple_files=True,
)
uploaded = sorted(uploaded or [], key=lambda f: f.name)

if uploaded:
    st.caption(f"{len(uploaded)}장 업로드됨")
    cols = st.columns(5)
    for i, f in enumerate(uploaded):
        cols[i % 5].image(f, caption=f.name, width="stretch")

st.subheader("2. 데이터 추출")
if st.button("추출 시작", type="primary", disabled=not uploaded):
    if not st.session_state["api_key"]:
        st.warning("사이드바에 API 키를 입력해 주세요.")
    else:
        results = []
        progress = st.progress(0.0, text="추출 준비 중...")
        for i, f in enumerate(uploaded, start=1):
            progress.progress((i - 1) / len(uploaded), text=f"{i}/{len(uploaded)} 처리 중: {f.name}")
            results.append(extract_marker(f.getvalue(), f.name, st.session_state["api_key"], MODEL))
        progress.progress(1.0, text=f"{len(uploaded)}장 처리 완료")
        st.session_state["results"] = pd.DataFrame(results, columns=KEYS)
        st.session_state.pop("edited_results", None)

if "results" in st.session_state:
    df = st.session_state["results"]
    failed = df["note"].str.startswith("추출 실패").sum()
    unreadable = (~df["readable"]).sum()
    st.caption(f"총 {len(df)}건 · 판독 불가 {unreadable}건 (그중 추출 실패 {failed}건)")

    st.subheader("3. 결과 확인 및 수정")
    st.caption("표의 값을 직접 고칠 수 있습니다. 고친 값은 다음 단계(판정)에 사용됩니다.")
    st.session_state["edited_results"] = st.data_editor(
        df,
        key="results_editor",
        hide_index=True,
        width="stretch",
        disabled=["file"],
        column_config={
            "file": st.column_config.TextColumn(COLUMN_LABELS["file"]),
            "marker_freq": st.column_config.NumberColumn(COLUMN_LABELS["marker_freq"], format="%.6f"),
            "freq_unit": st.column_config.SelectboxColumn(
                COLUMN_LABELS["freq_unit"], options=["Hz", "kHz", "MHz", "GHz"]
            ),
            "marker_power": st.column_config.NumberColumn(COLUMN_LABELS["marker_power"], format="%.5g"),
            "power_unit": st.column_config.SelectboxColumn(
                COLUMN_LABELS["power_unit"], options=["pW", "nW", "µW", "mW", "W"]
            ),
            "readable": st.column_config.CheckboxColumn(COLUMN_LABELS["readable"]),
            "note": st.column_config.TextColumn(COLUMN_LABELS["note"]),
        },
    )

    st.subheader("4. 판정")
    rows = st.session_state["edited_results"].to_dict("records")
    judged = judge.judge_all(
        rows, cf=cf, limit=limit, freq_min=freq_min, freq_max=freq_max, use_freq=use_freq
    )
    summary = judge.summarize(judged)
    st.session_state["judged"] = judged
    st.session_state["summary"] = summary

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("총 건수", summary["total"])
    c2.metric("PASS", summary["pass"])
    c3.metric("FAIL", summary["fail"])
    c4.metric("확인필요", summary["check"])
    c5.metric("종합판정", summary["overall"])

    def _color(value):
        return {
            judge.PASS: "color: #1a7f37; font-weight: bold",
            judge.FAIL: "color: #cf222e; font-weight: bold",
            judge.CHECK: "color: #9a6700; font-weight: bold",
        }.get(value, "")

    judged_df = pd.DataFrame(judged).rename(
        columns={
            "file": "파일",
            "freq_ghz": "주파수 (GHz)",
            "power_uw": "전력 (µW)",
            "dbm": "전력 (dBm)",
            "measured": "측정값 (dBµV/m)",
            "margin": "마진 (dB)",
            "result": "판정",
            "reason": "사유",
        }
    )
    st.dataframe(
        judged_df.style.map(_color, subset=["판정"]).format(
            {
                "주파수 (GHz)": "{:.6f}",
                "전력 (µW)": "{:.3f}",
                "전력 (dBm)": "{:.2f}",
                "측정값 (dBµV/m)": "{:.2f}",
                "마진 (dB)": "{:.2f}",
            },
            na_rep="-",
        ),
        hide_index=True,
        width="stretch",
    )

    st.subheader("5. 보고서")
    c1, c2, c3 = st.columns(3)
    info = {
        "doc_no": c1.text_input("문서번호"),
        "test_date": c2.date_input("시험일", value=date.today()).strftime("%Y-%m-%d"),
        "test_name": c3.text_input("시험명", value="방사성 방출 (RE)"),
        "sample_name": c1.text_input("시료명"),
        "tester": c2.text_input("담당자"),
        "reviewer": c3.text_input("검토자"),
        "standard": c1.text_input("적용 규격", value=report.DEFAULT_STANDARD),
    }
    notes = dict(zip(st.session_state["edited_results"]["file"], st.session_state["edited_results"]["note"]))

    if not info["doc_no"].strip():
        st.info("문서번호를 입력하면 보고서를 내려받을 수 있습니다.")
    else:
        d1, d2 = st.columns(2)
        d1.download_button(
            "보고서 다운로드",
            data=report.build_report(info, judged, summary, cf, limit, notes=notes),
            file_name=report.report_filename(info["doc_no"]),
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary",
        )
        d2.download_button(
            "결과 CSV 다운로드",
            data=report.results_csv(rows, judged, limit),
            file_name=report.report_filename(info["doc_no"]).replace("_RE보고서.docx", "_RE결과.csv"),
            mime="text/csv",
        )
