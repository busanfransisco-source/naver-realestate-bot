"""전국 실거래 요약에서 사용하는 시도 표시 순서."""

# 사용자가 지정한 수도권·부산 우선순위 뒤에 나머지 지역을 인구순으로 배치한다.
POPULATION_ORDER = (
    "서울",
    "경기",
    "인천",
    "부산",
    "경남",
    "광주·전남",
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

REGION_EMOJI = {
    "서울": "🏙️",
    "경기": "🏘️",
    "인천": "🌉",
    "부산": "🌊",
    "경남": "⚓",
    "광주·전남": "🌾",
    "경북": "🏛️",
    "대구": "🍎",
    "충남": "🌅",
    "전북": "🍚",
    "충북": "⛰️",
    "강원": "🏔️",
    "대전": "🔬",
    "울산": "🏭",
    "제주": "🍊",
    "세종": "🏢",
}

_POPULATION_RANK = {name: index for index, name in enumerate(POPULATION_ORDER)}


def population_order_key(name):
    """알려진 시도는 지정 순서, 새 지역명은 맨 뒤 가나다순으로 보낸다."""
    return (_POPULATION_RANK.get(name, len(POPULATION_ORDER)), name)


def region_heading(name):
    """신고가 목록에서 사용하는 지역별 이모지 제목을 반환한다."""
    return f"{REGION_EMOJI.get(name, '📍')} {name}"
