"""Qwen3-Omni 0~3분 전 구간 — 병렬 호출 + 현행 최종본과 나란히 비교.

틀린 지점만 보면 그 사이에서 망가진 걸 놓친다 → 구간 전체를 찍는다.
결과는 output/1/omni_3min.txt (Q/B/현행/Omni 4단) + 콘솔 요약.

    python3 test_omni3.py [초]      # 기본 180초
"""
import asyncio
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
PAD = 0.3
CONC = 8            # vLLM --max-num-seqs 10 에 맞춤
TIMEOUT = 300.0

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

# 사장님이 귀로 확인해 주신 0~3분 정답 (초, 설명, 채점 키워드)
GT3 = [
    (33,  "구톰슨",              ["구톰슨"]),
    (44,  "조심할",              ["조심할"]),
    (44,  "그런 회가",           ["그런 회"]),
    (62,  "선두 타자가",         ["선두 타자"]),
    (74,  "정근우 타자",         ["정근우 타자", "좋은 정근우"]),
    (136, "저지를 했기",         ["저지를"]),
    (155, "타석에는",            ["타석에"]),
    (164, "2루에 갖다",          ["2루에 갖다", "2루에다", "이루에"]),
    (171, "두고 공격",           ["두고 공격"]),
    (179, "볼카운트",            ["볼카운트", "볼 카운트"]),
]


def _sec(t: str) -> float:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def clip_b64(start: float, end: float) -> str:
    """[start,end] 구간만 seek-read 해 WAV(base64). 파일을 만들지 않는다."""
    with wave.open(WAV, "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        w.setpos(max(0, int((start - PAD) * sr)))
        frames = w.readframes(int((end - start + PAD * 2) * sr))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as o:
        o.setnchannels(ch); o.setsampwidth(sw); o.setframerate(sr)
        o.writeframes(frames)
    return base64.b64encode(buf.getvalue()).decode()


def top_names(roster: str, texts: str, n: int = 30) -> list[str]:
    """자막에 실제로 자주 나온 순 상위 n명 — 명단에 섞인 오류를 자동 배제."""
    names = re.findall(r"^-([가-힣]{2,5})—", roster, re.M)
    cnt = {x: texts.count(x) for x in names}
    return [x for x, c in sorted(cnt.items(), key=lambda kv: -kv[1]) if c > 0][:n]


async def main() -> None:
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 180.0
    raw = json.load(open(f"{AG}/1_stt.json"))
    wh = {int(k): v for k, v in json.load(open(f"{AG}/2_whisper.json")).items()}
    fin = {s.get("orig_idx", s["idx"]): s["text"]
           for s in json.load(open(f"{AG}/5_hallu.json"))["kept"]}
    roster = open(f"{AG}/3_roster.txt").read()
    names = top_names(roster, " ".join(s["text"] for s in raw))
    from lib.svc.stt.correct import prompt_common as P
    terms = P.glossary_for("스포츠-야구").split("\n\n", 1)[-1]
    sysmsg = f"{SYSTEM}\n\n[등장인물]\n{', '.join(names)}\n\n[야구 용어]\n{terms}"

    segs = [s for s in raw if _sec(s["start"]) < limit]
    print(f"대상 {len(segs)} 구간 (0~{limit:.0f}초), 동시 {CONC}")
    sem = asyncio.Semaphore(CONC)

    async def one(http, s):
        body = {"model": OMNI_MODEL, "temperature": 0.2, "max_tokens": 512,
                "messages": [
                    {"role": "system", "content": sysmsg},
                    {"role": "user", "content": [
                        {"type": "audio_url", "audio_url": {
                            "url": "data:audio/wav;base64," +
                                   clip_b64(_sec(s["start"]), _sec(s["end"]))}},
                        {"type": "text", "text":
                            f"[A - Qwen3-ASR]\n{s['text']}\n\n"
                            f"[B - whisper]\n{wh.get(s['idx'], '(없음)')}\n\n"
                            f"오디오를 듣고 이 구간의 자막을 정확히 적어라."}]}]}
        async with sem:
            try:
                r = await http.post(OMNI_URL, json=body)
                r.raise_for_status()
                return s["idx"], r.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:  # noqa: BLE001 — 구간 단위 격리
                return s["idx"], f"(실패: {e})"

    import time
    t0 = time.time()
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        res = dict(await asyncio.gather(*[one(http, s) for s in segs]))
    el = time.time() - t0
    print(f"소요 {el:.0f}초  ({el/len(segs):.1f}초/구간)")

    with open(f"{AG}/omni_3min.txt", "w") as f:
        f.write(f"0~{limit:.0f}초 전 구간 — Q=1차 B=whisper 현행=지금최종 Omni=오디오교정\n" + "=" * 104 + "\n")
        for s in segs:
            i = s["idx"]
            f.write(f"\n[idx {i}] {s['start']}\n  Q   : {s['text']}\n")
            if i in wh:
                f.write(f"  B   : {wh[i]}\n")
            f.write(f"  현행 : {fin.get(i, '')}\n  Omni: {res.get(i, '')}\n")
    print(f"saved {AG}/omni_3min.txt")

    # 채점 — 사장님 GT
    def near(get, t):
        return " ".join(get(s["idx"]) for s in segs
                        if _sec(s["end"]) >= t - 2 and _sec(s["start"]) <= t + 8)
    cur = sum(1 for t, _, k in GT3 if any(x in near(lambda i: fin.get(i, ""), t) for x in k))
    omn = sum(1 for t, _, k in GT3 if any(x in near(lambda i: res.get(i, ""), t) for x in k))
    print(f"\nGT 10항목:  현행 {cur}/10   →   Omni {omn}/10")
    for t, ans, k in GT3:
        a = any(x in near(lambda i: fin.get(i, ""), t) for x in k)
        b = any(x in near(lambda i: res.get(i, ""), t) for x in k)
        if a != b:
            print(f"  [{t//60}:{t%60:02d}] {ans:<14} 현행 {'O' if a else 'X'} → Omni {'O' if b else 'X'}")


if __name__ == "__main__":
    asyncio.run(main())
