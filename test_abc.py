"""A+B+C 교정 — Qwen(A) + whisper(B) + Omni(C) 를 Qwen3.6 correct 에 함께 넣는다.

Omni 는 소리를 잘 듣지만(조심할·타석에는·두고 공격) 명단·용어집을 안 지킨다(이영규·킥모션).
→ 최종본으로 쓰지 말고 '세 번째 의견'으로 넘겨 Qwen3.6 이 명단·용어집으로 걸러내게 한다.

교정 프롬프트는 오늘 실측에서 이긴 '순서 A'(절차 4단계)를 쓴다.

    python3 test_abc.py [초]
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

import config
from lib.svc.stt.correct import prompt_common as P

OMNI_URL = "http://3.39.52.226:8000/v1/chat/completions"
OMNI_MODEL = "omni"
AG = "output/1"
WAV = "/stg/vod/scenemaker/1/audio.wav"
PAD, CONC = 0.3, 8

OMNI_SYS = """너는 야구 중계 오디오를 듣고 자막 초안을 바로잡는 전사기다.
[A], [B] 는 두 음성인식 시스템의 초안이고, 실제 오디오가 함께 주어진다.

오디오를 직접 듣고 그 구간에서 실제로 말한 내용을 한국어로 적어라.
- [A]·[B] 가 다르면 들리는 쪽을 택한다. 둘 다 틀렸으면 들리는 대로 적는다.
- 안 들리는 부분은 [A] 를 그대로 둔다. [A] 의 내용을 빠뜨리지 마라.
- 이 구간에 없는 말을 끌어오지 마라. 요약하지 마라.
[출력] 자막 텍스트만."""

CORRECT_SYS = """너는 한국어 야구 중계 자막(STT 결과) 교정기다. 각 줄은 'idx: 원문' 이고,
아래에 같은 오디오를 다른 시스템이 받아쓴 [B](whisper) 와 [C](오디오를 직접 들은 모델) 가 붙는다.

[교정 절차 — 반드시 이 순서로]
1) 초안 대조 — 원문과 [B]·[C] 가 다른 자리를 하나씩 본다.
   원문이 그 자리에서 뜻이 통하지 않으면(문법이 깨지거나 앞뒤와 안 이어지면) 초안을 택한다.
   [C] 는 실제 오디오를 들은 결과라 소리에 관해서는 [B] 보다 신뢰도가 높다.
   둘 다 말이 되면 원문을 유지한다. 초안에 없는 원문 내용은 지우지 않는다.
2) 이름·자리 확인 — 사람 자리에 이름이 잘못 적혔으면 [참고 명단] 표기로 바꾼다.
   명단에 없는 이름을 지어내지 않는다.
   **서술어(동사·형용사) 자리에 [참고 명단]·[참고 용어] 의 명사가 들어가 있으면 그건 오인식이다.**
   그 명사를 지키지 말고, 발음이 비슷하면서 문맥에 맞는 말로 고쳐라.
   (예: "주심할 필요가 있다" — 주심은 심판을 뜻하는 명사라 서술어 자리에 올 수 없다 → 오인식)
3) 용어집 적용 — [참고 용어] 의 말이 발음만 비슷하게 잘못 적혔으면 그 표기로 바로잡는다.
   단 2에서 서술어 자리로 판정한 곳은 건드리지 않는다.
4) 표기 정리 — 남은 오탈자·맞춤법·띄어쓰기를 고친다.

[지킬 것]
- 입력 줄 수와 순서, idx 를 그대로 유지한다.
- 의미와 말투를 보존한다. 내용을 새로 만들거나 요약하지 않는다.
[출력] 오직 JSON: {"lines":[{"idx":<정수>,"text":"<교정된 본문>"}]}"""

GT3 = [
    (33, "구톰슨", ["구톰슨"]), (44, "조심할", ["조심할"]), (44, "그런 회가", ["그런 회"]),
    (62, "선두 타자가", ["선두 타자"]), (74, "정근우 타자", ["정근우 타자", "좋은 정근우"]),
    (136, "저지를", ["저지를"]), (155, "타석에는", ["타석에"]),
    (164, "2루에 갖다", ["2루에 갖다", "2루에다", "이루에"]),
    (171, "두고 공격", ["두고 공격"]), (179, "볼카운트", ["볼카운트", "볼 카운트"]),
]


def _sec(t: str) -> float:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def clip_b64(a: float, b: float) -> str:
    with wave.open(WAV, "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        w.setpos(max(0, int((a - PAD) * sr)))
        frames = w.readframes(int((b - a + PAD * 2) * sr))
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
    gloss = P.glossary_for("스포츠-야구")
    names = top_names(roster, " ".join(s["text"] for s in raw))
    segs = [s for s in raw if _sec(s["start"]) < limit]

    # ── ① Omni 로 C 초안 생성 (구간별 병렬)
    osys = (f"{OMNI_SYS}\n\n[등장인물]\n{', '.join(names)}\n\n"
            f"[야구 용어]\n{gloss.split(chr(10)+chr(10), 1)[-1]}")
    sem = asyncio.Semaphore(CONC)

    async def omni(http, s):
        body = {"model": OMNI_MODEL, "temperature": 0.2, "max_tokens": 512,
                "messages": [{"role": "system", "content": osys},
                             {"role": "user", "content": [
                                 {"type": "audio_url", "audio_url": {"url":
                                     "data:audio/wav;base64," + clip_b64(_sec(s["start"]), _sec(s["end"]))}},
                                 {"type": "text", "text":
                                     f"[A - Qwen3-ASR]\n{s['text']}\n\n"
                                     f"[B - whisper]\n{wh.get(s['idx'], '(없음)')}\n\n"
                                     f"오디오를 듣고 이 구간의 자막을 정확히 적어라."}]}]}
        async with sem:
            try:
                r = await http.post(OMNI_URL, json=body)
                r.raise_for_status()
                return s["idx"], r.json()["choices"][0]["message"]["content"].strip()
            except Exception:  # noqa: BLE001
                return s["idx"], ""

    t0 = time.time()
    async with httpx.AsyncClient(timeout=300.0) as http:
        C = dict(await asyncio.gather(*[omni(http, s) for s in segs]))
    print(f"① Omni C초안 {len(segs)}구간 {time.time()-t0:.0f}초")

    # ── ② Qwen3.6 correct (A + B + C)
    from openai import AsyncOpenAI
    cli = AsyncOpenAI(base_url=config.VLLM_BASE_URL, api_key="-")
    sysmsg = "\n\n".join([
        CORRECT_SYS,
        "[영상 정보]\n제목: 코리안시리즈 KIA vs SK\n카테고리: 스포츠-야구\n방송연도: 2009",
        gloss.strip(), P.ROSTER_GUIDE.format(roster=roster.strip())])

    async def page(p):
        orig = {s["idx"]: s["text"] for s in p}
        lines = []
        for s in p:
            i = s["idx"]
            lines.append(f'{i}: {s["text"]}')
            if i in wh:
                lines.append(f"    [B] {wh[i]}")
            if C.get(i):
                lines.append(f"    [C] {C[i]}")
        try:
            r = await cli.chat.completions.create(
                model=config.VLLM_MODEL,
                messages=[{"role": "system", "content": sysmsg},
                          {"role": "user", "content":
                              "다음 자막을 교정해서 JSON 으로 반환해.\n\n" + "\n".join(lines)}],
                temperature=0.1, response_format={"type": "json_object"},
                extra_body={"chat_template_kwargs": {"enable_thinking": False}})
            out = {l["idx"]: l["text"] for l in json.loads(r.choices[0].message.content)["lines"]}
            return out if set(out) == set(orig) else orig
        except Exception:  # noqa: BLE001
            return orig

    t0 = time.time()
    pages = [segs[i:i + 30] for i in range(0, len(segs), 30)]
    res = {}
    for r in await asyncio.gather(*[page(p) for p in pages]):
        res.update(r)
    print(f"② Qwen3.6 correct {time.time()-t0:.0f}초")

    with open(f"{AG}/abc_3min.txt", "w") as f:
        f.write(f"0~{limit:.0f}초 — A+B+C 교정 vs 현행\n" + "=" * 104 + "\n")
        for s in segs:
            i = s["idx"]
            f.write(f"\n[idx {i}] {s['start']}\n  Q(A) : {s['text']}\n")
            if i in wh:
                f.write(f"  B    : {wh[i]}\n")
            if C.get(i):
                f.write(f"  C    : {C[i]}\n")
            f.write(f"  현행  : {fin.get(i,'')}\n  ABC  : {res.get(i,'')}\n")
    print(f"saved {AG}/abc_3min.txt")

    def near(get, t):
        return " ".join(get(s["idx"]) for s in segs
                        if _sec(s["end"]) >= t - 2 and _sec(s["start"]) <= t + 8)
    for nm, g in (("현행", lambda i: fin.get(i, "")), ("C만(Omni)", lambda i: C.get(i, "")),
                  ("A+B+C", lambda i: res.get(i, ""))):
        n = sum(1 for t, _, k in GT3 if any(x in near(g, t) for x in k))
        print(f"  {nm:<10} {n}/10")
    print("\n[개악 점검 — A+B+C]")
    for i, want in [(11, "이용규"), (18, "퀵모션"), (14, "53개"), (13, "우익 플라이")]:
        o = res.get(i, "")
        print(f"  idx {i:>3}  {'O' if want in o else 'X'}  {o[:86]}")


if __name__ == "__main__":
    asyncio.run(main())
