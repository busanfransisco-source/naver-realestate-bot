"""실거래 표시용 통상 평형 추정.

국토부 실거래 원자료에는 전용면적만 있고 단지별 주거공용면적은 없다.
따라서 반환값은 실제 공급면적이 아니라 사용자가 지정한 59㎡→26평형,
84㎡→34평형 관례를 기준으로 한 근사 표기다.
"""

from math import floor


def approximate_pyeong_type(exclusive_sqm):
    """전용면적을 약식 평형으로 표시한다. 실제 공급평형으로 쓰지 않는다."""
    try:
        area = float(exclusive_sqm or 0)
    except (TypeError, ValueError):
        return 0
    if area <= 0:
        return 0
    if area <= 59:
        estimate = area * 26 / 59
    else:
        estimate = 26 + (area - 59) * (34 - 26) / (84 - 59)
    return max(1, floor(estimate + 0.5))
