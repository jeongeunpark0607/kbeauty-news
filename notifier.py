# -*- coding: utf-8 -*-
"""
notifier.py
===========
Slack Incoming Webhook으로 보고서 텍스트를 발송합니다.

Slack 메시지는 40,000자 제한이 있고, 실제로는 가독성을 위해 블록당 3000자 내외로
쪼개 여러 메시지로 나눠 보내는 것을 권장합니다. 여기서는 안전하게 3500자 단위로
분할 발송합니다.
"""
import requests

from config import SLACK_WEBHOOK_URL

CHUNK_SIZE = 3500


def _split_text(text, chunk_size=CHUNK_SIZE):
    """줄바꿈 단위를 보존하면서 chunk_size 이하로 텍스트를 분할.
    개별 줄 자체가 chunk_size보다 긴 경우(예: 줄바꿈 없는 매우 긴 텍스트)에도
    안전하게 강제로 잘라 분할합니다."""
    raw_lines = text.split("\n")
    lines = []
    for line in raw_lines:
        if len(line) <= chunk_size:
            lines.append(line)
        else:
            # 너무 긴 단일 줄은 chunk_size 단위로 강제 절단
            for i in range(0, len(line), chunk_size):
                lines.append(line[i : i + chunk_size])

    chunks = []
    current = []
    current_len = 0
    for line in lines:
        if current_len + len(line) + 1 > chunk_size and current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def send_slack_report(report_text):
    if not SLACK_WEBHOOK_URL:
        raise RuntimeError("SLACK_WEBHOOK_URL 이 설정되지 않았습니다. .env 또는 GitHub Secrets를 확인하세요.")

    chunks = _split_text(report_text)
    for i, chunk in enumerate(chunks):
        resp = requests.post(SLACK_WEBHOOK_URL, json={"text": chunk}, timeout=10)
        if resp.status_code != 200:
            raise RuntimeError(f"Slack 발송 실패 ({i + 1}/{len(chunks)}): {resp.status_code} {resp.text}")
    print(f"[INFO] Slack 발송 완료 ({len(chunks)}개 메시지로 분할)")


# --------------------------------------------------------------------------
# (선택) 이메일(SMTP) 발송을 사용하고 싶다면 아래 함수를 사용하고,
# main_daily.py에서 send_slack_report 대신/함께 호출하세요.
# 필요한 환경변수: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_TO
# (Gmail의 경우 일반 비밀번호가 아닌 '앱 비밀번호'를 사용해야 합니다)
# --------------------------------------------------------------------------
def send_email_report(report_text, subject=None):
    import os
    import smtplib
    from email.mime.text import MIMEText
    from datetime import datetime

    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    mail_to = os.environ.get("MAIL_TO", "")

    if not (user and password and mail_to):
        raise RuntimeError("SMTP_USER / SMTP_PASSWORD / MAIL_TO 환경변수가 필요합니다.")

    subject = subject or f"[K뷰티 데일리 뉴스클리핑] {datetime.now().strftime('%Y-%m-%d')}"

    msg = MIMEText(report_text, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = mail_to

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(user, [mail_to], msg.as_string())

    print("[INFO] 이메일 발송 완료")
