"""이미지 갈래 산출물 — 값만 담는다. 함수는 두지 않는다.

워커 결과를 **가공 없이** 그대로 담는다. 음성 갈래와 다른 점이 이것이다 — 대사는 교정·필터를
거치며 모양이 바뀌지만, 프레임 검출 결과는 받은 그대로 DB(t_frame_*)로 간다.
그래서 svc 전용 타입을 새로 만들지 않고 client 의 Video 를 그대로 쓴다.
"""
from dataclasses import dataclass

from lib.client.img_detect.baseball import Video


@dataclass
class ImageOut:
    """영상 하나의 이미지 갈래 결과.

    video 가 None 이면 검출을 못 한 것이다 — 프레임이 없거나, 워커가 거절했거나,
    종목이 미지원이거나. 이미지 갈래는 옵션이라 None 이어도 음성 결과는 저장된다.
    """
    video: Video | None = None
