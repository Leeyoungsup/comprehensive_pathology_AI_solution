"""앱 설정"""

import os
from pathlib import Path


class Settings:
    # 업로드 디렉토리 (서버 로컬 디스크 — 원본 WSI 저장)
    UPLOAD_DIR: str = os.environ.get(
        "UPLOAD_DIR",
        str(Path(__file__).parent.parent / "uploads")
    )

    # 프리타일 디렉토리 (뷰어용 JPEG 타일 캐시)
    TILES_DIR: str = os.environ.get(
        "TILES_DIR",
        str(Path(__file__).parent.parent / "tiles")
    )

    # 타일 설정
    TILE_SIZE: int = 512
    TILE_FORMAT: str = "JPEG"  # JPEG이 PNG보다 빠르고 작음
    TILE_QUALITY: int = 85

    # 청크 업로드 설정
    CHUNK_SIZE: int = 5 * 1024 * 1024  # 5MB

    # AI 모델 경로 (기존 프로젝트의 model/ 디렉토리)
    MODEL_DIR: str = str(Path(__file__).parent.parent.parent.parent / "model")

    # 지원 확장자
    SUPPORTED_EXTENSIONS: set = {
        ".svs", ".ndpi", ".vms", ".vmu", ".scn",
        ".mrxs", ".tiff", ".tif", ".png", ".jpg", ".jpeg",
    }


settings = Settings()
