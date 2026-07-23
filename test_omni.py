"""Qwen3-Omni 검증 — 오디오를 듣고 1차(Qwen3-ASR)·2차(whisper) 초안을 바로잡는지.

텍스트만으로는 못 고치는 오류(두 모델이 함께 틀린 것)를 소리로 회수할 수 있는지 잰다.
정답은 사장님이 귀로 확인해 주신 GT.

  구간 오디오(seek-read, base64) + Qwen 초안 + whisper 초안 + 이름 + 용어
    → Omni → 교정문 → GT 키워드로 채점

파일을 만들지 않는다. wave 로 프레임 오프셋만 읽어 메모리에서 WAV 로 감싼다.

    python3 test_omni.py            # 전체
    python3 test_omni.py 7 13 111   # 특정 idx 만
"""
import base64
import io
import json
import re
import sys
import wave

import httpx

OMNI_URL = "http://3.39.52.226:8000/v1/chat/completions"
OMNI_MODEL = "omni"
AG = "output/1"
WAV = "/stg/vod/scenemaker/1/audio.wav"
PAD = 0.3          # 앞뒤 여유(초). 말이 잘려 들어가면 판단이 어려워짐
TIMEOUT = 180.0

# 사장님 GT — (idx, 정답 설명, 채점 키워드). 텍스트 교정으로 못 고친 것들.
CASES = [
    (7,   "조심할 필요가 있는 그런 회가 됐습니다", ["조심할"]),
    (9,   "선두 타자가 살아나갔어요",              ["선두 타자"]),
    (13,  "오늘 첫 타석은 우익수 플라이 아웃",      ["우익수 플라이", "우익수플라이"]),
    (19,  "타석에는 선두타자 박정권",              ["타석에"]),
    (27,  "삼루에 김상현은 조금 전진 수비",         ["전진 수비"]),
    (37,  "정근우 리드 시작",                     ["정근우 리드"]),
    (111, "투수는 한기주로 바뀌었습니다",           ["투수는"]),
    (127, "자 타석에 나주환 육번 타자입니다",       ["타석에 나주환"]),
    (241, "희생 번트",                           ["희생 번트", "희생번트"]),
]


def clip_b64(start: float, end: float) -> str:
    """[start,end] 구간만 읽어 WAV(base64). 파일 안 만든다 — 프레임 오프셋 seek."""
    with wave.open(WAV, "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        a = max(0, int((start - PAD) * sr))
        n = int((end - start + PAD * 2) * sr)
        w.setpos(a)
        frames = w.readframes(n)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as o:
        o.setnchannels(ch)
        o.setsampwidth(sw)
        o.setframerate(sr)
        o.writeframes(frames)
    return base64.b64encode(buf.getvalue()).decode()


def top_names(roster: str, texts: str, n: int = 30) -> list[str]:
    """명단 이름 중 자막에 실제로 자주 나온 순 상위 n명.

    명단에 섞인 오류(그 해에 없던 선수)를 자동으로 배제한다 — 자막에 안 나오니 상위에 못 온다.
    """
    names = re.findall(r"^-([가-힣]{2,5})—", roster, re.M)
    cnt = {x: texts.count(x) for x in names}
    return [x for x, c in sorted(cnt.items(), key=lambda kv: -kv[1]) if c > 0][:n]


SYSTEM = """너는 야구 중계 오디오를 듣고 자막을 바로잡는 교정기다.

같은 구간에 대해 두 음성인식 시스템이 만든 초안 [A], [B] 와 실제 오디오가 주어진다.

[할 일]
오디오를 직접 듣고, 그 구간에서 실제로 말한 내용을 한국어 자막으로 적어라.
[A]·[B] 는 참고용 초안일 뿐이다. 둘 다 틀렸으면 둘 다 버리고 들리는 대로 적어라.

[지킬 것]
- 아래 [등장인물]·[야구 용어] 에 있는 말이 들리면 그 표기로 적는다.
- 없는 말을 지어내지 마라. 안 들리는 부분은 초안을 따른다.
- 구간에 있는 말만 적는다. 앞뒤 구간의 말을 끌어오지 마라.
- 요약하지 말고 말한 그대로 적는다.

[출력] 자막 텍스트만. 설명·따옴표·머리말 없이."""


def main() -> None:
    raw = {s["idx"]: s for s in json.load(open(f"{AG}/1_stt.json"))}
    wh = {int(k): v for k, v in json.load(open(f"{AG}/2_whisper.json")).items()}
    fin = {s.get("orig_idx", s["idx"]): s["text"]
           for s in json.load(open(f"{AG}/5_hallu.json"))["kept"]}
    roster = open(f"{AG}/3_roster.txt").read()
    names = top_names(roster, " ".join(s["text"] for s in raw.values()))

    from lib.svc.stt.correct import prompt_common as P
    terms = P.glossary_for("스포츠-야구").split("\n\n", 1)[-1]

    want = [int(x) for x in sys.argv[1:]] or None
    cases = [c for c in CASES if want is None or c[0] in want]

    sysmsg = (f"{SYSTEM}\n\n[등장인물]\n{', '.join(names)}\n\n[야구 용어]\n{terms}")
    ok = 0
    with httpx.Client(timeout=TIMEOUT) as http:
        for idx, ans, keys in cases:
            s = raw[idx]
            a, b = _sec(s["start"]), _sec(s["end"])
            body = {
                "model": OMNI_MODEL,
                "temperature": 0.2,
                "max_tokens": 512,
                "messages": [
                    {"role": "system", "content": sysmsg},
                    {"role": "user", "content": [
                        {"type": "audio_url",
                         "audio_url": {"url": f"data:audio/wav;base64,{clip_b64(a, b)}"}},
                        {"type": "text", "text":
                            f"[A - Qwen3-ASR]\n{s['text']}\n\n"
                            f"[B - whisper]\n{wh.get(idx, '(없음)')}\n\n"
                            f"오디오를 듣고 이 구간의 자막을 정확히 적어라."},
                    ]},
                ],
            }
            try:
                r = http.post(OMNI_URL, json=body)
                r.raise_for_status()
                out = r.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:  # noqa: BLE001 — 케이스 단위 격리
                out = f"(실패: {e})"
            hit = any(k in out for k in keys)
            ok += hit
            print(f"\n{'='*96}\n[idx {idx}] {s['start']}~{s['end']}  {'O' if hit else 'X'}  정답: {ans}")
            print(f"  A(Qwen)   : {s['text'][:110]}")
            print(f"  B(whisper): {wh.get(idx, '(없음)')[:110]}")
            print(f"  현재 최종  : {fin.get(idx, '')[:110]}")
            print(f"  ▶ Omni    : {out[:110]}")
    print(f"\n{'='*96}\n>>> {ok}/{len(cases)} 정답  (이 항목들은 현재 파이프라인에선 전부 X)")


def _sec(t: str) -> float:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


if __name__ == "__main__":
    main()
