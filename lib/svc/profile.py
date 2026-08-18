"""카테고리 표 — 어떤 영상에 어떤 스텝을 켜고 무엇을 줄지.

**카테고리 문자열을 해석하는 곳은 여기 하나다.** 갈래(audio/image)와 스텝들은 resolve() 가
넘긴 프로파일만 보고 돈다 — 그래서 카테고리가 늘어도 파이프라인 코드는 안 바뀐다.

조회 순서 — 정확일치 → 대분류 → 기본:
  "스포츠-야구"  → 정확일치
  "스포츠-농구"  → 표에 없으니 "스포츠" (종목 검출은 없고 나머지는 스포츠와 같음)
  "드라마-사극"  → "드라마"
  그 외/빈 값    → DEFAULT (검색·2차전사 없이 STT→교정→할루시→요약)

새 카테고리는 TABLE 에 한 줄 추가하면 끝이다.
"""
from dataclasses import dataclass, field

from lib.svc.audio.schema_audio import Audio


@dataclass(frozen=True)
class Profile:
    """영상 하나를 어떻게 처리할지.

    ffmpeg 는 갈래가 아니라 **두 갈래의 공통 선행 작업**이라 audio 밖에 둔다 —
    음성(audio.wav)과 프레임(frames/)을 둘 다 이게 만들기 때문에, 이게 끝나야
    음성·이미지 갈래를 띄울 수 있다.
    """
    ffmpeg: bool = False  # 원본 → 음성·프레임 추출. 끄면 요청의 file_path 를 그대로 쓴다
    audio: Audio = field(default_factory=Audio)
    image: str = ""      # 이미지 갈래에 쓸 종목 키 ("baseball"/"soccer"). "" 면 갈래 자체를 안 띄운다


# ── 카테고리 표 ────────────────────────────────────────────────────────
#   ffmpeg           원본 → 음성·프레임 추출 (갈래 공통 선행)
#   search           웹 명단 검색 (제목·연도로 등장인물/선수 찾기)
#   stt_whisper      2차 전사 (교정 대조용). 뉴스·다큐는 1차가 이미 정확해 이득 없이 환각 위험만
#   correct_glossary 교정 용어집. 목록이 있는 카테고리(스포츠 종목)에서만 실제로 실린다
#   summary          요약. 스포츠는 줄거리가 의미 없어 끈다
#   스텝은 전부 적는다 — 기본값에 기대지 않아야 표만 보고 공정을 알 수 있다.
TABLE: dict[str, Profile] = {
    "스포츠-야구": Profile(ffmpeg=True, image="baseball",
                      audio=Audio(search=True, stt_qwen=True, stt_whisper=True,   correct=True,
                                  correct_glossary=True, hallu=True, summary=False)),
    "스포츠-축구": Profile(ffmpeg=True, image="soccer",
                      audio=Audio(search=True, stt_qwen=True, stt_whisper=True,   correct=True,
                                  correct_glossary=True, hallu=True, summary=False)),
    "스포츠":     Profile(ffmpeg=True,
                      audio=Audio(search=True, stt_qwen=True, stt_whisper=True,   correct=True,
                                  correct_glossary=True, hallu=True, summary=False)),
    "드라마":     Profile(ffmpeg=True,
                      audio=Audio(search=True, stt_qwen=True, stt_whisper=True,   correct=True,
                                  correct_glossary=True, hallu=True, summary=True)),
    "다큐":       Profile(ffmpeg=True,
                      audio=Audio(search=False, stt_qwen=True, stt_whisper=False, correct=True,
                                  correct_glossary=False, hallu=True, summary=True)),
    "뉴스":       Profile(ffmpeg=True,
                      audio=Audio(search=False, stt_qwen=True, stt_whisper=False, correct=True,
                                  correct_glossary=False, hallu=True, summary=True)),
}

DEFAULT = Profile()


def resolve(category: str) -> Profile:
    """카테고리 → 프로파일. 정확일치 → 대분류('-' 앞) → 기본 순으로 찾는다."""
    if not category:
        return DEFAULT
    if category in TABLE:
        return TABLE[category]
    return TABLE.get(category.split("-", 1)[0], DEFAULT)
