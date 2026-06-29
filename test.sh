#!/bin/bash

curl -sS -X POST http://localhost:19010/api/v1/stt_svc -H 'Content-Type: application/json' -d '{"v_id":2,"file_path":"vod/2/2.mp4"}'


