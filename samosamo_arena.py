import streamlit as st
import requests
import json
from bs4 import BeautifulSoup
import os
from openai import OpenAI
import chromadb

# ==========================================
# 1. API 키 및 클라이언트 설정
# ==========================================
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "여기에_API_키_입력"))

def get_krx_ticker_map():
    # 임시 티커 맵 (필요시 전 종목 확대)
    return {"삼성전자": "005930", "SK하이닉스": "000660", "에코프로": "086520", "POSCO홀딩스": "005490"}

# ==========================================
# 2. 도서관(ChromaDB) 연결 (로컬에서 만든 DB 읽기 전용)
# ==========================================
@st.cache_resource
def get_library_db():
    try:
        db_path = os.path.join(os.getcwd(), "samosamo_db")
        chroma_client = chromadb.PersistentClient(path=db_path)
        return chroma_client.get_or_create_collection(name="samosamo_library")
    except Exception as e:
        return None

# ==========================================
# 3. 알프레도 전술 금융 무기 (V6 확장팩)
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

def tool_get_market_ranking(rank_type="volume", top_n=20):
    try:
        if rank_type == "etf_rise":
            res = requests.get("https://finance.naver.com/api/sise/etfItemList.nhn", headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            etf_list = res.json().get('result', {}).get('etfItemList', [])
            sorted_etf = sorted(etf_list, key=lambda x: x.get('changeRate', 0), reverse=True)
            result = [{"종목명": item['itemname'], "상승률": f"{item['changeRate']}%"} for item in sorted_etf[:top_n]]
            return json.dumps({"rank_type": rank_type, "data": result}, ensure_ascii=False)

        urls = {"volume": "https://finance.naver.com/sise/sise_quant.naver", "rise": "https://finance.naver.com/sise/sise_rise.naver", "fall": "https://finance.naver.com/sise/sise_fall.naver"}
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
        if not ticker: return json.dumps({"error": f"'{name}' 종목코드 없음."})
        res = requests.get(f"https://finance.naver.com/item/main.naver?code={ticker}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        return json.dumps({
            "종목명": name, "티커": ticker,
            "시가총액": soup.select_one('#_market_sum').text.strip() + "억원" if soup.select_one('#_market_sum') else "N/A",
            "PER": soup.select_one('#_per').text.strip() if soup.select_one('#_per') else "N/A",
            "PBR": soup.select_one('#_pbr').text.strip() if soup.select_one('#_pbr') else "N/A"
        }, ensure_ascii=False)
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
        if not ticker: return json.dumps({"error": f"'{name}' 종목코드 없음."})
        res = requests.get(f"https://finance.naver.com/item/frgn.naver?code={ticker}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        res.encoding = 'euc-kr'
        soup = BeautifulSoup(res.text, 'html.parser')
        cols = soup.select_one('.type2').find_all('tr', onmouseover="mouseOver(this)")[0].find_all('td')
        return json.dumps({"종목명": name, "날짜": cols[0].text.strip(), "기관순매매": cols[5].text.strip(), "외국인순매매": cols[6].text.strip(), "외국인보유율": cols[8].text.strip() + "%"}, ensure_ascii=False)
    except Exception as e: return json.dumps({"error": f"수급 조회 실패: {str(e)}"})

tools_schema = [
    {"type": "function", "function": {"name": "get_market_index", "description": "국내 주요 증시 지수와 환율을 가져옵니다.", "parameters": { "type": "object", "properties": {} }}},
    {"type": "function", "function": {"name": "get_market_ranking", "description": "종목 랭킹을 가져옵니다.", "parameters": {"type": "object", "properties": {"rank_type": {"type": "string", "enum": ["volume", "rise", "fall", "etf_rise"]}, "top_n": {"type": "integer"}}, "required": ["rank_type"]}}},
    {"type": "function", "function": {"name": "get_company_finance", "description": "특정 종목의 재무 정보를 가져옵니다.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "get_theme_ranking", "description": "가장 크게 상승 중인 주도 테마와 관련 주도주를 가져옵니다.", "parameters": {"type": "object", "properties": {"top_n": {"type": "integer"}}, "required": ["top_n"]}}},
    {"type": "function", "function": {"name": "get_investor_trend", "description": "특정 종목의 최근 기관 및 외국인 수급 동향을 가져옵니다.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}}
]

# ==========================================
# 4. Streamlit UI 및 SAMOSAMO 페르소나 엔진
# ==========================================
st.set_page_config(page_title="SAMOSAMO Arena", page_icon="🏛️", layout="wide")
st.title("🏛️ SAMOSAMO Arena")

with st.sidebar:
    st.header("⚙️ 시스템 관제탑")
    st.info("💡 파이프라인(크롤링/대본)은 로컬 터보 엔진으로 이관되었습니다. 이곳은 순수 분석 및 토론 공간입니다.")
    if st.button("🧹 대화 초기화"):
        st.session_state.messages = []
        st.rerun()

if "messages" not in st.session_state or not st.session_state.messages:
    st.session_state.messages = [{"role": "assistant", "content": "🤵 **알프레도:** 안녕하십니까 마스터, 알프레도입니다. 영감님과 패널들도 대기 중입니다. 무엇을 분석해 드릴까요?"}]

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("알프레도, 패널, 영감님에게 지시를 내려주십시오."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    # ------------------------------------------------
    # 1막: 알프레도의 팩트 체크 및 데이터 수집
    # ------------------------------------------------
    with st.chat_message("assistant"):
        st.markdown("🤵 **알프레도:** 데이터망을 검색 중입니다...")
        alfredo_prompt = "당신은 SAMOSAMO의 수석 비서 '알프레도'입니다. 도구를 사용해 정확한 팩트를 브리핑하세요."
        try:
            res = client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[{"role": "system", "content": alfredo_prompt}] + [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages[-3:] if "content" in m],
                tools=tools_schema, tool_choice="auto"
            )
            msg = res.choices[0].message
            if msg.tool_calls:
                # 도구 실행 라우팅
                tool_messages = [{"role": "assistant", "content": msg.content, "tool_calls": msg.tool_calls}]
                for tc in msg.tool_calls:
                    fn_name, args = tc.function.name, json.loads(tc.function.arguments)
                    tool_result = ""
                    if fn_name == "get_market_index": tool_result = tool_get_market_index()
                    elif fn_name == "get_market_ranking": tool_result = tool_get_market_ranking(args.get("rank_type", "volume"), args.get("top_n", 20))
                    elif fn_name == "get_company_finance": tool_result = tool_get_company_finance(args["name"])
                    elif fn_name == "get_theme_ranking": tool_result = tool_get_theme_ranking(args.get("top_n", 5))
                    elif fn_name == "get_investor_trend": tool_result = tool_get_investor_trend(args["name"])
                    tool_messages.append({"tool_call_id": tc.id, "role": "tool", "name": fn_name, "content": tool_result})
                
                final_res = client.chat.completions.create(
                    model="gpt-4-turbo-preview",
                    messages=[{"role": "system", "content": alfredo_prompt}] + tool_messages
                )
                alfredo_answer = final_res.choices[0].message.content
            else:
                alfredo_answer = msg.content

            st.markdown(f"🤵 **알프레도:**\n{alfredo_answer}")
            st.session_state.messages.append({"role": "assistant", "content": f"🤵 **알프레도:**\n{alfredo_answer}"})
        except Exception as e:
            st.error(f"알프레도 시스템 에러: {e}")
            alfredo_answer = "데이터 수집 실패"

    # ------------------------------------------------
    # 2막: 패널들의 치열한 토론 (강세론자 vs 약세론자)
    # ------------------------------------------------
    with st.chat_message("assistant"):
        st.markdown("🗣️ **패널 토론:** 알프레도의 브리핑을 바탕으로 분석 중입니다...")
        panel_prompt = f"당신들은 주식 토론 패널입니다. 강세론자(Bull)와 약세론자(Bear)의 입장에서 다음 알프레도의 브리핑을 짧고 치열하게 분석하세요: {alfredo_answer}"
        try:
            panel_res = client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[{"role": "user", "content": panel_prompt}]
            )
            panel_answer = panel_res.choices[0].message.content
            st.markdown(f"🗣️ **패널 토론:**\n{panel_answer}")
            st.session_state.messages.append({"role": "assistant", "content": f"🗣️ **패널 토론:**\n{panel_answer}"})
        except Exception as e:
            st.error(f"패널 시스템 에러: {e}")

    # ------------------------------------------------
    # 3막: 영감님의 최종 통찰 (ChromaDB 도서관 RAG 연동)
    # ------------------------------------------------
    with st.chat_message("assistant"):
        st.markdown("👴 **영감님:** 도서관의 지혜를 열람 중이다...")
        library = get_library_db()
        rag_context = ""
        if library:
            try:
                # 질문과 관련된 과거 유튜브 대본 지식 검색
                results = library.query(query_texts=[prompt], n_results=3)
                rag_context = "\n".join(results['documents'][0]) if results and 'documents' in results else "관련 도서관 기록 없음."
            except: rag_context = "도서관 접근 실패."
        else:
            rag_context = "도서관 DB가 연결되지 않았음."

        grandpa_prompt = f"당신은 시장의 산전수전을 다 겪은 '영감님'입니다. 반말을 사용하며 묵직한 통찰을 줍니다. 알프레도의 팩트와 패널 토론, 그리고 다음 [도서관 기록]을 참고하여 최종 결론을 내리세요.\n[도서관 기록]: {rag_context}"
        try:
            grandpa_res = client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": grandpa_prompt},
                    {"role": "user", "content": f"마스터의 질문: {prompt}"}
                ]
            )
            grandpa_answer = grandpa_res.choices[0].message.content
            st.markdown(f"👴 **영감님:**\n{grandpa_answer}")
            st.session_state.messages.append({"role": "assistant", "content": f"👴 **영감님:**\n{grandpa_answer}"})
        except Exception as e:
            st.error(f"영감님 시스템 에러: {e}")