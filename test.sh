#!/bin/bash
# 자막 공정 요청 (stt_svc) — 음성 갈래 + 이미지 갈래 병렬 → 둘 다 끝나면 한 트랜잭션 저장
#   무슨 스텝이 도는지는 category 가 정한다 (lib/svc/profile.py 의 표)
#   접수 응답은 즉시 {"v_id":N,"status":"accepted"} — 공정은 백그라운드에서 돈다

# 스포츠-야구 — 검색 O / 2차 전사 O / 야구 용어집 / 요약 ✕ / 이미지 검출 baseball
curl -sS -X POST http://localhost:19010/api/v1/stt_svc -H 'Content-Type: application/json' \
  -d '{"v_id":1,"file_path":"vod/1/1.mp4","title":"코리안시리즈 KIA vs SK","category":"스포츠-야구","year":2009}'

# 다큐 — 검색 ✕ / 2차 전사 ✕ / 요약 O / 이미지 갈래 없음
# curl -sS -X POST http://localhost:19010/api/v1/stt_svc -H 'Content-Type: application/json' \
#   -d '{"v_id":2,"file_path":"vod/2/2.mp4","title":"휴먼다큐 사랑","category":"다큐","year":2015}'
