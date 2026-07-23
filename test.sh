#!/bin/bash
# ① 1차 공정 (stt_svc) — prep(ffmpeg) → STT → 명단검색(web_search) → 교정 → t_dialogue 저장 → vision 트리거
#    title/category/year 는 실제 v_id 영상에 맞게 조정 (스포츠·드라마면 명단 검색이 돎)
curl -sS -X POST http://localhost:19010/api/v1/stt_svc -H 'Content-Type: application/json' \
  -d '{"v_id":1,"file_path":"vod/1/1.mp4","title":"코리안시리즈 KIA vs SK","category":"스포츠-야구","year":2009}'

# ② 2차 공정 (stt_cast) — 화자 매칭 + 대사 이름 정정 → t_dialogue_refine 저장
#    (vision 완료 후 콜백으로 오는 요청. 입력은 v_id 하나, 나머지는 DB 조회)
curl -sS -X POST http://localhost:19010/api/v1/refine_svc -H 'Content-Type: application/json' -d '{"v_id":2}'

