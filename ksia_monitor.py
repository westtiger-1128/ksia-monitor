"""
KSIA 교육 모니터링 스크립트
https://infra.ksia.or.kr 에서 새로운 예비취업자 교육이 올라오면 이메일로 알려줍니다.

설정 방법:
1. 아래 CONFIG 섹션을 본인 정보로 수정하세요.
2. Gmail 앱 비밀번호 발급: https://myaccount.google.com/apppasswords
   (Gmail 2단계 인증이 켜져 있어야 합니다)
3. python ksia_monitor.py 실행 (또는 ksia_monitor_run.bat 더블클릭)
"""

import requests
import json
import os
import smtplib
import hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup
from datetime import datetime

# ===== 설정 =====
CONFIG = {
    "naver_email": os.environ.get("NAVER_EMAIL", "bigel123@naver.com"),
    "naver_password": os.environ.get("NAVER_PASSWORD", "joseoboem5@"),
    "notify_email": os.environ.get("NOTIFY_EMAIL", "joseobeom1128@gmail.com"),
}
# ================

BASE_URL = "https://infra.ksia.or.kr/user/Wo/WoUser0101.do"
URL = BASE_URL + "?SCH_PRM_GB=002&CURRENT_MENU_CODE=MENU0046&TOP_MENU_CODE=MENU0040"
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ksia_known_courses.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": "https://infra.ksia.or.kr/",
}


def fetch_all_courses():
    """모든 페이지를 순회하여 전체 강좌 목록을 가져옵니다."""
    all_courses = []
    page = 1

    while True:
        page_url = BASE_URL + f"?SCH_PRM_GB=002&CURRENT_MENU_CODE=MENU0046&TOP_MENU_CODE=MENU0040&PAGE_INDEX={page}"
        try:
            resp = requests.get(page_url, headers=HEADERS, timeout=20, verify=True)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[오류] 페이지 {page} 로드 실패: {e}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        courses = parse_courses(soup)

        if not courses:
            break

        all_courses.extend(courses)

        # 다음 페이지 존재 여부 확인
        has_next = check_next_page(soup, page)
        if not has_next:
            break
        page += 1

    return all_courses


def parse_courses(soup):
    """HTML에서 강좌 목록을 파싱합니다."""
    courses = []

    # 전체 텍스트에서 과정 목록 ul 찾기 (모집기간/교육기간 포함하는 ul)
    lists = soup.find_all("ul")
    target_ul = None
    for ul in lists:
        text = ul.get_text()
        if "모집기간" in text and "교육기간" in text and len(ul.find_all("li")) >= 3:
            target_ul = ul
            break

    if not target_ul:
        return courses

    for li in target_ul.find_all("li", recursive=False):
        li_text = li.get_text(separator="\n").strip()

        # 모집기간이 없으면 강좌 항목이 아님
        if "모집기간" not in li_text:
            continue

        # 기관명 추출
        org = ""
        for tag in li.find_all(["span", "p", "div", "em", "strong"]):
            t = tag.get_text(strip=True)
            if any(uni in t for uni in ["대학교", "대학", "한국반도체산업협회"]):
                if len(t) < 30:
                    org = t
                    break

        # 교육명 추출 (가장 긴 <a> 텍스트)
        course_name = ""
        for a in li.find_all("a"):
            t = a.get_text(strip=True)
            if t and len(t) > len(course_name) and t not in ["#", ""]:
                course_name = t

        # 텍스트에서 날짜 정보 파싱
        lines = [l.strip() for l in li_text.split("\n") if l.strip()]
        recruit_period = ""
        edu_period = ""
        status = ""
        for i, line in enumerate(lines):
            if "모집기간" in line:
                # 같은 라인이거나 다음 라인에 날짜
                if "~" in line:
                    recruit_period = line.replace("모집기간", "").strip()
                elif i + 1 < len(lines):
                    recruit_period = lines[i + 1].strip()
            if "교육기간" in line:
                if "~" in line:
                    edu_period = line.replace("교육기간", "").strip()
                elif i + 1 < len(lines):
                    edu_period = lines[i + 1].strip()
            if line in ["모집준비", "모집중", "모집마감"]:
                status = line

        if course_name:
            uid = hashlib.md5(f"{course_name}{recruit_period}{edu_period}".encode()).hexdigest()
            courses.append({
                "id": uid,
                "org": org,
                "name": course_name,
                "recruit_period": recruit_period,
                "edu_period": edu_period,
                "status": status,
                "found_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            })

    return courses


def check_next_page(soup, current_page):
    """다음 페이지가 있는지 확인합니다."""
    # 페이징 영역에서만 다음 페이지 링크 검색
    paging_area = soup.find(class_=lambda c: c and any(x in c for x in ["paging", "pagination", "page"]))
    if paging_area:
        links = paging_area.find_all("a", string=str(current_page + 1))
        return len(links) > 0
    # 페이징 영역이 없으면 단일 페이지로 간주
    return False


def load_known_courses():
    """저장된 강좌 목록을 불러옵니다."""
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_known_courses(courses_dict):
    """강좌 목록을 저장합니다."""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(courses_dict, f, ensure_ascii=False, indent=2)


def send_email(new_courses):
    """새로운 강좌를 이메일로 발송합니다."""
    subject = f"[KSIA] 새로운 교육 {len(new_courses)}개 업데이트!"

    # HTML 이메일 본문 작성
    rows = ""
    for c in new_courses:
        status_color = {
            "모집중": "#2ecc71",
            "모집준비": "#f39c12",
            "모집마감": "#e74c3c",
        }.get(c["status"], "#95a5a6")

        rows += f"""
        <tr>
          <td style="padding:12px;border-bottom:1px solid #eee;color:#555;">{c['org']}</td>
          <td style="padding:12px;border-bottom:1px solid #eee;font-weight:bold;">
            <a href="{URL}" style="color:#2c3e50;text-decoration:none;">{c['name']}</a>
          </td>
          <td style="padding:12px;border-bottom:1px solid #eee;color:#555;">{c['recruit_period']}</td>
          <td style="padding:12px;border-bottom:1px solid #eee;color:#555;">{c['edu_period']}</td>
          <td style="padding:12px;border-bottom:1px solid #eee;">
            <span style="background:{status_color};color:white;padding:3px 8px;border-radius:4px;font-size:13px;">{c['status']}</span>
          </td>
        </tr>"""

    html_body = f"""
    <html><body style="font-family:Apple SD Gothic Neo,맑은 고딕,sans-serif;color:#2c3e50;margin:0;padding:0;">
      <div style="max-width:700px;margin:20px auto;background:#fff;border:1px solid #ddd;border-radius:8px;overflow:hidden;">
        <div style="background:#1a252f;padding:20px 30px;">
          <h2 style="color:#fff;margin:0;font-size:20px;">🔔 KSIA 새로운 교육 업데이트</h2>
          <p style="color:#bdc3c7;margin:5px 0 0;">반도체인프라활용현장인력양성 &nbsp;|&nbsp; 예비취업자 교육</p>
        </div>
        <div style="padding:20px 30px;">
          <p style="margin-top:0;">새로운 교육 과정 <strong>{len(new_courses)}개</strong>가 등록되었습니다.</p>
          <table style="width:100%;border-collapse:collapse;font-size:14px;">
            <thead>
              <tr style="background:#f8f9fa;">
                <th style="padding:10px 12px;text-align:left;color:#888;font-weight:normal;border-bottom:2px solid #eee;">기관</th>
                <th style="padding:10px 12px;text-align:left;color:#888;font-weight:normal;border-bottom:2px solid #eee;">교육명</th>
                <th style="padding:10px 12px;text-align:left;color:#888;font-weight:normal;border-bottom:2px solid #eee;">모집기간</th>
                <th style="padding:10px 12px;text-align:left;color:#888;font-weight:normal;border-bottom:2px solid #eee;">교육기간</th>
                <th style="padding:10px 12px;text-align:left;color:#888;font-weight:normal;border-bottom:2px solid #eee;">상태</th>
              </tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
          <div style="margin-top:20px;text-align:center;">
            <a href="{URL}" style="background:#1a252f;color:#fff;padding:10px 24px;border-radius:6px;text-decoration:none;font-size:14px;">
              사이트에서 확인하기 →
            </a>
          </div>
        </div>
        <div style="background:#f8f9fa;padding:12px 30px;font-size:12px;color:#aaa;">
          이 메일은 KSIA 교육 모니터링 스크립트가 자동 발송했습니다. ({datetime.now().strftime("%Y-%m-%d %H:%M")})
        </div>
      </div>
    </body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = CONFIG["naver_email"]
    msg["To"] = CONFIG["notify_email"]
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.naver.com", 465) as server:
            server.login(CONFIG["naver_email"], CONFIG["naver_password"])
            server.send_message(msg)
        print(f"[완료] 이메일 발송 성공: {CONFIG['notify_email']}")
    except Exception as e:
        print(f"[오류] 이메일 발송 실패: {e}")


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] KSIA 교육 모니터링 시작...")

    # 현재 강좌 목록 수집
    current_courses = fetch_all_courses()
    print(f"  → 현재 강좌 {len(current_courses)}개 확인")

    if not current_courses:
        print("  [경고] 강좌를 가져오지 못했습니다. 네트워크 연결을 확인하세요.")
        return

    # 저장된 목록과 비교
    known = load_known_courses()
    new_courses = [c for c in current_courses if c["id"] not in known]

    if new_courses:
        print(f"  → 새로운 교육 {len(new_courses)}개 발견!")
        for c in new_courses:
            print(f"     - [{c['org']}] {c['name']} ({c['status']})")
        send_email(new_courses)
    else:
        print("  → 새로운 교육 없음.")

    # 현재 목록 저장 (기존 known과 병합 - IP 차단으로 일부만 수집돼도 기존 데이터 유지)
    updated = dict(known)  # 기존 known 유지
    for c in current_courses:
        updated[c["id"]] = c  # 새로 발견된 강좌 추가/갱신
    save_known_courses(updated)

    print("  완료.\n")


if __name__ == "__main__":
    main()
