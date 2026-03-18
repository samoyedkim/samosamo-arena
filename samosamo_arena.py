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
# 1. 엔진, 도서관 & 통합 티커 사전 로드
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
# 3. 사이드바 UI (파이프라인 제거)
# ==========================================
with st.sidebar:
    st.header("🐞 SOS 리포트")
    if st.session_state.chat_history:
        sos_log = "🚨 [ARENA V6 SOS]\n\n"
        for msg in st.session_state.chat_history[-4:]: 
            sos_log += f"[{msg['name']}]\n{msg['content']}\n\n"
        st.code(sos_log, language="text") 
    else:
        st.info("대화 기록이 없습니다.")
    st.divider()

    st.header("🔗 알프레도 즐겨찾기")
    with st.expander("➕ 새 단축어 추가", expanded=False):
        new_macro_name = st.text_input("단축어")
        new_macro_url = st.text_input("URL")
        if st.button("저장", use_container_width=True) and new_macro_name and new_macro_url:
            st.session_state.macros[new_macro_name] = new_macro_url
            save_macros(); st.success("등록 완료!"); st.rerun()

    for key, url in list(st.session_state.macros.items()):
        colA, colB = st.columns([4, 1])
        with colA: st.markdown(f"🏷️ **{key}**")
        with colB:
            if st.button("❌", key=f"del_{key}"):
                del st.session_state.macros[key]; save_macros(); st.rerun()
    st.divider()
    st.info("💡 파이프라인 엔진은 로컬 PC로 이관되었습니다.")

# ==========================================
# 4. 알프레도 전술 금융 무기 (V6 패치)
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
        if rank_type == "etf_rise":
            res = requests.get("https://finance.naver.com/api/sise/etfItemList.nhn", headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            etf_list = res.json().get('result', {}).get('etfItemList', [])
            sorted_etf = sorted(etf_list, key=lambda x: x.get('changeRate', 0), reverse=True)
            result = [{"종목명": item['itemname'], "상승률": f"{item['changeRate']}%"} for item in sorted_etf[:top_n]]
            return json.dumps({"rank_type": rank_type, "data": result}, ensure_ascii=False)

        urls = {"volume": "https://finance.naver.com/sise/sise_quant.naver", "foreign": "https://finance.naver.com/sise/sise_foreign_up.naver", "rise": "https://finance.naver.com/sise/sise_rise.naver", "fall": "https://finance.naver.com/sise/sise_fall.naver", "etf_volume": "https://finance.naver.com/sise/etf.naver"}
        res = requests.get(urls.get(rank_type, urls["volume"]), headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        res.encoding = 'euc-kr' 
        soup = BeautifulSoup(res.text, 'html.parser')
        table = soup.find('table', {'class': 'type_2'})
        result = []
        for r in table.find_all('tr'):
            a_tag = r.find('a')
            if a_tag and r.find('td', class_='num'): result.append({"종목명": a_tag.text.strip()})
            if len(result) >= top_n: break
        return json.dumps({"rank_type": rank_type, "data": result}, ensure_ascii=False)
    except Exception as e: return json.dumps({"error": f"랭킹 조회 실패: {str(e)}"})

def tool_get_company_finance(name):
    try:
        krx_map = get_krx_ticker_map()
        ticker = krx_map.get(name)
        if not ticker: return json.dumps({"error": f"'{name}' 종목코드 찾기 실패."})
        res = requests.get(f"https://finance.naver.com/item/main.naver?code={ticker}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        return json.dumps({"종목명": name, "티커": ticker, "시가총액": soup.select_one('#_market_sum').text.strip() + "억원" if soup.select_one('#_market_sum') else "N/A", "PER": soup.select_one('#_per').text.strip() if soup.select_one('#_per') else "N/A", "PBR": soup.select_one('#_pbr').text.strip() if soup.select_one('#_pbr') else "N/A", "배당수익률": soup.select_one('#_dvr').text.strip() + "%" if soup.select_one('#_dvr') else "N/A"}, ensure_ascii=False)
    except Exception as e: return json.dumps({"error": f"재무 조회 실패: {str(e)}"})

def tool_get_theme_ranking(top_n=5):
    try:
        res = requests.get("https://finance.naver.com/sise/theme.naver", headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        res.encoding = 'euc-kr'
        soup = BeautifulSoup(res.text, 'html.parser')
        table = soup.select_one('.type_1.theme')
        result = []
        for tr in table.find_all('tr'):
            tds = tr.find_all('td')
            if len(tds) > 2 and tds[0].find('a'):
                result.append({"테마명": tds[0].find('a').text.strip(), "상승률": tds[1].text.strip(), "주도주": tds[2].text.strip().replace('\n', ' ')})
            if len(result) >= top_n: break
        return json.dumps({"data": result}, ensure_ascii=False)
    except Exception as e: return json.dumps({"error": f"테마 조회 실패: {str(e)}"})

def tool_get_investor_trend(name):
    try:
        krx_map = get_krx_ticker_map()
        ticker = krx_map.get(name)
        if not ticker: return json.dumps({"error": "종목코드 없음"})
        res = requests.get(f"https://finance.naver.com/item/frgn.naver?code={ticker}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        res.encoding = 'euc-kr'
        soup = BeautifulSoup(res.text, 'html.parser')
        cols = soup.select_one('.type2').find_all('tr', onmouseover="mouseOver(this)")[0].find_all('td')
        return json.dumps({"종목명": name, "날짜": cols[0].text.strip(), "기관순매매": cols[5].text.strip(), "외국인순매매": cols[6].text.strip(), "외국인보유율": cols[8].text.strip() + "%"}, ensure_ascii=False)
    except Exception as e: return json.dumps({"error": f"수급 조회 실패: {str(e)}"})

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

def tool_search_news(query, count=5):
    try:
        res = requests.get("https://openapi.naver.com/v1/search/news.json", headers={"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}, params={"query": query, "display": count, "sort": "date"}, timeout=5)
        news_list = []
        for r in res.json().get('items', []):
            news_list.append({"title": BeautifulSoup(html.unescape(r['title']), "html.parser").get_text(), "url": r.get('link')})
        return json.dumps({"news": news_list}, ensure_ascii=False)
    except: return json.dumps({"error": "뉴스 검색 실패"})

tools_schema = [
    {"type": "function", "function": {"name": "get_market_index", "description": "주요 지수(코스피, 코스닥)와 환율을 가져옵니다.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_market_ranking", "description": "종목 랭킹 조회", "parameters": {"type": "object", "properties": {"rank_type": {"type": "string", "enum": ["volume", "foreign", "rise", "fall", "etf_volume", "etf_rise"]}, "top_n": {"type": "integer"}}, "required": ["rank_type"]}}},
    {"type": "function", "function": {"name": "get_company_finance", "description": "종목 재무 정보", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "get_theme_ranking", "description": "주도 테마 정보", "parameters": {"type": "object", "properties": {"top_n": {"type": "integer"}}, "required": ["top_n"]}}},
    {"type": "function", "function": {"name": "get_investor_trend", "description": "종목별 수급 동향", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "get_historical_data", "description": "과거 주가 데이터", "parameters": {"type": "object", "properties": {"names": {"type": "array", "items": {"type": "string"}}, "start_date": {"type": "string"}, "end_date": {"type": "string"}}, "required": ["names", "start_date", "end_date"]}}},
    {"type": "function", "function": {"name": "search_news", "description": "뉴스 검색", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "count": {"type": "integer"}}, "required": ["query"]}}}
]

# ==========================================
# 5. 엔진 로직 (기존과 동일)
# ==========================================
def sync_generate_gemini(client, prompt):
    if not client: return "Gemini 키 오류"
    return client.models.generate_content(model="gemini-2.0-flash", contents=prompt).text

async def generate_openai(client, prompt):
    res = await client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
    return res.choices[0].message.content

async def compete_for_turn(panel_id, panel_info, topic, query_embedding, history_text):
    start_time = time.time()
    try:
        results = await asyncio.to_thread(collection.query, query_embeddings=[query_embedding], n_results=2, where={"source": panel_info["tag"]})
        context_text = "\n".join(results['documents'][0]) if results['documents'] else "지식 없음"
        prompt = f"당신은 '{panel_info['name']}' 패널입니다. 아래 팩트를 기반으로 {topic}에 대해 토론하세요.\n팩트: {context_text}\n기록: {history_text}"
        if panel_info["ai"] == "Gemini": answer = await asyncio.to_thread(sync_generate_gemini, panel_info["client"], prompt)
        else: answer = await generate_openai(panel_info["client"], prompt)
        return panel_id, panel_info, answer, time.time() - start_time
    except Exception as e: return panel_id, panel_info, f"에러: {e}", 0

# ==========================================
# 6. 메인 UI 및 타겟 라우팅 (V6 패치 적용)
# ==========================================
st.title("🏛️ SAMOSAMO AI 콜로세움 V6.0")

for chat in st.session_state.chat_history:
    with st.chat_message(chat["role"], avatar=chat.get("avatar")):
        st.markdown(f"**{chat['name']}**")
        st.write(chat["content"])
st.divider()

col1, col2 = st.columns([3, 1])
with col1:
    target_mode = st.radio("수신자", ["🤵 알프레도", "🗣️ 패널 토론"], horizontal=True)
    master_input = st.chat_input("메시지를 입력하세요...")

if master_input:
    st.session_state.topic = master_input
    st.session_state.chat_history.append({"role": "user", "name": "👑 마스터", "content": master_input, "avatar": "👑"})
    
    if target_mode == "🤵 알프레도":
        with st.chat_message("assistant", avatar="🤵"):
            st.markdown("**🤵 알프레도 (수석 비서)**")
            today = datetime.date.today().strftime("%Y-%m-%d")
            sys_prompt = f"당신은 알프레도입니다. 오늘 날짜는 {today}입니다. 도구 연계(Chaining)를 활용해 표 형식으로 보고하세요."
            history = "\n".join([f"[{c['name']}] {c['content']}" for c in st.session_state.chat_history[-6:]])
            messages = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": f"{history}\n지시: {master_input}"}]
            
            with st.spinner("알프레도가 데이터 분석 중입니다..."):
                response = sync_openai_client.chat.completions.create(model="gpt-4o-mini", messages=messages, tools=tools_schema)
                msg = response.choices[0].message
                if msg.tool_calls:
                    messages.append(msg)
                    for tc in msg.tool_calls:
                        f_name, args = tc.function.name, json.loads(tc.function.arguments)
                        # V6 신규 무기 라우팅
                        if f_name == "get_market_index": res = tool_get_market_index()
                        elif f_name == "get_market_ranking": res = tool_get_market_ranking(args.get("rank_type"), args.get("top_n", 10))
                        elif f_name == "get_company_finance": res = tool_get_company_finance(args["name"])
                        elif f_name == "get_theme_ranking": res = tool_get_theme_ranking(args.get("top_n", 5))
                        elif f_name == "get_investor_trend": res = tool_get_investor_trend(args["name"])
                        elif f_name == "get_historical_data": res = tool_get_historical_data(args["names"], args["start_date"], args["end_date"])
                        elif f_name == "search_news": res = tool_search_news(args["query"], args.get("count", 5))
                        messages.append({"tool_call_id": tc.id, "role": "tool", "name": f_name, "content": res})
                    
                    final = sync_openai_client.chat.completions.create(model="gpt-4o-mini", messages=messages)
                    ans = final.choices[0].message.content
                else: ans = msg.content
                st.write(ans)
                st.session_state.chat_history.append({"role": "assistant", "name": "🤵 알프레도", "content": ans, "avatar": "🤵"})

    elif target_mode == "🗣️ 패널 토론":
        eligible = list(set(PANELS.keys()) - st.session_state.spoken_panels)
        if not eligible: st.session_state.spoken_panels = set(); eligible = list(PANELS.keys())
        pid = random.choice(eligible)
        q_emb = embedder.encode([st.session_state.topic])[0].tolist()
        with st.spinner(f"🎙️ {PANELS[pid]['name']} 발언 준비..."):
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
            pid, info, ans, elap = loop.run_until_complete(compete_for_turn(pid, PANELS[pid], st.session_state.topic, q_emb, ""))
            st.session_state.spoken_panels.add(pid)
            st.session_state.chat_history.append({"role": "assistant", "name": f"📺 {info['name']} ({info['ai']})", "content": ans, "avatar": "📺"})
    st.rerun()

# 토론 컨트롤 버튼 (생략 가능하나 기능 유지를 위해 포함)
if st.session_state.chat_history:
    st.markdown("### 🎮 컨트롤")
    b_col1, b_col2, b_col3 = st.columns(3)
    with b_col1:
        if st.button("▶️ 다음 패널"): st.rerun()
    with b_col2:
        if st.button("👴 영감님 판정"):
            with st.spinner("영감님 분석 중..."):
                res = sync_openai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": f"토론을 보고 최종 판정을 내려라.\n{st.session_state.chat_history}"}])
                st.session_state.chat_history.append({"role": "assistant", "name": "👴 영감님", "content": res.choices[0].message.content, "avatar": "👴"})
            st.rerun()
    with b_col3:
        if st.button("💾 저장 및 종료"):
            st.session_state.chat_history = []; st.session_state.spoken_panels = set(); st.rerun()
