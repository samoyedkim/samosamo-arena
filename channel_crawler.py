import streamlit as st
import yt_dlp
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# =======================================================
# [설정] 3개 채널 맞춤형 타겟 프로필 (다중 키워드 지원)
# =======================================================
TARGET_CHANNELS = [
    {
        "name": "KBS 경제쇼",
        "url": "https://www.youtube.com/playlist?list=PLFnESzVU01TG3D5Gj2yrv21vkLiHS7If8",
        "min_minutes": 10,
        "keyword": "풀영상", # 단일 키워드도 당연히 OK!
        "max_videos": 100
    },
    {
        "name": "삼프로TV",
        "url": "https://www.youtube.com/@3protv/videos",
        "min_minutes": 10,
        "keyword": "시황",
        "max_videos": 100
    },
    {
        "name": "매일경제",
        "url": "https://www.youtube.com/@MKeconomy_TV/videos",
        "min_minutes": 100,
        # 💡 [패치] 여러 개의 키워드를 찾고 싶을 때는 이렇게 대괄호 [] 로 묶어주세요!
        "keyword": ["투자의 눈", "정철진", "일발장전"], 
        "max_videos": 50
    }
]

SHEET_NAME = "SAMOSAMO_List"

def get_existing_urls():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    
    # 💡 [핵심 패치] 하이브리드 인증 로직
    try:
        # 1. 클라우드(Streamlit) 환경: st.secrets 금고에서 열쇠를 꺼냅니다.
        if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            print("☁️ 클라우드 금고(Secrets)에서 구글 시트 인증 완료!")
        # 2. 로컬(PC) 환경: 기존처럼 물리적인 json 파일을 읽습니다.
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name('service_account.json', scope)
            print("💻 로컬 파일(json)에서 구글 시트 인증 완료!")
            
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME).sheet1
        
        urls_col = sheet.col_values(1)
        existing_urls = urls_col[1:] if len(urls_col) > 1 else []
        return sheet, existing_urls
        
    except Exception as e:
        raise Exception(f"인증 로직 에러: {e}")

def run_crawler_for_arena():
    """아레나에서 버튼을 눌렀을 때 실행될 메인 자동화 함수"""
    print("▶️ 구글 시트 접속 중...")
    try:
        sheet, existing_urls = get_existing_urls()
    except Exception as e:
        return f"❌ 시트 접속 실패: {e}"

    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
        'no_warnings': True,
    }

    total_added = 0
    report_lines = []

    print("▶️ 3개 채널 탐색 시작...")
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for ch_info in TARGET_CHANNELS:
            ch_name = ch_info["name"]
            ch_url = ch_info["url"]
            min_sec = ch_info["min_minutes"] * 60
            keyword = ch_info["keyword"]
            limit = ch_info["max_videos"]
            
            print(f"\n🔎 [{ch_name}] 채널 탐색 중... (조건: {ch_info['min_minutes']}분 이상)")
            report_lines.append(f"✅ **{ch_name}** 검사 완료")
            
            try:
                result = ydl.extract_info(ch_url, download=False)
            except Exception as e:
                print(f"   ⚠️ 채널 접근 실패: {e}")
                report_lines.append(f"   - ⚠️ 접근 실패")
                continue

            if 'entries' not in result: continue

            ch_added = 0
            for i, video in enumerate(result['entries']):
                if i >= limit: break 
                
                title = video.get('title', 'Unknown')
                url = video.get('url', '')
                duration = video.get('duration', 0)

                if "youtube.com" not in url:
                    url = f"https://www.youtube.com/watch?v={video.get('id')}"

                # 💡 [패치] 다중 키워드(리스트) 필터링 로직
                if duration and duration < min_sec: continue
                
                if keyword:
                    if isinstance(keyword, list):
                        # 리스트 안의 키워드 중 하나라도 제목에 없으면 패스 (있으면 통과)
                        if not any(k in title for k in keyword):
                            continue
                    else:
                        # 단일 키워드일 경우
                        if keyword not in title:
                            continue

                if url in existing_urls: continue

                # 조건 통과 -> 시트 추가
                print(f"   ➕ 추가됨: [{ch_name}] {title}")
                sheet.append_row([url, "", f"자동수집: [{ch_name}] {title}"])
                existing_urls.append(url) 
                ch_added += 1
                total_added += 1
                report_lines.append(f"   - 📥 추가: {title[:20]}...")

            if ch_added == 0:
                report_lines.append("   - 새로운 영상 없음")

    final_report = "\n".join(report_lines)
    print(f"\n✨ 총 {total_added}개의 영상 추가 완료!")
    return f"총 {total_added}건 추가 완료!\n\n{final_report}"

if __name__ == "__main__":
    run_crawler_for_arena()
