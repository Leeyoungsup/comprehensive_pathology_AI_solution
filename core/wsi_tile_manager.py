"""
WSI 타일 매니저
ASAP의 TileManager를 참고한 타일 기반 렌더링 시스템
"""

import openslide
import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal, QThread, QRect, QRectF
from PyQt5.QtGui import QImage, QPixmap
from collections import OrderedDict
import threading


class TileCache:
    """타일 캐시 관리 (ASAP의 WSITileGraphicsItemCache 참고)
    레벨별 크기 제한으로 메모리 효율적 관리
    """
    
    def __init__(self, max_tiles_per_level=None):
        # 레벨별 LRU 캐시
        self.cache = OrderedDict()  # {(tx, ty, level): pixmap}
        
        # 레벨별 최대 타일 수 (고해상도는 적게, 저해상도는 많이)
        if max_tiles_per_level is None:
            self.max_tiles_per_level = {
                0: 500,   # 레벨 0 (최고 해상도): 500타일 (512x512x4 bytes ≈ 500MB)
                1: 800,   # 레벨 1: 800타일
                2: 1200,  # 레벨 2: 1200타일
                3: 2000,  # 레벨 3+ (저해상도): 2000타일
            }
        else:
            self.max_tiles_per_level = max_tiles_per_level
        
        # 레벨별 현재 타일 수 추적
        self.level_counts = {0: 0, 1: 0, 2: 0, 3: 0}
        self.lock = threading.Lock()
        self.total_evictions = 0
    
    def get(self, key):
        """캐시에서 타일 가져오기"""
        with self.lock:
            if key in self.cache:
                # LRU: 최근 사용된 항목을 끝으로 이동
                self.cache.move_to_end(key)
                return self.cache[key]
        return None
    
    def put(self, key, pixmap):
        """캐시에 타일 저장 (레벨별 크기 제한 적용)"""
        tile_x, tile_y, level = key
        
        with self.lock:
            # 이미 있으면 위치만 업데이트
            if key in self.cache:
                self.cache.move_to_end(key)
                return
            
            # 해당 레벨의 최대 크기 확인
            max_for_level = self.max_tiles_per_level.get(level, self.max_tiles_per_level[3])
            
            # 해당 레벨의 타일이 한계를 초과하면 가장 오래된 타일 제거
            if self.level_counts.get(level, 0) >= max_for_level:
                self._evict_oldest_tile_for_level(level)
            
            # 새 타일 추가
            self.cache[key] = pixmap
            self.level_counts[level] = self.level_counts.get(level, 0) + 1
    
    def _evict_oldest_tile_for_level(self, target_level):
        """특정 레벨의 가장 오래된 타일 제거"""
        # 해당 레벨의 타일 찾기 (오래된 순서)
        for key in list(self.cache.keys()):
            tx, ty, level = key
            if level == target_level:
                del self.cache[key]
                self.level_counts[level] -= 1
                self.total_evictions += 1
                if self.total_evictions % 100 == 0:  # 100개마다 로그
                    print(f"  [캐시 관리] 레벨 {level} 타일 제거 (total evictions: {self.total_evictions})")
                return
    
    def get_all_keys(self):
        """모든 캐시 키 반환"""
        with self.lock:
            return list(self.cache.keys())
    
    def get_stats(self):
        """캐시 통계 반환"""
        with self.lock:
            return {
                'total_tiles': len(self.cache),
                'level_counts': dict(self.level_counts),
                'total_evictions': self.total_evictions
            }
    
    def clear(self):
        """캐시 초기화"""
        with self.lock:
            self.cache.clear()
            self.level_counts = {0: 0, 1: 0, 2: 0, 3: 0}
    
    def clear_all(self):
        """모든 캐시 초기화"""
        self.clear()


class TileLoader(QThread):
    """타일 로딩 워커 스레드 (ASAP의 IOWorker 참고)"""
    
    tileLoaded = pyqtSignal(QPixmap, int, int, int)  # pixmap, tile_x, tile_y, level
    
    def __init__(self, slide, tile_size=1024):
        super().__init__()
        self.slide = slide
        self.tile_size = tile_size
        self.tasks = []
        self.running = True
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
    
    def add_task(self, tile_x, tile_y, level):
        """타일 로딩 태스크 추가"""
        with self.lock:
            task = (tile_x, tile_y, level)
            if task not in self.tasks:
                self.tasks.append(task)
                self.condition.notify()
    
    def run(self):
        """워커 스레드 실행"""
        while self.running:
            task = None
            with self.lock:
                if self.tasks:
                    task = self.tasks.pop(0)
                else:
                    self.condition.wait(timeout=0.1)
            
            if task:
                tile_x, tile_y, level = task
                pixmap = self.load_tile(tile_x, tile_y, level)
                if pixmap:
                    self.tileLoaded.emit(pixmap, tile_x, tile_y, level)
    
    def load_tile(self, tile_x, tile_y, level):
        """실제 타일 로딩"""
        try:
            # 이미지 좌표 계산
            downsample = self.slide.level_downsamples[level]
            x = int(tile_x * self.tile_size * downsample)
            y = int(tile_y * self.tile_size * downsample)
            
            print(f"    타일 로딩 중: ({tile_x}, {tile_y}, level {level}) -> 좌표 ({x}, {y})")
            
            # 타일 읽기
            tile = self.slide.read_region(
                (x, y), 
                level, 
                (self.tile_size, self.tile_size)
            )
            
            # RGBA to RGB 변환
            tile_rgb = tile.convert('RGB')
            
            # NumPy 배열로 변환
            tile_array = np.array(tile_rgb)
            
            # QImage로 변환
            height, width, channel = tile_array.shape
            bytes_per_line = 3 * width
            q_image = QImage(
                tile_array.data, 
                width, 
                height, 
                bytes_per_line, 
                QImage.Format_RGB888
            )
            
            # QPixmap으로 변환
            return QPixmap.fromImage(q_image.copy())
            
        except Exception as e:
            print(f"타일 로딩 실패 ({tile_x}, {tile_y}, level {level}): {e}")
            return None
    
    def stop(self):
        """워커 스레드 종료"""
        self.running = False
        with self.lock:
            self.condition.notify()


class WSITileManager(QObject):
    """WSI 타일 매니저 (ASAP의 TileManager 참고)"""
    
    tilesUpdated = pyqtSignal()
    
    def __init__(self, slide_path, tile_size=1024, num_workers=4):
        super().__init__()
        self.slide = None
        self.slide_path = slide_path
        self.tile_size = tile_size
        self.cache = TileCache()  # 레벨별 자동 크기 관리
        
        # 로딩 중인 타일 추적 (중복 로딩 방지)
        self.loading_tiles = set()
        self.loading_lock = threading.Lock()
        
        # 4단계 레벨 매핑
        self.level_stages = []  # [레벨0, 레벨1, 레벨2, 레벨3]
        
        # OpenSlide로 WSI 열기
        try:
            self.slide = openslide.OpenSlide(slide_path)
            self._setup_level_stages()
            print(f"WSI 로딩 완료: {slide_path}")
            print(f"  - 총 레벨 수: {self.slide.level_count}")
            print(f"  - 4단계 레벨 매핑: {self.level_stages}")
        except Exception as e:
            print(f"WSI 로딩 실패: {e}")
            raise
        
        # 워커 스레드 생성
        self.workers = []
        for _ in range(num_workers):
            worker = TileLoader(self.slide, tile_size)
            worker.tileLoaded.connect(self.on_tile_loaded)
            worker.start()
            self.workers.append(worker)
        
        self.current_worker_idx = 0
    
    def _setup_level_stages(self):
        """4단계 레벨 매핑 설정"""
        if not self.slide:
            return
        
        total_levels = self.slide.level_count
        self.level_stages = [0, 0, 0, 0]
        if total_levels == 1:
            # 레벨이 1개만 있으면 모두 동일하게
            self.level_stages = [0, 0, 0, 0]
        elif total_levels == 2:
            self.level_stages = [0, 0, 1, 1]
        elif total_levels == 3:
            self.level_stages = [0, 1, 2, 2]
        elif total_levels >= 4:
            # 4개 이상이면 균등하게 분배
            step = (total_levels - 1) / 3.0
            self.level_stages = [
                0,  # 최고 배율
                int(round(step)),
                int(round(step * 2)),
                min(total_levels - 1, int(round(step * 3)))  # 최저 배율
            ]
    
    def get_stage_level(self, zoom_level):
        """줌 레벨에 따라 4단계 중 하나 선택"""
        if not self.level_stages:
            return 0
        
        # 줌 레벨에 따라 4단계 중 선택
        if zoom_level >= 0.3:
            # 고배율: 레벨 0 (원본)
            return self.level_stages[0]
        elif zoom_level >= 0.03:
            # 중상배율: 레벨 1
            return self.level_stages[1]
        elif zoom_level >= 0.004:
            # 중하배율: 레벨 2
            return self.level_stages[2]
        else:
            # 저배율: 레벨 3
            return self.level_stages[3]
    
    def get_level_count(self):
        """레벨 수 반환"""
        return self.slide.level_count if self.slide else 0
    
    def get_level_dimensions(self, level):
        """특정 레벨의 크기 반환"""
        if self.slide and 0 <= level < self.slide.level_count:
            return self.slide.level_dimensions[level]
        return (0, 0)
    
    def get_level_downsample(self, level):
        """특정 레벨의 다운샘플 배율 반환"""
        if self.slide and 0 <= level < self.slide.level_count:
            return self.slide.level_downsamples[level]
        return 1.0
    
    def get_best_level_for_downsample(self, downsample):
        """다운샘플 배율에 가장 적합한 레벨 찾기"""
        if not self.slide:
            return 0
        
        best_level = 0
        best_diff = abs(self.slide.level_downsamples[0] - downsample)
        
        for level in range(1, self.slide.level_count):
            diff = abs(self.slide.level_downsamples[level] - downsample)
            if diff < best_diff:
                best_level = level
                best_diff = diff
        
        return best_level
    
    def load_tiles_for_view(self, view_rect, level):
        """뷰 영역에 필요한 타일 로딩"""
        if not self.slide:
            return
        
        downsample = self.get_level_downsample(level)
        
        # 타일 인덱스 계산 (보이는 영역보다 넉넉하게 +4 타일)
        tile_size_at_level = self.tile_size
        buffer_tiles = 4  # 각 방향으로 4타일씩 더 로드
        start_tile_x = max(0, int(view_rect.left() / downsample / tile_size_at_level) - buffer_tiles)
        start_tile_y = max(0, int(view_rect.top() / downsample / tile_size_at_level) - buffer_tiles)
        end_tile_x = int(view_rect.right() / downsample / tile_size_at_level) + 1 + buffer_tiles
        end_tile_y = int(view_rect.bottom() / downsample / tile_size_at_level) + 1 + buffer_tiles
        
        print(f"  타일 로딩 요청: x[{start_tile_x}~{end_tile_x}] y[{start_tile_y}~{end_tile_y}], level={level}, downsample={downsample}")
        
        # 타일 로딩 요청
        tiles_requested = 0
        tiles_cached = 0
        for ty in range(start_tile_y, end_tile_y):
            for tx in range(start_tile_x, end_tile_x):
                cache_key = (tx, ty, level)
                
                # 캐시에 있는지 확인
                if self.cache.get(cache_key) is not None:
                    tiles_cached += 1
                    continue
                
                # 이미 로딩 중인지 확인
                with self.loading_lock:
                    if cache_key in self.loading_tiles:
                        continue
                    # 로딩 중으로 표시
                    self.loading_tiles.add(cache_key)
                
                # 캐시에 없고 로딩 중이 아니면 로딩 요청
                worker = self.workers[self.current_worker_idx]
                worker.add_task(tx, ty, level)
                self.current_worker_idx = (self.current_worker_idx + 1) % len(self.workers)
                tiles_requested += 1
        
        if tiles_requested > 0:
            print(f"  -> {tiles_requested}개 타일 로딩 요청됨 (캐시: {tiles_cached}개)")
    
    def get_tile(self, tile_x, tile_y, level):
        """캐시에서 타일 가져오기"""
        cache_key = (tile_x, tile_y, level)
        return self.cache.get(cache_key)
    
    def on_tile_loaded(self, pixmap, tile_x, tile_y, level):
        """타일 로딩 완료 시 호출"""
        cache_key = (tile_x, tile_y, level)
        
        # 로딩 중 표시 제거
        with self.loading_lock:
            self.loading_tiles.discard(cache_key)
        
        # 캐시에 저장
        self.cache.put(cache_key, pixmap)
        
        # 업데이트 시그널 발생
        self.tilesUpdated.emit()
    
    def get_cached_tiles_info(self):
        """캐시된 타일 정보 반환 (미니맵용)"""
        cached_tiles = []
        for key in self.cache.get_all_keys():
            tx, ty, level = key
            downsample = self.get_level_downsample(level)
            cached_tiles.append((tx, ty, level, downsample))
        return cached_tiles
    
    def get_thumbnail(self, max_size=(400, 400)):
        """썸네일 이미지 반환 (미니맵용)"""
        if not self.slide:
            return None
        
        try:
            thumbnail = self.slide.get_thumbnail(max_size)
            thumbnail_rgb = thumbnail.convert('RGB')
            thumbnail_array = np.array(thumbnail_rgb)
            
            height, width, channel = thumbnail_array.shape
            bytes_per_line = 3 * width
            q_image = QImage(
                thumbnail_array.data, 
                width, 
                height, 
                bytes_per_line, 
                QImage.Format_RGB888
            )
            
            return QPixmap.fromImage(q_image.copy())
        except Exception as e:
            print(f"썸네일 생성 실패: {e}")
            return None
    
    def close(self):
        """리소스 정리"""
        # 워커 스레드 종료
        for worker in self.workers:
            worker.stop()
        for worker in self.workers:
            worker.wait()
        
        # 캐시 초기화
        self.cache.clear_all()
        
        # 로딩 중 표시 초기화
        with self.loading_lock:
            self.loading_tiles.clear()
        
        # Slide 닫기
        if self.slide:
            self.slide.close()
            self.slide = None
