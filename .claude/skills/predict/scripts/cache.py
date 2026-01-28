"""
파일 기반 캐시 시스템

날짜별 디렉토리 구조로 캐시를 관리합니다.
캐시 키는 MD5 해시로 생성되며, JSON 형식으로 저장됩니다.
"""
import os
import json
import hashlib
import shutil

from config import CACHE_DIR, CACHE_ENABLED

# 캐시 히트/미스 카운터
cache_stats = {"hits": 0, "misses": 0}


def _ensure_cache_dir():
    """캐시 디렉토리 생성"""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)


def _get_cache_path(cache_type: str, ticker: str, date: str, extra: str = "") -> str:
    """캐시 파일 경로 생성"""
    key = f"{cache_type}_{ticker}_{date}_{extra}"
    filename = hashlib.md5(key.encode()).hexdigest()[:16] + ".json"
    return os.path.join(CACHE_DIR, date, filename)


def _read_cache(cache_path: str):
    """캐시 파일 읽기"""
    if not CACHE_ENABLED:
        return None
    try:
        if os.path.exists(cache_path):
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _write_cache(cache_path: str, data):
    """캐시 파일 쓰기"""
    if not CACHE_ENABLED:
        return
    try:
        cache_dir = os.path.dirname(cache_path)
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def clear_cache():
    """캐시 디렉토리 삭제"""
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
        print(f"캐시 삭제 완료: {CACHE_DIR}")
    else:
        print("삭제할 캐시가 없습니다.")


def get_cache_stats():
    """캐시 통계 반환"""
    if not os.path.exists(CACHE_DIR):
        return {"total_files": 0, "total_size_mb": 0, "dates": []}

    total_files = 0
    total_size = 0
    dates = []

    for date_dir in os.listdir(CACHE_DIR):
        date_path = os.path.join(CACHE_DIR, date_dir)
        if os.path.isdir(date_path):
            dates.append(date_dir)
            for f in os.listdir(date_path):
                total_files += 1
                total_size += os.path.getsize(os.path.join(date_path, f))

    return {
        "total_files": total_files,
        "total_size_mb": round(total_size / 1024 / 1024, 2),
        "dates": sorted(dates, reverse=True)
    }
