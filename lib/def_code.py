"""상태 코드 정의 — t_video.status_code 에 찍는 값.

**값은 여기가 원본이고, 문구는 DB(t_code)가 갖는다.** 관리자 UI 는 이 값으로 t_code 를
조인해 name/description 을 보여준다. 그래서 문구를 바꾸려고 이 파일을 열 일은 없고,
반대로 여기 값을 바꾸면 t_code 도 같이 고쳐야 한다.

DB 에서 읽어오지 않는 이유:
  ERROR_DB_CONN(2996) 을 기록해야 하는 상황은 DB 가 죽었을 때다. 코드표까지 DB 에
  있으면 그걸 못 읽어 아무것도 못 남긴다. 값은 import 시점에 확정돼 있어야 한다.

번호 규칙 — 진행 코드에 900 을 더하면 그 단계의 실패 코드다:
    2010 추출 중   → 2910 추출 실패
    2030 대사 추출 → 2930 대사 추출 실패
    2090 화면 분석 → 2990 화면 분석 실패
  실패 코드의 끝자리가 원인을 가른다:
    +0 기타 / +1 연결 실패 / +2 시간 초과 / +3 그 단계 고유 원인

2000 번대는 이 에이전트(STT)의 몫이다. 1000 번대(UI-*)와 1010·1011(장면 분석)은
다른 시스템이 쓰므로 건드리지 않는다.
"""
import httpx

# ── 진행 ───────────────────────────────────────────────────────────────
CODE_OK = 2000               # 자막 처리 완료 (최종)
CODE_ACCEPT = 2001           # 영상 접수

CODE_FFMPEG = 2010           # 음성·이미지 추출 중
CODE_SEARCH = 2020           # 출연진 정보 검색 중
CODE_QWEN = 2030             # 대사 추출 중
CODE_WHISPER = 2040          # 대사 재확인 중
CODE_CORRECT = 2050          # 자막 교정 중
CODE_GLOSSARY = 2060         # 전문 용어 교정 중
CODE_HALLU = 2070            # 잘못된 자막 걸러내는 중
CODE_SUMMARY = 2080          # 줄거리 요약 중

# ── 중단 (영상이 실패로 끝난다) ────────────────────────────────────────
CODE_ERROR = 2900                    # 알 수 없는 오류

CODE_ERROR_FFMPEG = 2910             # 음성·이미지 추출 실패
CODE_ERROR_FFMPEG_CONN = 2911        #   추출 서버 연결 실패
CODE_ERROR_FFMPEG_TIMEOUT = 2912     #   추출 시간 초과
CODE_ERROR_FFMPEG_SOURCE = 2913      #   원본 영상 없음

CODE_ERROR_QWEN = 2930               # 대사 추출 실패
CODE_ERROR_QWEN_CONN = 2931          #   전사 서버 연결 실패
CODE_ERROR_QWEN_TIMEOUT = 2932       #   대사 추출 시간 초과
CODE_ERROR_QWEN_FORMAT = 2933        #   대사 응답 오류

CODE_ERROR_IMAGE = 2990              # 화면 분석 실패
CODE_ERROR_IMAGE_CONN = 2991         #   분석 서버 연결 실패
CODE_ERROR_IMAGE_TIMEOUT = 2992      #   화면 분석 시간 초과
CODE_ERROR_IMAGE_FRAME = 2993        #   분석할 이미지 없음

CODE_ERROR_DB = 2995                 # 결과 저장 실패
CODE_ERROR_DB_CONN = 2996            #   데이터베이스 연결 실패


# ── 예외 → 실패 코드 ───────────────────────────────────────────────────
# 단계마다 같은 판정을 반복하지 않도록 한곳에 모은다. 단계가 늘면 표에 한 줄만 더한다.
#   산술(stage+901)로 줄일 수도 있지만 그러면 소스에서 2911 을 grep 해도 안 나온다 —
#   운영 중엔 코드 번호로 찾는 일이 많아 값을 그대로 적는다.
_STAGE_ERROR: dict[int, tuple[int, int, int]] = {
    #  단계          (기타,               연결 실패,               시간 초과)
    CODE_FFMPEG: (CODE_ERROR_FFMPEG, CODE_ERROR_FFMPEG_CONN, CODE_ERROR_FFMPEG_TIMEOUT),
    CODE_QWEN:   (CODE_ERROR_QWEN,   CODE_ERROR_QWEN_CONN,   CODE_ERROR_QWEN_TIMEOUT),
    CODE_ERROR_IMAGE: (CODE_ERROR_IMAGE, CODE_ERROR_IMAGE_CONN, CODE_ERROR_IMAGE_TIMEOUT),
}


def error_code(stage: int, exc: Exception) -> int:
    """(단계 진행 코드, 예외) → 실패 코드.

    같은 예외라도 단계에 따라 코드가 다르다 — 연결 실패가 추출 중이면 2911,
    화면 분석 중이면 2991 이다. 표에 없는 단계는 CODE_ERROR.

    예외 타입으로 가릴 수 있는 것만 나눈다. '원본 없음'(2913)처럼 워커가 본문 문자열로만
    알려주는 사유는 여기서 못 가린다 — 워커가 코드로 주게 되면 그때 나눈다.
    """
    etc, conn, timeout = _STAGE_ERROR.get(stage, (CODE_ERROR,) * 3)
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return conn
    if isinstance(exc, httpx.TimeoutException):        # ReadTimeout 등
        return timeout
    return etc
