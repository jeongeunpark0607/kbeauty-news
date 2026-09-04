#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
search_app.py
=============
Streamlit 기반 검색 웹 UI.

실행:
    streamlit run search_app.py

기업명 / 키워드 / 기간을 조합해 누적 DB(SQLite)를 검색하고 표/카드 형태로 보여줍니다.
"""
from datetime import timedelta

import pandas as pd
import streamlit as st

import db
from config import TARGET_COMPANIES, now_kst

st.set_page_config(page_title="K-뷰티 뉴스클리핑 검색", layout="wide")

st.title("💄 K-뷰티 뉴스클리핑 검색")
st.caption("누적 DB에서 기업명 · 키워드 · 기간으로 뉴스/리포트를 검색합니다.")

db.init_db()

with st.sidebar:
    st.header("🔍 검색 조건")

    company_options = ["(전체)"] + list(TARGET_COMPANIES.keys()) + ["산업전반"]
    company = st.selectbox("기업명", company_options, index=0)

    keyword = st.text_input("키워드 (제목/요약/태그, 예: 북미, 선케어, EU 규제)")

    category = st.selectbox("구분", ["(전체)", "뉴스", "리포트"], index=0)

    period_mode = st.radio("기간", ["최근 N일", "직접 지정"], horizontal=True)
    if period_mode == "최근 N일":
        days = st.slider("최근 며칠", min_value=1, max_value=180, value=30)
        start_date = (now_kst() - timedelta(days=days)).strftime("%Y-%m-%d")
        end_date = now_kst().strftime("%Y-%m-%d")
    else:
        col1, col2 = st.columns(2)
        start_date = col1.date_input("시작일", value=now_kst() - timedelta(days=30)).strftime("%Y-%m-%d")
        end_date = col2.date_input("종료일", value=now_kst()).strftime("%Y-%m-%d")

    limit = st.number_input("최대 표시 건수", min_value=10, max_value=1000, value=200, step=10)

    search_clicked = st.button("검색", type="primary", use_container_width=True)

if search_clicked or "last_results" not in st.session_state:
    results = db.search(
        company=None if company == "(전체)" else company,
        keyword=keyword or None,
        category=None if category == "(전체)" else category,
        start_date=start_date,
        end_date=end_date,
        limit=int(limit),
    )
    st.session_state["last_results"] = results
else:
    results = st.session_state["last_results"]

st.subheader(f"검색 결과: {len(results)}건")

if not results:
    st.info("검색 결과가 없습니다. 조건을 조정해 보세요.")
else:
    df = pd.DataFrame(results)

    def _summary_preview(s):
        """표에서는 요약 첫 줄만 짧게 보여주고, 전체 5줄 요약은 '카드로 보기' 탭에서 확인."""
        if not isinstance(s, str) or not s:
            return ""
        first_line = s.split("\n")[0].lstrip("- ").strip()
        return first_line + (" ⋯" if "\n" in s else "")

    if "summary" in df.columns:
        df["summary_preview"] = df["summary"].apply(_summary_preview)

    tab_table, tab_cards = st.tabs(["📋 표로 보기", "🗂 카드로 보기 (전체 요약)"])

    with tab_table:
        st.caption("요약 전체(최대 5줄)는 옆의 **'카드로 보기'** 탭에서 줄바꿈된 형태로 볼 수 있습니다.")
        show_cols = [
            "collected_at", "category", "company", "title", "summary_preview", "source",
            "opinion", "target_price", "keywords", "link",
        ]
        show_cols = [c for c in show_cols if c in df.columns]
        st.dataframe(
            df[show_cols],
            use_container_width=True,
            column_config={
                "link": st.column_config.LinkColumn("링크"),
                "summary_preview": st.column_config.TextColumn("요약(첫 줄)", width="large"),
                "title": st.column_config.TextColumn("제목", width="medium"),
            },
            hide_index=True,
        )
        csv = df.drop(columns=["summary_preview"], errors="ignore").to_csv(index=False).encode("utf-8-sig")
        st.download_button("CSV로 다운로드 (요약 전체 포함)", data=csv, file_name="kbeauty_search_result.csv", mime="text/csv")

    with tab_cards:
        for r in results:
            with st.container(border=True):
                st.markdown(f"**[{r['company']}] {r['title']}**  \n`{r['category']}` · {r.get('source','-')} · {r['collected_at']}")
                if r.get("summary"):
                    st.markdown(r["summary"])
                meta = []
                if r.get("keywords"):
                    meta.append(f"🏷 {r['keywords']}")
                if r.get("opinion"):
                    meta.append(f"📈 투자의견: {r['opinion']}")
                if r.get("target_price"):
                    meta.append(f"🎯 목표주가: {r['target_price']}원")
                if meta:
                    st.caption(" | ".join(meta))
                st.markdown(f"[원문 보기]({r['link']})")
