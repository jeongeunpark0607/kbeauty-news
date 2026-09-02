# -*- coding: utf-8 -*-
"""
db.py
=====
SQLite 기반 누적 데이터베이스 계층.

테이블: news_report
----------------------------------------------------------------------------
컬럼               타입        설명
----------------------------------------------------------------------------
id                 INTEGER     PK, 자동증가
collected_at       TEXT        데이터 수집(적재) 일시 (YYYY-MM-DD HH:MM:SS)
published_at       TEXT        원문 발행 일시 (알 수 없으면 collected_at과 동일)
category           TEXT        '뉴스' | '리포트'
company            TEXT        관련 기업명 (TARGET_COMPANIES의 key). 산업 전반 기사면 '산업전반'
title              TEXT        제목
summary            TEXT        AI 요약 (2~3문장)
source             TEXT        매체명 / 증권사명
link               TEXT        원문 링크 (UNIQUE, 중복 수집 방지 키)
opinion             TEXT        투자의견 (예: 매수/BUY/Hold) - 리포트가 아니면 빈 값
target_price       TEXT        목표주가 (원 단위 문자열, 파싱 불가시 빈 값)
keywords           TEXT        쉼표로 구분된 관련 키워드 태그
raw_description    TEXT        원문 스니펫(요약 실패시 폴백 표시용)
created_at         TEXT        레코드 생성 타임스탬프 (감사용)
----------------------------------------------------------------------------

link 컬럼에 UNIQUE 제약을 걸어, 동일 기사를 여러 키워드로 중복 수집하더라도
INSERT OR IGNORE 로 자동 중복 제거가 되도록 설계했습니다.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS news_report (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at    TEXT NOT NULL,
    published_at    TEXT,
    category        TEXT NOT NULL,
    company         TEXT NOT NULL,
    title           TEXT NOT NULL,
    summary         TEXT,
    source          TEXT,
    link            TEXT NOT NULL UNIQUE,
    opinion         TEXT,
    target_price    TEXT,
    keywords        TEXT,
    raw_description TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_news_report_company ON news_report(company);
CREATE INDEX IF NOT EXISTS idx_news_report_collected_at ON news_report(collected_at);
CREATE INDEX IF NOT EXISTS idx_news_report_category ON news_report(category);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """DB 파일 및 테이블이 없으면 생성합니다. 스크립트 시작 시 항상 먼저 호출하세요."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def insert_records(records):
    """
    records: dict 리스트. 각 dict는 아래 키를 가질 수 있습니다.
      category, company, title, summary, source, link, opinion,
      target_price, keywords, raw_description, published_at

    link 기준으로 중복이면 자동 무시(INSERT OR IGNORE)됩니다.
    반환값: 실제로 새로 삽입된 건수
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted = 0
    with get_conn() as conn:
        cur = conn.cursor()
        for r in records:
            cur.execute(
                """
                INSERT OR IGNORE INTO news_report
                (collected_at, published_at, category, company, title, summary,
                 source, link, opinion, target_price, keywords, raw_description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    r.get("published_at", now),
                    r.get("category", "뉴스"),
                    r.get("company", "산업전반"),
                    r.get("title", ""),
                    r.get("summary", ""),
                    r.get("source", ""),
                    r.get("link", ""),
                    r.get("opinion", ""),
                    r.get("target_price", ""),
                    r.get("keywords", ""),
                    r.get("raw_description", ""),
                    now,
                ),
            )
            if cur.rowcount > 0:
                inserted += 1
    return inserted


def fetch_today(collected_date=None):
    """오늘(또는 지정 날짜, 'YYYY-MM-DD') 수집된 레코드 전체를 반환합니다."""
    date_str = collected_date or datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM news_report WHERE collected_at LIKE ? ORDER BY collected_at DESC",
            (f"{date_str}%",),
        )
        return [dict(row) for row in cur.fetchall()]


def search(company=None, keyword=None, start_date=None, end_date=None, category=None, limit=200):
    """
    누적 DB 검색.
      company: TARGET_COMPANIES key와 부분일치 (예: '아모레퍼시픽')
      keyword: title/summary/keywords 컬럼에서 부분일치 검색 (예: '북미', '선케어')
      start_date, end_date: 'YYYY-MM-DD' 형식, collected_at 기준 범위
      category: '뉴스' 또는 '리포트'
    """
    query = "SELECT * FROM news_report WHERE 1=1"
    params = []

    if company:
        query += " AND company LIKE ?"
        params.append(f"%{company}%")

    if keyword:
        query += " AND (title LIKE ? OR summary LIKE ? OR keywords LIKE ? OR raw_description LIKE ?)"
        params.extend([f"%{keyword}%"] * 4)

    if category:
        query += " AND category = ?"
        params.append(category)

    if start_date:
        query += " AND collected_at >= ?"
        params.append(f"{start_date} 00:00:00")

    if end_date:
        query += " AND collected_at <= ?"
        params.append(f"{end_date} 23:59:59")

    query += " ORDER BY collected_at DESC LIMIT ?"
    params.append(limit)

    with get_conn() as conn:
        cur = conn.execute(query, params)
        return [dict(row) for row in cur.fetchall()]


def get_existing_links():
    """이미 DB에 있는 link 집합. 요약 API 호출 전 사전 필터링해 비용을 아끼는 데 사용."""
    with get_conn() as conn:
        cur = conn.execute("SELECT link FROM news_report")
        return {row["link"] for row in cur.fetchall()}


if __name__ == "__main__":
    init_db()
    print(f"DB 초기화 완료: {DB_PATH}")
