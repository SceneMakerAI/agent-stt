# CAST — 2차 화자 매칭·이름 정정 공정 (알고리즘 백업)

vision(화면분석, `t_segment_refine`) 이후 도는 2차 보정 공정. STT 1차 보정본
(`t_dialogue`, status 1006)에 **화자 신원(speaker_name)** 을 채우고 **대사 속 인물 이름
오표기**를 정정해 `t_dialogue_refine` 으로 저장한다. 1차본은 건드리지 않는다.

> 현재 리팩터링에서 cast 는 일단 깨져도 되는 상태로 두고(에러 허용), STT 1차 저장 구조를
> 정리한다. 이 문서는 **재도입할 때 그대로 복원할 수 있도록** 알고리즘·설계 결정만 남긴 것.
> 관련 메모: [[cast-flow-deferred]].

---

## 0. 전체 흐름

```
POST /api/v1/refine_svc {v_id}         (http 핸들러: stt_cast.py, 카운터 +1 후 즉시 응답)
   └─ 백그라운드: svc/cast/process.run(state, v_id)
      1. load    (rdb)      t_video(summary,cate) + t_dialogue + t_segment_refine → CastInput
      2~3. map   (LLM)      증거 압축 → 증거 텍스트          (작으면 원문 직행 / 크면 윈도우 병렬)
      4. reduce  (LLM)      증거 종합 → speaker_map + name_fixes (CastResult, 영상당 1회)
      5. apply   (순수코드)  판정을 대사에 반영 (가드 포함) → FinalRow[]
      6. save    (rdb)      t_dialogue_refine INSERT + status 1016
      7. scenario 트리거     (예정)
```

상태코드: `REFINE_START=1015` (입력) → `REFINE_END=1016` (완료).
실패 시 status 를 -1 로 덮지 **않는다** — 1차 보정본(1006)이 유효하므로 v_id 로 재실행하면 됨.

접수 카운터(`state.current_req_cnt`)는 핸들러가 +1, `process.run` 의 finally 가 -1(성공/실패 무관).

---

## 1. 파일 구조 (부품 분리)

| 파일 | 역할 | 의존 |
|---|---|---|
| `lib/http/stt_cast.py` | http 핸들러 — run 하나만 bg 로 띄움 | process |
| `lib/svc/cast/process.py` | 오케스트레이터 — **순서와 실패정책만**. 로직은 부품 위임 | 전부 |
| `lib/svc/cast/cast_match.py` | map / reduce / apply 3단계 로직 | evidence, prompt, parse, vllm |
| `lib/svc/cast/evidence.py` | DB행 → LLM 입력 텍스트 (순수함수, vllm/rdb 모름) | schema |
| `lib/svc/cast/prompt.py` | 증거 → vLLM messages (SYSTEM_MAP/REDUCE + 장르규칙) | schema |
| `lib/svc/cast/parse.py` | LLM JSON 응답 → 구조체 (검증·환각 필터, 순수함수) | schema |
| `lib/svc/cast/schema.py` | 데이터 계약 (CastInput/Window/Speaker/NameFix/CastResult/FinalRow) | — |

원칙: evidence(무엇을 근거로) · prompt(어떻게 물을지) · parse(응답을 어떻게 읽을지) 세 부품은
서로 모른다. cast_match 는 vllm 은 쓰되 rdb 는 모른다(조회/저장은 process).

---

## 2. 데이터 계약 (schema.py)

- **CastInput** (1단계 조회 출력): `summary`(t_video 줄거리, None 가능), `cate_name`,
  `root_cate_name`(최상위 카테고리 — 장르 프롬프트 분기 키), `dialogues`(t_dialogue 행 dict),
  `segments`(t_segment_refine 행 dict). DB 행은 관례대로 dict 로 흐름(rdb docstring 이 계약).
- **Window** (map 입력): `span`("00:30~"), `d_lines`(대사 라인), `s_lines`(화면분석 라인).
- **Speaker**: `name`(실명 또는 역할), `confidence`(0~1, CAST_CONF_MIN 미만이면 apply 가 '미상').
- **NameFix**: `wrong` → `correct` 문자열 치환 규칙.
- **CastResult** (reduce 출력): `speaker_map`(라벨→Speaker), `name_fixes`(NameFix[]).
- **FinalRow** (apply 출력 = t_dialogue_refine 한 행): idx/start/end/speaker/**speaker_name**/lang/**text**.
  원본 컬럼은 t_dialogue 복사, speaker_name·text 만 교정.

---

## 3. 증거 생성 (evidence.py)

DB 행을 LLM 이 읽을 텍스트로 펼침. 인물 신원 단서가 될 필드만 남겨 입력 압축.

- `_dialogue_line(d)` → `idx|화자라벨|HH:MM:SS|본문` (0.1초 자리·speaker_name 은 증거에 불필요).
- `_segment_line(s)` → `HH:MM:SS|cast|ocr|summary` (다 비면 ""). **sound/action 제외** — 화자
  신원과 대개 무관.
- `size(inp)` = 대사+화면분석 총 글자수. 원문직행/윈도우경유 판단용(≈글자수÷1.5 토큰).
- `direct(inp)` = 전체 대사 + 전체 화면분석 한 블록 (작은 영상).
- `windows(inp)` = 대사·세그먼트를 **같은 시간축** `CAST_WINDOW_SEC` 버킷에 배분(시간순).
  한 윈도우 = 그 구간의 대사 + 그 구간의 화면분석.
- `speaker_stats(dialogues)` = 라벨별 `S009: 580줄, 19607자` 발화량(글자수) 내림차순.
  모델이 스스로 세지 않게 **명시적으로** 준다 → 주요 화자 판단 근거.

---

## 4. map (cast_match.map)

크기 판단 → 증거 텍스트 생성.

```
total = evidence.size(inp)
if total <= CAST_DIRECT_MAX_CHARS:   return evidence.direct(inp)          # 원문 직행
else:                                 윈도우별 _map_window 병렬 → "\n\n".join
```

- `_map_window(w)`: 윈도우 1개 → LLM(thinking **off**, json_object, max_tokens=CAST_MAP_MAX_TOKENS)
  → 화자별 '단서'(결론 아님) 수집. `[구간 {span} 단서]\n{JSON}` 블록 반환.
- **실패는 삼키지 않고 전파** (`asyncio.gather` 그대로). 한 구간(20~30분)을 통째로 빠뜨린 채
  reduce 하면 부분 증거로 화자를 오판(실측: 윈도우 2개 누락 → name_fixes 방향 역전).
  cast 전체가 멈춰도 1차본은 유효 → v_id 재실행.

---

## 5. reduce (cast_match.reduce)

증거 전체 종합 → 전역 판정. 영상당 1회, thinking **on**, max_tokens=CAST_MAX_TOKENS(thinking 예산 포함).

입력: `summary` + `evidence`(map 결과) + `speaker_stats` + `root_cate_name`.
출력: `parse.reduce(text, 실제_라벨_집합)` → CastResult.

**판정 규칙** (prompt.SYSTEM_REDUCE):
1. **호칭/호명이 최우선 증거.** 화면분석·발화시각 정렬은 보조. OCR 이름은 강한 증거.
2. summary 속 이름도 STT 오인식일 수 있음 — 표기 충돌 시 더 자주·일관되게 나오는 쪽.
3. 확신 없으면 이름 지어내지 말고 역할("내레이터"/"해설"/"인터뷰이"/"미상").
4. name_fixes 는 인물 이름 오표기만. 일반 오탈자는 이미 교정됨 → 건드리지 마라.
5. speaker_map 에 입력의 모든 화자 라벨 포함.

---

## 6. 장르 규칙 (prompt.GENRE_RULES) — `root_cate_name` 으로 선택

공통규칙(증거 우선순위/폴백/출력형식)은 SYSTEM_REDUCE 에, 장르별 **역할 어휘·특성만** 여기.
장르는 하나씩 검증하며 추가(없는 장르는 "" → 공통규칙만). 현재 등록: 스포츠/드라마/뉴스.

- **스포츠**: 내레이터 없음 → "캐스터"/"해설"(2~3명이 발화량 대부분). 발화량 상위를 광고/단역
  판정하면 거의 오판. 이름+역할 알면 "백양(캐스터)". 실명은 대사 호명 시에만(세상지식 추측 금지).
  화면 선수명(네임플레이트/라인업/스코어보드)은 최상급 증거. 인터뷰는 OCR 이름/직함 or "인터뷰이".
  중간광고 목소리는 "광고 내레이터".
- **드라마**: 배역 이름(배우 실명 아님). 화면에 이름 거의 없음 → 호칭/호명이 유일한 실명 증거.
  호명 없으면 역할("어머니"/"형사") or "미상"(미상 많은 것 정상). 장면 밖 목소리는 "내레이터".
- **뉴스**: "앵커"(스튜디오)/"기자"(현장). 발화량 상위는 앵커. 기자 이름은 끝인사·OCR 에 자주.
  이름+역할 알면 "최문종(앵커)". 취재원/시민은 OCR 이름 or "인터뷰이".

---

## 7. 응답 파싱 (parse.py)

- `strip_think(text)`: `</think>` 이전(thinking 잔여물) 제거.
- `is_valid_json(text)`: map 응답이 파싱 가능한 JSON 인지만(내용은 reduce 가 종합).
- `reduce(text, labels)` → CastResult 검증:
  - speaker_map: **실제 대사에 있는 라벨만**, name(str)·confidence(0~1 clamp) 타입 강제, 빈 name 스킵.
  - name_fixes: wrong·correct 가 비어있지 않고 서로 다른 쌍만.
  - 판정 누락 라벨은 경고 로그(→ apply 가 '미상' 처리).

---

## 8. apply (cast_match.apply) — 순수 코드, LLM 없음

판정을 대사에 반영해 FinalRow[] 생성.

- **speaker_name**: `confidence >= CAST_CONF_MIN` 만 채택, 미달·미판정은 `"미상"`.
- **text**: `_valid_fixes` 통과한 name_fixes 만 문자열 치환.

### _valid_fixes 가드 (환각 차단 — 핵심)

name_fixes 의 `correct`(정정 결과)가 **'신뢰 증거'에 실존**하는 것만 통과.

```
anchor = summary + 모든 segment 의 cast + 모든 segment 의 ocr   (공백 join)
correct in anchor 이면 채택, 아니면 버림(경고 로그)
```

**대사(STT)는 앵커에서 제외** — 대사에만 있는 이름은 그 자체가 오인식일 수 있어 앵커로 못 씀.
증거에 없는 정정(예: 구톤슨→구원투수, 박지용→김태현)은 환각/엉뚱한 치환이므로 버린다.
(폴백을 코드가 아니라 모델 출력 단계부터 강제 + apply 단계 가드로 이중 차단.)

---

## 9. 저장 (rdb, 6단계)

`insert_refine(vid, rows, code)` — **한 트랜잭션**:
- `t_dialogue_refine` DELETE(vid) 후 일괄 INSERT (멱등). 스키마는 t_dialogue 와 동일 +
  speaker_name 컬럼. 매핑: idx/start/end/speaker/**speaker_name**/lang/**text**
  → idx/start_time/end_time/speaker/speaker_name/lang/dialogue.
- `t_video.status_code` = 1016 갱신.
- 둘 중 하나라도 실패하면 통째 rollback(대사만 들어가고 status 안 바뀌는 불일치 방지).

조회(1단계):
- `load_video(vid)` — t_video ⋈ t_category(자신+부모): `{summary, cate_name, root_cate_name}`.
  root 는 최상위 카테고리("야구"→"스포츠"), 부모 없으면 자신이 최상위.
- `load_dialogues(vid)` — t_dialogue idx 순, 시간컬럼(timedelta)은 'HH:MM:SS.s' 문자열로.
- `load_segments(vid)` — t_segment_refine seg_id 순 (6초 단위 화면분석, agent-vision 산출물):
  seg_id/start/end/summary/cast/ocr/sound/action.

> 재도입 시: 위 rdb 함수들(insert_refine/_insert_refine/load_video/load_dialogues/load_segments)이
> STT 리팩터링에서 제거됐다면 이 문서 기준으로 복원. t_dialogue_refine 저장은 db_svc 패턴
> (테이블별 파일 + 커서 조합)으로 옮기는 것을 권장.

---

## 10. 설정 키 (config)

| 키 | 의미 |
|---|---|
| `CAST_DIRECT_MAX_CHARS` | 이하면 원문 직행, 초과면 윈도우 경유 |
| `CAST_WINDOW_SEC` | map 윈도우 시간 폭 |
| `CAST_MAP_MAX_TOKENS` | map 윈도우 1개 응답 토큰 |
| `CAST_MAX_TOKENS` | reduce 응답 토큰 (thinking 예산 포함) |
| `CAST_CONF_MIN` | speaker_name 채택 최소 confidence (미달 → '미상') |

---

## 11. 실패 원칙 (전체 관통)

1차 보정본이 이미 유효하므로 **cast 실패 < 부분 오염**.
- map 윈도우/reduce 실패 → 예외 전파(부분 증거로 오판하느니 멈춘다).
- process 가 잡아 1차본(1006) 유지, status 를 -1 로 덮지 않음 → v_id 재실행.
- apply 의 _valid_fixes 로 환각 치환 차단(증거 없는 correct 버림).
