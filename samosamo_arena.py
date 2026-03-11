import os
import json
import time
import asyncio
import datetime
import requests
import html
import random
import re
from bs4 import BeautifulSoup
import streamlit as st
import chromadb
from sentence_transformers import SentenceTransformer
from google import genai
from openai import AsyncOpenAI, OpenAI
from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import FinanceDataReader as fdr

import channel_crawler
import samosamo_manager
import samosamo_indexer

# ==========================================
# 0. UI 및 환경 변수 세팅
# ==========================================
st.set_page_config(page_title="SAMOSAMO Colosseum", page_icon="🏛️", layout="wide")

load_dotenv(override=True)
GEMINI_API_KEY_1 = os.getenv("GEMINI_API_KEY_1")
GEMINI_API_KEY_2 = os.getenv("GEMINI_API_KEY_2")
GEMINI_API_KEY_3 = os.getenv("GEMINI_API_KEY_3")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

SCRIBE_FILE = "samosamo_scribe.json"
MACRO_FILE = "alfredo_macros.json"

# ==========================================
# 1. 엔진, 도서관 & 💡[통합 티커 사전] 로드
# ==========================================
@st.cache_resource
def load_engines():
    embedder = SentenceTransformer('BAAI/bge-m3')
    chroma_client = chromadb.PersistentClient(path="./samosamo_db")
    collection = chroma_client.get_or_create_collection(name="samosamo_rag")
    gemini_kbs = genai.Client(api_key=GEMINI_API_KEY_1) if GEMINI_API_KEY_1 else None
    gemini_maeil = genai.Client(api_key=GEMINI_API_KEY_2) if GEMINI_API_KEY_2 else None
    gemini_sampro = genai.Client(api_key=GEMINI_API_KEY_3) if GEMINI_API_KEY_3 else None
    async_openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    sync_openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return embedder, collection, gemini_kbs, gemini_maeil, gemini_sampro, async_openai_client, sync_openai_client

embedder, collection, gemini_kbs, gemini_maeil, gemini_sampro, async_openai_client, sync_openai_client = load_engines()

@st.cache_data
def get_krx_ticker_map():
    try:
        # 일반 주식(KRX)과 ETF 목록을 모두 가져와서 하나의 거대한 사전으로 병합합니다.
        df_krx = fdr.StockListing('KRX')
        df_etf = fdr.StockListing('ETF/KR')
        ticker_map = dict(zip(df_krx['Name'], df_krx['Code']))
        ticker_map.update(dict(zip(df_etf['Name'], df_etf['Symbol']))) 
        return ticker_map
    except:
        return {}

PANELS = {
    "KBS_Gemini": {"name": "KBS 경제쇼", "tag": "KBS", "ai": "Gemini", "client": gemini_kbs},
    "KBS_GPT": {"name": "KBS 경제쇼", "tag": "KBS", "ai": "GPT", "client": async_openai_client},
    "Maeil_Gemini": {"name": "매일경제", "tag": "Maeil", "ai": "Gemini", "client": gemini_maeil},
    "Maeil_GPT": {"name": "매일경제", "tag": "Maeil", "ai": "GPT", "client": async_openai_client},
    "Sampro_Gemini": {"name": "삼프로TV", "tag": "Sampro", "ai": "Gemini", "client": gemini_sampro},
    "Sampro_GPT": {"name": "삼프로TV", "tag": "Sampro", "ai": "GPT", "client": async_openai_client}
}

# ==========================================
# 2. 세션 상태 및 즐겨찾기 관리
# ==========================================
if "chat_history" not in st.session_state: st.session_state.chat_history = []  
if "topic" not in st.session_state: st.session_state.topic = ""
if "spoken_panels" not in st.session_state: st.session_state.spoken_panels = set() 
if "shared_news_full_texts" not in st.session_state: st.session_state.shared_news_full_texts = "" 

def load_macros():
    if not os.path.exists(MACRO_FILE):
        default_macros = {"주달 외국인": "https://www.judal.co.kr/?view=stockList&type=foreignerBuy"}
        with open(MACRO_FILE, "w", encoding="utf-8") as f:
            json.dump(default_macros, f, ensure_ascii=False, indent=2)
        return default_macros
    with open(MACRO_FILE, "r", encoding="utf-8") as f: return json.load(f)

if "macros" not in st.session_state: st.session_state.macros = load_macros()

def save_macros():
    with open(MACRO_FILE, "w", encoding="utf-8") as f:
        json.dump(st.session_state.macros, f, ensure_ascii=False, indent=2)

# ==========================================
# 3. 사이드바 UI & 💡[모바일 SOS 기능]
# ==========================================
with st.sidebar:
    # --- 모바일 원클릭 에러 리포트 ---
    st.header("🐞 제레에게 SOS 치기")
    st.markdown("오류 발생 시 아래 박스의 우측 상단 **복사 아이콘**을 눌러 제레에게 전달해주세요.")
    
    if st.session_state.chat_history:
        sos_log = "🚨 [모바일 테스트 SOS 리포트]\n\n"
        for msg in st.session_state.chat_history[-4:]: # 최근 4개 대화 추출
            sos_log += f"[{msg['name']}]\n{msg['content']}\n\n"
        st.code(sos_log, language="text") # 스트림릿이 자동으로 복사 버튼을 생성해 줍니다!
    else:
        st.info("아직 대화 기록이 없습니다.")
        
    st.divider()

    st.header("🔗 알프레도 즐겨찾기")
    with st.expander("➕ 새 단축어 추가", expanded=False):
        new_macro_name = st.text_input("단축어 (예: 주달 외국인)")
        new_macro_url = st.text_input("연결할 URL (https://...)")
        if st.button("저장", use_container_width=True) and new_macro_name and new_macro_url:
            st.session_state.macros[new_macro_name] = new_macro_url
            save_macros()
            st.success(f"'{new_macro_name}' 등록 완료!")
            st.rerun()

    for key, url in list(st.session_state.macros.items()):
        colA, colB = st.columns([4, 1])
        with colA: st.markdown(f"🏷️ **{key}**\n*(...{url[-20:]})*")
        with colB:
            if st.button("❌", key=f"del_{key}"):
                del st.session_state.macros[key]; save_macros(); st.rerun()
    
    st.divider()
    st.header("🛠️ 도서관 업데이트")
    if st.button("🚀 원클릭 파이프라인 가동", type="primary", use_container_width=True):
        with st.status("도서관 업데이트 가동 중...", expanded=True) as status:
            st.write("**[1단계] 스크래핑**"); st.code(channel_crawler.run_crawler_for_arena())
            st.write("**[2단계] 대본 추출**"); [st.write(m) for m in samosamo_manager.run_manager_for_arena()]
            st.write("**[3단계] DB 입고**"); [st.write(m) for m in samosamo_indexer.run_indexer_for_arena()]
            status.update(label="도서관 업데이트 완료!", state="complete", expanded=False)

# ==========================================
# 4. 알프레도 4대 금융 무기 + 기본 도구
# ==========================================
def tool_get_market_index():
    try:
        res = requests.get("https://finance.naver.com/", headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        return json.dumps({
            "KOSPI": soup.select_one('.kospi_area .num').text if soup.select_one('.kospi_area .num') else "N/A",
            "KOSDAQ": soup.select_one('.kosdaq_area .num').text if soup.select_one('.kosdaq_area .num') else "N/A",
            "USD/KRW 환율": soup.select_one('.market1 .value').text if soup.select_one('.market1 .value') else "N/A"
        }, ensure_ascii=False)
    except Exception as e: return json.dumps({"error": f"시황 조회 실패: {str(e)}"})

def tool_get_market_ranking(rank_type="volume", top_n=10):
    try:
        urls = {
            "volume": "https://finance.naver.com/sise/sise_quant.naver",
            "foreign": "https://finance.naver.com/sise/sise_foreign_up.naver",
            "rise": "https://finance.naver.com/sise/sise_rise.naver",
            "fall": "https://finance.naver.com/sise/sise_fall.naver",
            "etf_volume": "https://finance.naver.com/sise/etf.naver"
        }
        res = requests.get(urls.get(rank_type, urls["volume"]), headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        table = soup.find('table', {'class': 'type_2'})
        result = []
        
        # 💡 [핵심 패치] ETF 페이지의 표 구조에 맞게 a 태그(링크) 안의 텍스트만 쏙 빼옵니다.
        for r in table.find_all('tr'):
            a_tag = r.find('a')
            if a_tag and r.find('td', class_='num'): 
                result.append({"종목명": a_tag.text.strip()})
            if len(result) >= top_n: break
            
        return json.dumps({"rank_type": rank_type, "data": result}, ensure_ascii=False)
    except Exception as e: return json.dumps({"error": f"랭킹 조회 실패: {str(e)}"})

def tool_get_company_finance(name):
    try:
        krx_map = get_krx_ticker_map()
        ticker = krx_map.get(name)
        if not ticker: return json.dumps({"error": f"'{name}'의 종목코드를 찾지 못했습니다."})
        res = requests.get(f"https://finance.naver.com/item/main.naver?code={ticker}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        return json.dumps({
            "종목명": name, "티커": ticker,
            "시가총액": soup.select_one('#_market_sum').text.strip() + "억원" if soup.select_one('#_market_sum') else "N/A",
            "PER": soup.select_one('#_per').text.strip() if soup.select_one('#_per') else "N/A",
            "PBR": soup.select_one('#_pbr').text.strip() if soup.select_one('#_pbr') else "N/A",
            "배당수익률": soup.select_one('#_dvr').text.strip() + "%" if soup.select_one('#_dvr') else "N/A"
        }, ensure_ascii=False)
    except Exception as e: return json.dumps({"error": f"재무 조회 실패: {str(e)}"})

def tool_get_historical_data(names, start_date, end_date):
    try:
        krx_map = get_krx_ticker_map()
        results = {}
        for name in names:
            ticker = krx_map.get(name, name) 
            try:
                df = fdr.DataReader(ticker, start_date, end_date)
                if df.empty: results[name] = "데이터 없음"
                else: results[name] = {k.strftime('%Y-%m-%d'): int(v) for k, v in df['Close'].to_dict().items()}
            except: results[name] = "조회 실패"
        return json.dumps({"start_date": start_date, "end_date": end_date, "data": results}, ensure_ascii=False)
    except Exception as e: return json.dumps({"error": f"과거 주가 조회 실패: {str(e)}"})

def tool_read_website(url):
    try:
        if not url.startswith("http"): url = "https://" + url
        options = Options()
        options.add_argument('--headless'); options.add_argument('--disable-gpu'); options.add_argument('--no-sandbox')
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.get(url)
        time.sleep(3) 
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        driver.quit() 
        for s in soup(["script", "style", "nav", "footer"]): s.extract()
        clean_text = re.sub(r'\s+', ' ', soup.get_text(separator=' ', strip=True))
        return json.dumps({"url": url, "content": clean_text[:15000]}, ensure_ascii=False) if len(clean_text) > 50 else json.dumps({"error": "본문 텍스트 없음."})
    except Exception as e: return json.dumps({"error": f"접속 실패: {str(e)}"})

def tool_search_news(query, count=5):
    try:
        res = requests.get("https://openapi.naver.com/v1/search/news.json", headers={"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}, params={"query": query, "display": max(1, min(int(count), 5)), "sort": "date"}, timeout=5)
        news_list, scraped = [], []
        for r in res.json().get('items', []):
            title, desc, real_link = BeautifulSoup(html.unescape(r['title']), "html.parser").get_text(), BeautifulSoup(html.unescape(r['description']), "html.parser").get_text(), r.get('link') or r.get('originallink')
            full_text = desc 
            try:
                soup = BeautifulSoup(requests.get(real_link, headers={'User-Agent': 'Mozilla/5.0'}, timeout=2).text, 'html.parser')
                b = soup.select_one('#dic_area, #newsct_article, #articleBodyContents')
                clean_scraped = re.sub(r'\s+', ' ', b.get_text(separator=' ', strip=True) if b else " ".join([p.get_text(strip=True) for p in soup.find_all('p') if len(p.get_text(strip=True)) > 30]))
                if len(clean_scraped) > 50: full_text = clean_scraped[:2500] 
            except: pass
            news_list.append({"title": title, "url": real_link, "full_text_chunk": full_text})
            scraped.append(f"▶ [{title}]\n{full_text}")
        st.session_state.shared_news_full_texts = "\n\n".join(scraped)
        return json.dumps({"keyword": query, "news": news_list}, ensure_ascii=False)
    except: return json.dumps({"error": "뉴스 검색 실패"})

tools_schema = [
    {"type": "function", "function": {"name": "get_market_index", "description": "국내 주요 증시 지수(코스피, 코스닥)와 환율을 가져옵니다.", "parameters": { "type": "object", "properties": {} }}},
    {"type": "function", "function": {"name": "get_market_ranking", "description": "조건에 맞는 종목 랭킹을 가져옵니다.", "parameters": {"type": "object", "properties": {"rank_type": {"type": "string", "enum": ["volume", "foreign", "rise", "fall", "etf_volume"], "description": "순위 종류 (volume: 코스피거래량, foreign: 코스피외국인, rise: 코스피상승, fall: 코스피하락, etf_volume: ETF거래량)"}, "top_n": {"type": "integer", "description": "상위 개수"}}, "required": ["rank_type"]}}},
    {"type": "function", "function": {"name": "get_company_finance", "description": "특정 종목의 시가총액, PER, PBR 등 재무 정보를 가져옵니다.", "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "종목명"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "get_historical_data", "description": "여러 종목의 특정 기간 동안의 일일 주가(종가) 변동을 가져옵니다.", "parameters": {"type": "object", "properties": {"names": {"type": "array", "items": {"type": "string"}, "description": "종목명 목록"}, "start_date": {"type": "string", "description": "시작일 (YYYY-MM-DD)"}, "end_date": {"type": "string", "description": "종료일 (YYYY-MM-DD)"}}, "required": ["names", "start_date", "end_date"]}}},
    {"type": "function", "function": {"name": "search_news", "description": "최신 뉴스를 검색합니다.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "count": {"type": "integer"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "read_website", "description": "웹사이트 접속 도구.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}}
]

# ==========================================
# 5. 패널 난타전 엔진
# ==========================================
def sync_generate_gemini(client, prompt):
    if not client: return "Gemini API 키 오류"
    return client.models.generate_content(model="gemini-2.5-flash", contents=prompt, config={"temperature": 0.7}).text

async def generate_openai(client, prompt):
    return (await client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], temperature=0.7)).choices[0].message.content

async def compete_for_turn(panel_id, panel_info, topic, query_embedding, history_text):
    start_time = time.time()
    try:
        results = await asyncio.to_thread(collection.query, query_embeddings=[query_embedding], n_results=2, where={"source": panel_info["tag"]})
        context_text = "\n".join(results['documents'][0]) if results['documents'] else "도서관 기록 없음"
        shared_news = st.session_state.shared_news_full_texts[:12000] 
        prompt = f"너는 '{panel_info['name']}' 패널이다. (AI: {panel_info['ai']})\n[절대 규칙]\n1. 모든 판단은 오직 아래 <도서관 검색 팩트>에서 나온다.\n2. 뉴스는 철저히 너의 팩트 안경을 끼고 재해석해라.\n3. '논리 비판' -> '내 주장' -> '결론' 순서로 말하되 태그 노출 금지.\n4. 400자 이내로 묵직하게 끝내라.\n\n<수집 기사>\n{shared_news}\n<도서관 팩트>\n{context_text}\n<토론 기록>\n{history_text}\n주제: {topic}"
        if panel_info["ai"] == "Gemini": answer = await asyncio.to_thread(sync_generate_gemini, panel_info["client"], prompt)
        else: answer = await generate_openai(panel_info["client"], prompt)
        return panel_id, panel_info, answer, time.time() - start_time, context_text
    except Exception as e: return panel_id, panel_info, f"앗, 마이크 고장! ({str(e)})", time.time() - start_time, ""

# ==========================================
# 6. 메인 화면 UI 및 타겟 라우팅
# ==========================================
st.title("🏛️ SAMOSAMO AI 콜로세움 V5.8 (모바일 최적화)")

for chat in st.session_state.chat_history:
    with st.chat_message(chat["role"], avatar=chat.get("avatar", "🗣️")):
        st.markdown(f"**{chat['name']}**")
        st.write(chat["content"])
st.divider()

col1, col2 = st.columns([3, 1])
with col1:
    target_mode = st.radio("📝 메시지 수신자 선택", ["🤵 비서 알프레도에게 지시", "🗣️ 토론 패널에게 주제 던지기"], horizontal=True)
    master_input = st.chat_input("질문이나 토론 주제를 입력하세요...")

if master_input:
    st.session_state.topic = master_input
    st.session_state.chat_history.append({"role": "user", "name": "👑 마스터", "content": master_input, "avatar": "👑"})
    
    if target_mode == "🤵 비서 알프레도에게 지시":
        with st.chat_message("assistant", avatar="🤵"):
            st.markdown("**🤵 알프레도 (수석 비서)**")
            
            macro_instructions = "\n".join([f"- 마스터가 '{key}' 언급 시 반드시 URL '{url}' 에 접속해라." for key, url in st.session_state.macros.items()])
            today_str = datetime.date.today().strftime("%Y-%m-%d")
            
            system_prompt = f"""너는 마스터를 보좌하는 최고급 AI 금융 비서 알프레도야. (오늘 날짜: {today_str})
[알프레도 행동 매뉴얼]
{macro_instructions}

[🔥 2단계 연계 작업(Tool Chaining) 및 데이터 포맷팅 절대 원칙 🔥]
1. 도구 연계(Chaining) 필수: 마스터가 "거래량 상위 N개의 과거 주가 변동을 표로 만들어라"처럼 랭킹과 과거 데이터를 동시에 요구하면, 절대 한 번에 끝내려 하지 마라.
   - [1단계] `get_market_ranking` 도구를 호출하여 정확한 종목명 N개를 먼저 확보한다. (ETF 조건 시 반드시 etf_volume 사용)
   - [2단계] 확보한 종목명 리스트를 그대로 `get_historical_data` 도구에 넣어 과거 주가 데이터를 조회한다. (날짜는 오늘 날짜인 {today_str}를 기준으로 정확히 계산)
2. 수량 절대 준수: 20개를 요구하면 20개를 반드시 끝까지 채워라.
3. 완벽한 마크다운 표(Markdown Table): 최종 답변은 반드시 행과 열이 정렬된 깔끔한 마크다운 표 형식으로 작성해라.
"""
            history_text = "\n".join([f"[{c['name']}] {c['content']}" for c in st.session_state.chat_history[-6:]])
            combined_input = f"<최근 대화 맥락>\n{history_text}\n\n<마스터의 새로운 지시>\n{master_input}"
            
            messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": combined_input}]
            
            with st.spinner("알프레도가 마스터의 지시를 분석하여 다중 파이프라인을 가동 중입니다..."):
                response = sync_openai_client.chat.completions.create(model="gpt-4o-mini", messages=messages, tools=tools_schema, tool_choice="auto", temperature=0.0) 
                
                response_msg = response.choices[0].message
                if response_msg.tool_calls:
                    messages.append(response_msg)
                    for tool_call in response_msg.tool_calls:
                        args = json.loads(tool_call.function.arguments)
                        fn_name = tool_call.function.name
                        
                        if fn_name == "get_market_index": tool_result = tool_get_market_index()
                        elif fn_name == "get_market_ranking": tool_result = tool_get_market_ranking(args.get("rank_type", "volume"), args.get("top_n", 10))
                        elif fn_name == "get_company_finance": tool_result = tool_get_company_finance(args["name"])
                        elif fn_name == "get_historical_data": tool_result = tool_get_historical_data(args["names"], args["start_date"], args["end_date"])
                        elif fn_name == "search_news": tool_result = tool_search_news(args["query"], args.get("count", 5))
                        elif fn_name == "read_website": tool_result = tool_read_website(args["url"])
                            
                        messages.append({"tool_call_id": tool_call.id, "role": "tool", "name": fn_name, "content": tool_result})
                    
                    second_response = sync_openai_client.chat.completions.create(model="gpt-4o-mini", messages=messages, tools=tools_schema, temperature=0.0)
                    
                    if second_response.choices[0].message.tool_calls:
                         messages.append(second_response.choices[0].message)
                         for tool_call in second_response.choices[0].message.tool_calls:
                            args = json.loads(tool_call.function.arguments)
                            fn_name = tool_call.function.name
                            if fn_name == "get_historical_data": tool_result = tool_get_historical_data(args["names"], args["start_date"], args["end_date"])
                            messages.append({"tool_call_id": tool_call.id, "role": "tool", "name": fn_name, "content": tool_result})
                         final_response = sync_openai_client.chat.completions.create(model="gpt-4o-mini", messages=messages, temperature=0.0)
                         final_answer = final_response.choices[0].message.content
                    else:
                         final_answer = second_response.choices[0].message.content
                else: final_answer = response_msg.content
                
                st.write(final_answer)
                st.session_state.chat_history.append({"role": "assistant", "name": "🤵 알프레도", "content": final_answer, "avatar": "🤵"})

    elif target_mode == "🗣️ 토론 패널에게 주제 던지기":
        eligible = list(set(PANELS.keys()) - st.session_state.spoken_panels)
        if not eligible:
            st.session_state.spoken_panels = set()
            eligible = list(PANELS.keys())
            
        selected_pid = random.choice(eligible)
        history_text = "\n".join([f"[{c['name']}] {c['content']}" for c in st.session_state.chat_history[-4:]])
        query_embedding = embedder.encode([st.session_state.topic], show_progress_bar=False)[0].tolist()
        
        with st.spinner(f"🎙️ {PANELS[selected_pid]['name']}({PANELS[selected_pid]['ai']}) 패널이 발언 준비 중..."):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            pid, p_info, answer, elapsed, context = loop.run_until_complete(compete_for_turn(selected_pid, PANELS[selected_pid], st.session_state.topic, query_embedding, history_text))
            st.session_state.spoken_panels.add(pid)
            st.session_state.chat_history.append({"role": "assistant", "name": f"📺 {p_info['name']} ({p_info['ai']}) - ⏱️ {elapsed:.1f}초", "content": answer, "avatar": "📺"})
    st.rerun()

# --- 토론 진행 버튼 ---
if st.session_state.chat_history:
    st.markdown("### 🎮 토론 컨트롤")
    b_col1, b_col2, b_col3 = st.columns(3)
    with b_col1:
        if st.button("▶️ 다음 패널 발언", use_container_width=True):
            eligible = list(set(PANELS.keys()) - st.session_state.spoken_panels)
            if not eligible:
                st.session_state.spoken_panels = set()
                eligible = list(PANELS.keys())
            selected_pid = random.choice(eligible)
            history_text = "\n".join([f"[{c['name']}] {c['content']}" for c in st.session_state.chat_history[-4:]])
            query_embedding = embedder.encode([st.session_state.topic], show_progress_bar=False)[0].tolist()
            with st.spinner(f"🎙️ {PANELS[selected_pid]['name']} 발언 중..."):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                pid, p_info, answer, elapsed, context = loop.run_until_complete(compete_for_turn(selected_pid, PANELS[selected_pid], st.session_state.topic, query_embedding, history_text))
            st.session_state.spoken_panels.add(pid)
            st.session_state.chat_history.append({"role": "assistant", "name": f"📺 {p_info['name']} ({p_info['ai']}) - ⏱️ {elapsed:.1f}초", "content": answer, "avatar": "📺"})
            st.rerun()

    with b_col2:
        if st.button("👴 영감님 최종 판정 듣기", use_container_width=True):
            with st.spinner("영감님이 가장 훌륭한 단 한 명의 패널을 고르고 있습니다..."):
                history_text = "\n".join([f"[{c['name']}] {c['content']}" for c in st.session_state.chat_history])
                buffett_prompt = f"너는 워렌 버핏이야. 전체 로그를 읽고 패널들을 평가해라.\n[절대 규칙]\n1. 내재가치, 안전마진 등 철학을 기준으로 날카롭게 평가.\n2. 촌철살인 같은 너만의 비평을 내려라.\n3. 마지막 줄에 '[최종 판정] 가장 워렌 버핏의 철학에 부합한 단 한 명의 패널은 OOO입니다.' 라고 쾅 찍어라.\n\n<토론 기록>\n{history_text}"
                buffett_res = sync_openai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": buffett_prompt}], temperature=0.3)
                st.session_state.chat_history.append({"role": "assistant", "name": "👴 워렌 버핏", "content": buffett_res.choices[0].message.content, "avatar": "👴"})
            st.rerun()

    with b_col3:
        if st.button("💾 토론 종료 및 서기장 저장", type="primary", use_container_width=True):
            if not os.path.exists(SCRIBE_FILE): scribe_mem = []
            else:
                try:
                    with open(SCRIBE_FILE, "r", encoding="utf-8") as f: scribe_mem = json.load(f)
                except: scribe_mem = []
            scribe_mem.append({"role": "Scribe", "content": f"[{st.session_state.topic}] 토론 요약", "log": st.session_state.chat_history})
            with open(SCRIBE_FILE, "w", encoding="utf-8") as f: json.dump(scribe_mem, f, ensure_ascii=False, indent=2)
            st.session_state.chat_history = []
            st.session_state.spoken_panels = set()
            st.session_state.shared_news_full_texts = ""
            st.success("기록 완료 및 세션이 초기화되었습니다!")
            st.rerun()