import streamlit as st
import requests
import json
from bs4 import BeautifulSoup
import os
from openai import OpenAI
import time

# ==========================================
# 1. API 키 및 클라이언트 설정 (파트너님의 환경에 맞게 유지)
# ==========================================
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "여기에_API_키_입력"))

# 임시 티커 맵 (실제 사용 시 pykrx 등을 활용한 맵핑 로직 권장)
def get_krx_ticker_map():
    return {"삼성전자": "005930", "SK하이닉스": "000660", "에코프로": "086520", "POSCO홀딩스": "005490"}

# ==========================================
# 2. 알프레도 전술 금융 무기 (V6 확장팩)
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
        # 💡 ETF 랭킹 전용 API 다이렉트 찌르기 (에러 완벽 수리)
        if rank_type == "etf_rise":
            res = requests.get("https://finance.naver.com/api/sise/etfItemList.nhn", headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            etf_list = res.json().get('result', {}).get('etfItemList', [])
            sorted_etf = sorted(etf_list, key=lambda x: x.get('changeRate', 0), reverse=True)
            result = [{"종목명": item['itemname'], "상승률": f"{item['changeRate']}%"} for item in sorted_etf[:top_n]]
            return json.dumps({"rank_type": rank_type, "data": result}, ensure_ascii=False)

        urls = {
            "volume": "https://finance.naver.com/sise/sise_quant.naver",
            "rise": "https://finance.naver.com/sise/sise_rise.naver",
            "fall": "https://finance.naver.com/sise/sise_fall.naver"
        }
        res = requests.get(urls.get(rank_type, urls["volume"]), headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        res.encoding = 'euc-kr' 
        soup = BeautifulSoup(res.text, 'html.parser')
        table = soup.find('table', {'class': 'type_2'})
        result = []
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
                theme_name = tds[0].find('a').text.strip()
                rise_rate = tds[1].text.strip()
                lead_stocks = tds[2].text.strip().replace('\n', ' ')
                result.append({"테마명": theme_name, "상승률": rise_rate, "주도주": lead_stocks})
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
        table = soup.select_one('.type2')
        rows = table.find_all('tr', onmouseover="mouseOver(this)")
        if not rows: return json.dumps({"error": "수급 데이터 없음"})
        cols = rows[0].find_all('td')
        return json.dumps({
            "종목명": name, "날짜": cols[0].text.strip(),
            "기관순매매": cols[5].text.strip(), "외국인순매매": cols[6].text.strip(),
            "외국인보유율": cols[8].text.strip() + "%"
        }, ensure_ascii=False)
    except Exception as e: return json.dumps({"error": f"수급 조회 실패: {str(e)}"})

# ==========================================
# 3. 도구 스키마 정의
# ==========================================
tools_schema = [
    {"type": "function", "function": {"name": "get_market_index", "description": "국내 주요 증시 지수와 환율을 가져옵니다.", "parameters": { "type": "object", "properties": {} }}},
    {"type": "function", "function": {"name": "get_market_ranking", "description": "종목 랭킹을 가져옵니다.", "parameters": {"type": "object", "properties": {"rank_type": {"type": "string", "enum": ["volume", "rise", "fall", "etf_rise"]}, "top_n": {"type": "integer"}}, "required": ["rank_type"]}}},
    {"type": "function", "function": {"name": "get_company_finance", "description": "특정 종목의 재무 정보를 가져옵니다.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "get_theme_ranking", "description": "가장 크게 상승 중인 주도 테마와 관련 주도주를 가져옵니다.", "parameters": {"type": "object", "properties": {"top_n": {"type": "integer"}}, "required": ["top_n"]}}},
    {"type": "function", "function": {"name": "get_investor_trend", "description": "특정 종목의 최근 기관 및 외국인 수급 동향을 가져옵니다.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}}
]

# ==========================================
# 4. Streamlit UI 및 알프레도 챗봇 로직
# ==========================================
st.set_page_config(page_title="SAMOSAMO Arena", page_icon="📈", layout="wide")
st.title("🤵 SAMOSAMO Arena - 알프레도")

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "안녕하십니까 마스터, 시장의 흐름을 읽어드리는 알프레도입니다. 무엇을 분석해 드릴까요?"}]

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("알프레도에게 지시를 내려주십시오."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        message_placeholder.markdown("알프레도가 시장 데이터를 분석 중입니다...")
        
        system_prompt = "당신은 SAMOSAMO 프로젝트의 수석 투자 에이전트 '알프레도'입니다. 정중한 집사 톤으로 대답하며, 제공된 도구를 적극 활용해 한국 증시를 분석하십시오."
        
        try:
            # 1차 API 호출 (도구 사용 여부 판단)
            response = client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[{"role": "system", "content": system_prompt}] + st.session_state.messages,
                tools=tools_schema,
                tool_choice="auto"
            )
            
            response_message = response.choices[0].message
            
            # 도구를 사용해야 하는 경우
            if response_message.tool_calls:
                st.session_state.messages.append(response_message)
                
                for tool_call in response_message.tool_calls:
                    fn_name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    tool_result = ""
                    
                    # 💡 라우팅 로직 (신규 무기 완벽 연결)
                    if fn_name == "get_market_index": tool_result = tool_get_market_index()
                    elif fn_name == "get_market_ranking": tool_result = tool_get_market_ranking(args.get("rank_type", "volume"), args.get("top_n", 20))
                    elif fn_name == "get_company_finance": tool_result = tool_get_company_finance(args["name"])
                    elif fn_name == "get_theme_ranking": tool_result = tool_get_theme_ranking(args.get("top_n", 5))
                    elif fn_name == "get_investor_trend": tool_result = tool_get_investor_trend(args["name"])
                    
                    st.session_state.messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": fn_name,
                        "content": tool_result
                    })
                
                # 2차 API 호출 (도구 결괏값을 바탕으로 최종 답변 생성)
                second_response = client.chat.completions.create(
                    model="gpt-4-turbo-preview",
                    messages=[{"role": "system", "content": system_prompt}] + st.session_state.messages
                )
                final_answer = second_response.choices[0].message.content
                message_placeholder.markdown(final_answer)
                st.session_state.messages.append({"role": "assistant", "content": final_answer})
                
            else:
                # 도구 없이 바로 답변하는 경우
                final_answer = response_message.content
                message_placeholder.markdown(final_answer)
                st.session_state.messages.append({"role": "assistant", "content": final_answer})
                
        except Exception as e:
            message_placeholder.markdown(f"❌ 시스템 에러 발생: {str(e)}")