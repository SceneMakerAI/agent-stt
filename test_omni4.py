"""Qwen3-Omni 단독 교정 — Qwen3.6 correct 단계를 대체할 수 있는지.

test_omni3 은 '전사' 프롬프트(들리는 대로 적어라)였다. 여기선 '교정' 프롬프트로 바꿔
명단·용어집을 지키게 하고, 현행(Qwen3.6 correct) 결과와 같은 GT 로 채점한다.

    python3 test_omni4.py [초]      # 기본 180초
"""
import asyncio
import base64
import io
import json
import re
import sys
import time
import wave

import httpx

OMNI_URL = "http://3.39.52.226:8000/v1/chat/completions"
OMNI_MODEL = "omni"
AG = "output/1"
WAV = "/stg/vod/scenemaker/1/audio.wav"
PAD = 0.3
CONC = 8
TIMEOUT = 300.0

SYSTEM = """너는 야구 중계 자막 교정기다. 실제 오디오와, 두 음성인식 시스템의 초안 [A], [B] 가 주어진다.

[교정 절차 — 반드시 이 순서로]
1) 오디오를 듣는다. [A] 와 [B] 가 다른 자리마다 실제로 뭐라고 말했는지 확인해 맞는 쪽을 택한다.
   둘 다 틀렸으면 들리는 대로 적는다. 안 들리면 [A] 를 유지한다.
2) 사람 이름은 아래 [등장인물] 표기를 따른다. **명단에 있는 이름이 [A] 에 이미 정확히
   적혀 있으면 절대 바꾸지 않는다.** 명단에 없는 이름을 지어내지 않는다.
3) 야구 용어는 아래 [야구 용어] 표기를 따른다. 발음만 비슷하게 적혔으면 그 표기로 바로잡는다.
4) 남은 오탈자·맞춤법을 고친다. 숫자 표기는 [A] 를 따른다.

[지킬 것]
- **[A] 에 있는 내용을 빠뜨리지 마라.** 안 들려도 지우지 말고 [A] 를 그대로 둔다.
- 이 구간에 없는 말(앞뒤 구간의 말)을 끌어오지 마라.
- 요약하지 말고 말한 그대로 적는다.

[출력] 교정된 자막 텍스트만. 설명·따옴표·머리말 없이."""

GT3 = [
    (33,  "구톰슨",      ["구톰슨"]),
    (44,  "조심할",      ["조심할"]),
    (44,  "그런 회가",   ["그런 회"]),
    (62,  "선두 타자가", ["선두 타자"]),
    (74,  "정근우 타자", ["정근우 타자", "좋은 정근우"]),
    (136, "저지를 했기", ["저지를"]),
    (155, "타석에는",    ["타석에"]),
    (164, "2루에 갖다",  ["2루에 갖다", "2루에다", "이루에"]),
    (171, "두고 공격",   ["두고 공격"]),
    (179, "볼카운트",    ["볼카운트", "볼 카운트"]),
]


def _sec(t: str) -> float:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def clip_b64(start: float, end: float) -> str:
    with wave.open(WAV, "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        w.setpos(max(0, int((start - PAD) * sr)))
        frames = w.readframes(int((end - start + PAD * 2) * sr))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as o:
        o.setnchannels(ch); o.setsampwidth(sw); o.setframerate(sr)
        o.writeframes(frames)
    return base64.b64encode(buf.getvalue()).decode()


def top_names(roster: str, texts: str, n: int = 40) -> list[str]:
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
                            f"오디오를 듣고 절차대로 교정한 자막을 적어라."}]}]}
        async with sem:
            try:
                r = await http.post(OMNI_URL, json=body)
                r.raise_for_status()
                return s["idx"], r.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:  # noqa: BLE001 — 구간 단위 격리
                return s["idx"], f"(실패: {e})"

    t0 = time.time()
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        res = dict(await asyncio.gather(*[one(http, s) for s in segs]))
    print(f"소요 {time.time()-t0:.0f}초")

    with open(f"{AG}/omni_fix.txt", "w") as f:
        f.write(f"0~{limit:.0f}초 — Omni 단독 교정 vs 현행(Qwen3.6 correct)\n" + "=" * 104 + "\n")
        for s in segs:
            i = s["idx"]
            f.write(f"\n[idx {i}] {s['start']}\n  Q   : {s['text']}\n")
            if i in wh:
                f.write(f"  B   : {wh[i]}\n")
            f.write(f"  현행 : {fin.get(i, '')}\n  Omni: {res.get(i, '')}\n")
    print(f"saved {AG}/omni_fix.txt")

    def near(get, t):
        return " ".join(get(s["idx"]) for s in segs
                        if _sec(s["end"]) >= t - 2 and _sec(s["start"]) <= t + 8)
    cur = sum(1 for t, _, k in GT3 if any(x in near(lambda i: fin.get(i, ""), t) for x in k))
    omn = sum(1 for t, _, k in GT3 if any(x in near(lambda i: res.get(i, ""), t) for x in k))
    print(f"\nGT 10항목:  현행 {cur}/10   →   Omni {omn}/10")

    # 앞서 확인된 개악 4곳 점검
    print("\n[개악 점검]")
    for i, want, bad in [(11, "이용규", "이영규"), (18, "퀵모션", "킥모션"),
                         (14, "53개", None), (13, "우익 플라이", "우익스플라이")]:
        o = res.get(i, "")
        ok = (want in o) if want else False
        print(f"  idx {i:>3}  {'O' if ok else 'X'}  {o[:88]}")


if __name__ == "__main__":
    asyncio.run(main())
