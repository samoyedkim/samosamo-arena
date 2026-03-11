# samosamo_indexer.py

import warnings
warnings.filterwarnings("ignore") 

import os
import glob
import time
import chromadb
from sentence_transformers import SentenceTransformer

def extract_metadata_from_filename(filename):
    """파일명에서 채널명과 제목 분리"""
    base = os.path.basename(filename).replace(".txt", "")
    source = "Unknown"
    title = base
    
    if "KBS" in base or "경제쇼" in base:
        source = "KBS"
        title = base.replace("[KBS 경제쇼]", "").strip()
    elif "삼프로" in base or "3pro" in base.lower():
        source = "Sampro"
        title = base.replace("[삼프로TV]", "").strip()
    elif "매일경제" in base or "매경" in base:
        source = "Maeil"
        title = base.replace("[매일경제]", "").strip()
        
    return source, title

def chunk_text_smart(text, chunk_size=800, overlap=200):
    """문장 단위로 텍스트 쪼개기"""
    chunks = []
    start = 0
    text_len = len(text)
    
    while start < text_len:
        end = start + chunk_size
        if end >= text_len:
            chunks.append(text[start:])
            break
            
        best_break = end
        for i in range(end, max(start + overlap, end - 200), -1):
            if text[i] in ['.', '\n', '!', '?']:
                best_break = i + 1
                break
                
        chunks.append(text[start:best_break])
        start = best_break - overlap
        
    return chunks

def run_indexer_for_arena():
    """💡 아레나 UI에 실시간 중계를 쏴주는 제너레이터 함수"""
    yield "▶️ 임베딩 엔진(BAAI/bge-m3) 및 도서관(ChromaDB) 연결 중... (최대 10초 소요)"
    try:
        embedder = SentenceTransformer('BAAI/bge-m3')
        client = chromadb.PersistentClient(path="./samosamo_db")
        collection = client.get_or_create_collection(name="samosamo_rag")
    except Exception as e:
        yield f"❌ 엔진 로딩 실패: {e}"
        return

    txt_files = glob.glob("*.txt")
    if not txt_files:
        yield "ℹ️ 입고할 새로운 대본(.txt) 파일이 없습니다."
        return

    yield f"📁 총 {len(txt_files)}개의 대본 입고를 시작합니다."

    success_count = 0
    for i, file_path in enumerate(txt_files, 1):
        source, title = extract_metadata_from_filename(file_path)
        yield f"▶️ [{i}/{len(txt_files)}] '{title}' (출처: {source}) 분석 중..."
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            yield f"   ⚠️ 파일 읽기 실패: {e}"
            continue
            
        chunks = chunk_text_smart(content)
        yield f"   ✂️ 텍스트를 {len(chunks)}개의 조각으로 나누어 DB에 밀어 넣습니다."
        
        for j, chunk in enumerate(chunks):
            chunk_id = f"{file_path}_chunk_{j}"
            summary = chunk[:100] + "..." # 프리뷰 요약
            
            # 임베딩 및 적재
            embedding = embedder.encode(chunk).tolist()
            collection.add(
                documents=[chunk],
                embeddings=[embedding],
                metadatas=[{"source": source, "title": title, "summary": summary}],
                ids=[chunk_id]
            )
            
        yield f"   ✅ '{title}' 입고 완료!"
        
        # 💡 입고 완료된 텍스트 파일 삭제 (중복 입고 방지)
        try:
            os.remove(file_path)
            yield f"   🗑️ '{file_path}' (사용 완료 후 영구 삭제됨)"
        except:
            pass
            
        success_count += 1

    yield f"🎉 [최종 완료] 총 {success_count}개의 대본이 도서관에 성공적으로 저장되었습니다!"