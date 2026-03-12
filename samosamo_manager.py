import warnings
warnings.filterwarnings("ignore") 

import os
import time
import glob
import re
import yt_dlp
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai
import streamlit as st

# ⚠️ 파트너님의 식권 뭉치(API 키)
MY_API_KEYS = [
    "AIzaSyD-7GcSsOABxCk6pxK4ecG_NNmkdKMrhaM",
    "AIzaSyCm0NaC_ogdhWPBWRGFimbAXXHyxvrHtfw"
]
SHEET_NAME = "SAMOSAMO_List"
MODEL_CANDIDATES = ['gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-3-flash', 'gemma-3-27b-it', 'gemma-3-12b-it']

def connect_to_sheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        # 💡 [핵심 패치] 하이브리드 인증 로직
        # 1. 클라우드(Streamlit) 환경: st.secrets 금고에서 열쇠를 꺼냅니다.
        if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        # 2. 로컬(PC) 환경: 기존처럼 물리적인 json 파일을 읽습니다.
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name('service_account.json', scope)
            
        client = gspread.authorize(creds)
        return client.open(SHEET_NAME).sheet1
    except Exception as e:
        print(f"구글 시트 인증 실패: {e}")
        return None

def sanitize_filename(title):
    return re.sub(r'[\\/*?:"<>|]', "", title)

def get_video_data(video_url):
    for f in glob.glob("temp_*"): 
        try: os.remove(f)
        except: pass

    title = "Unknown_Video"
    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            title = ydl.extract_info(video_url, download=False).get('title', 'Unknown_Video')
    except: pass

    sub_opts = {'skip_download': True, 'writesubtitles': True, 'writeautomaticsub': True, 'subtitleslangs': ['ko'], 'outtmpl': 'temp_sub', 'quiet': True}
    try:
        with yt_dlp.YoutubeDL(sub_opts) as ydl: ydl.download([video_url])
        vtt_files = glob.glob("*.vtt")
        if vtt_files:
            with open(vtt_files[0], 'r', encoding='utf-8') as f: content = f.read()
            for f in vtt_files: os.remove(f)
            return title, content, "text"
    except: pass

    audio_opts = {'format': 'bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}], 'outtmpl': 'temp_audio.%(ext)s', 'quiet': True}
    try:
        with yt_dlp.YoutubeDL(audio_opts) as ydl: ydl.download([video_url])
        return title, "temp_audio.mp3", "audio"
    except:
        return None, None, None

def analyze_content_smart(content, mode):
    base_prompt = "너는 방송 작가야. [MM:SS] 형식으로 요약 없이 완벽한 대본을 작성해."
    for key_idx, api_key in enumerate(MY_API_KEYS):
        genai.configure(api_key=api_key)
        for model_name in MODEL_CANDIDATES:
            model = genai.GenerativeModel(model_name)
            for attempt in range(3):
                try:
                    if mode == "text":
                        return model.generate_content(f"{base_prompt}\n\n[자막 데이터]\n{content}").text
                    elif mode == "audio":
                        if not os.path.exists(content): return "ERROR: 오디오 없음"
                        audio_file = genai.upload_file(content, mime_type="audio/mp3")
                        while audio_file.state.name == "PROCESSING":
                            time.sleep(2)
                            audio_file = genai.get_file(audio_file.name)
                        return model.generate_content([base_prompt, audio_file]).text
                except Exception as e:
                    error_msg = str(e)
                    if any(err in error_msg for err in ["429", "ResourceExhausted", "limit: 0", "404", "NotFound"]): break
                    elif any(err in error_msg for err in ["500", "InternalServerError"]): time.sleep((attempt + 1) * 5)
                    else: break
        time.sleep(1) 
    return "ERROR: 전멸"

def run_manager_for_arena():
    """💡 아레나 UI에 실시간 중계를 쏴주는 제너레이터 함수"""
    sheet = connect_to_sheet()
    if not sheet:
        yield "❌ 구글 시트 연결 실패"
        return
        
    records = sheet.get_all_values()
    yield f"ℹ️ 구글 시트 연결 완료. (총 {len(records)-1}개 대기열 확인)"
    
    success_count = 0
    for i, row in enumerate(records[1:], start=2):
        url = row[0]
        status = row[1] if len(row) > 1 else ""
        
        if url and status != "완료":
            yield f"▶️ {i}행 작업 시작: {url}"
            title, content, mode = get_video_data(url)
            
            if title and content:
                yield f"   🔄 [{title[:15]}...] 대본 추출 중 (API 가동)"
                result_text = analyze_content_smart(content, mode)
                
                if result_text.startswith("ERROR"):
                    yield f"   ❌ 추출 실패: {result_text}"
                    sheet.update_cell(i, 2, "실패")
                    if "전멸" in result_text:
                        yield "🛑 API 한도 초과. 작업을 중단합니다."
                        break
                else:
                    filename = f"{sanitize_filename(title)}.txt"
                    try:
                        with open(filename, "w", encoding="utf-8") as f: f.write(result_text)
                        sheet.update_cell(i, 2, "완료")
                        sheet.update_cell(i, 3, filename)
                        yield f"   ✅ 저장 완료: {filename}"
                        success_count += 1
                    except Exception as e:
                        yield f"   ❌ 파일 저장 실패: {str(e)}"
                
                if mode == "audio" and os.path.exists(content):
                    try: os.remove(content)
                    except: pass
            else:
                yield "   ❌ 다운로드 실패"
                
    yield f"✨ 대본 추출 작업 완료! (총 {success_count}건 성공)"

if __name__ == "__main__":
    for msg in run_manager_for_arena():
        print(msg)
