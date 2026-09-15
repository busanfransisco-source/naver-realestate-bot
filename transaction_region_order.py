"""전국 실거래 요약에서 사용하는 시도 인구순 정렬 기준."""

# 행정안전부 주민등록 인구통계 2026년 8월 말 기준, 인구 내림차순.
POPULATION_ORDER = (
    "경기",
    "서울",
    "부산",
    "경남",
    "광주·전남",
    "인천",
    "경북",
    "대구",
    "충남",
    "전북",
    "충북",
    "강원",
    "대전",
    "울산",
    "제주",
    "세종",
)

_POPULATION_RANK = {name: index for index, name in enumerate(POPULATION_ORDER)}


def population_order_key(name):
    """알려진 시도는 인구순, 새 지역명은 맨 뒤 가나다순으로 보낸다."""
    return (_POPULATION_RANK.get(name, len(POPULATION_ORDER)), name)
