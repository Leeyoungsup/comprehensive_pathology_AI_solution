"""
WSI Tile Manager
Tile-based rendering system inspired by ASAP's TileManager
"""

import openslide
import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal, QThread, QRect, QRectF, QTimer
from PyQt5.QtGui import QImage, QPixmap
from PIL import ImageCms
from collections import OrderedDict
import threading
import os

class TileCache:
    """Tile cache management (inspired by ASAP's WSITileGraphicsItemCache)
    Memory-efficient management with per-level size limits.
    Uses per-level OrderedDict for O(1) eviction.
    """

    def __init__(self, max_tiles_per_level=None):
        # Per-level LRU caches — O(1) eviction per level
        self._level_caches = {}  # {level: OrderedDict{(tx, ty): pixmap}}

        if max_tiles_per_level is None:
            self.max_tiles_per_level = {
                0: 500,
                1: 800,
                2: 1200,
                3: 2000,
            }
        else:
            self.max_tiles_per_level = max_tiles_per_level

        self.lock = threading.Lock()
        self.total_evictions = 0

    def _get_level_cache(self, level):
        if level not in self._level_caches:
            self._level_caches[level] = OrderedDict()
        return self._level_caches[level]

    def get(self, key):
        """Get tile from cache"""
        tile_x, tile_y, level = key
        with self.lock:
            lc = self._level_caches.get(level)
            if lc is not None:
                tile_key = (tile_x, tile_y)
                if tile_key in lc:
                    lc.move_to_end(tile_key)
                    return lc[tile_key]
        return None

    def put(self, key, pixmap):
        """Store tile in cache (with per-level size limit, O(1) eviction)"""
        tile_x, tile_y, level = key
        tile_key = (tile_x, tile_y)

        with self.lock:
            lc = self._get_level_cache(level)

            if tile_key in lc:
                lc.move_to_end(tile_key)
                return

            max_for_level = self.max_tiles_per_level.get(level, self.max_tiles_per_level[3])

            if len(lc) >= max_for_level:
                lc.popitem(last=False)  # O(1) eviction of oldest
                self.total_evictions += 1

            lc[tile_key] = pixmap

    def get_all_keys(self):
        """Return all cache keys"""
        with self.lock:
            keys = []
            for level, lc in self._level_caches.items():
                for (tx, ty) in lc:
                    keys.append((tx, ty, level))
            return keys

    def get_stats(self):
        """Return cache statistics"""
        with self.lock:
            level_counts = {lvl: len(lc) for lvl, lc in self._level_caches.items()}
            return {
                'total_tiles': sum(level_counts.values()),
                'level_counts': level_counts,
                'total_evictions': self.total_evictions
            }

    def clear(self):
        """Clear cache"""
        with self.lock:
            self._level_caches.clear()

    def clear_all(self):
        """Clear all caches"""
        self.clear()


class TileLoader(QThread):
    """Tile loading worker thread (inspired by ASAP's IOWorker)
    Uses event-driven queue (no polling) and set-based dedup for O(1) checks.
    """

    tileLoaded = pyqtSignal(QPixmap, int, int, int)  # pixmap, tile_x, tile_y, level

    def __init__(self, slide_path, tile_size=512, icc_transform=None, calibration_flat_lut=None):
        super().__init__()
        self.slide_path = slide_path
        self._slide = None
        self.tile_size = tile_size
        self.icc_transform = icc_transform
        self.calibration_flat_lut = calibration_flat_lut
        # Deque-like list for ordered tasks + set for O(1) dedup
        self.tasks = []
        self._task_set = set()
        self.running = True
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)

    def add_task(self, tile_x, tile_y, level, priority=False):
        """Add tile loading task (priority=True inserts at front of queue)"""
        with self.lock:
            task = (tile_x, tile_y, level)
            if task not in self._task_set:  # O(1) lookup
                self._task_set.add(task)
                if priority:
                    self.tasks.insert(0, task)
                else:
                    self.tasks.append(task)
                self.condition.notify()

    def flush_tasks(self):
        """Remove all pending tasks"""
        with self.lock:
            self.tasks.clear()
            self._task_set.clear()

    def run(self):
        """Worker thread execution - event-driven, no polling"""
        try:
            self._slide = openslide.OpenSlide(self.slide_path)
        except Exception as e:
            print(f"TileLoader failed to open OpenSlide: {e}")
            return
        try:
            while self.running:
                task = None
                with self.lock:
                    while not self.tasks and self.running:
                        self.condition.wait()  # Block until notified — no timeout polling
                    if self.tasks:
                        task = self.tasks.pop(0)
                        self._task_set.discard(task)

                if task:
                    tile_x, tile_y, level = task
                    pixmap = self.load_tile(tile_x, tile_y, level)
                    if pixmap:
                        self.tileLoaded.emit(pixmap, tile_x, tile_y, level)
        finally:
            if self._slide:
                self._slide.close()
                self._slide = None

    def load_tile(self, tile_x, tile_y, level):
        """Load actual tile"""
        if self._slide is None:
            return None
        try:
            downsample = self._slide.level_downsamples[level]
            x = int(tile_x * self.tile_size * downsample)
            y = int(tile_y * self.tile_size * downsample)

            level_0_width, level_0_height = self._slide.level_dimensions[0]
            if x >= level_0_width or y >= level_0_height:
                return None

            # Read RGBA tile from OpenSlide
            tile = self._slide.read_region(
                (x, y),
                level,
                (self.tile_size, self.tile_size)
            )

            # RGBA to RGB
            tile_rgb = tile.convert('RGB')

            # Apply ICC color profile (slide → sRGB)
            if self.icc_transform:
                ImageCms.applyTransform(tile_rgb, self.icc_transform, inPlace=True)

            # Apply Aperio calibration
            if self.calibration_flat_lut is not None:
                tile_rgb = tile_rgb.point(self.calibration_flat_lut)

            # PIL → QPixmap: single-copy path via QImage
            width, height = tile_rgb.size
            raw = tile_rgb.tobytes("raw", "RGB")
            q_image = QImage(raw, width, height, width * 3, QImage.Format_RGB888)
            return QPixmap.fromImage(q_image)

        except Exception as e:
            print(f"Failed to load tile ({tile_x}, {tile_y}, level {level}): {e}")
            return None

    def stop(self):
        """Stop worker thread"""
        self.running = False
        with self.lock:
            self.condition.notify()


class WSITileManager(QObject):
    """WSI Tile Manager (inspired by ASAP's TileManager)"""

    tilesUpdated = pyqtSignal()

    def __init__(self, slide_path, tile_size=512, num_workers=8):
        super().__init__()
        self.slide = None
        self.slide_path = slide_path
        self.tile_size = tile_size
        self.cache = TileCache()  # Automatic per-level size management

        # Track tiles being loaded (prevent duplicate loading)
        self.loading_tiles = set()
        self.loading_lock = threading.Lock()

        # Track previously loaded level (for level change detection)
        self.last_loaded_level = -1

        # 4-stage level mapping
        self.level_stages = []  # [level0, level1, level2, level3]

        # ICC color profile transform (slide color space → sRGB)
        self.icc_transform = None
        # Aperio calibration LUT (white balance + gamma correction)
        self.calibration_lut = None
        self.calibration_flat_lut = None

        # Open WSI with OpenSlide
        try:
            self.slide = openslide.OpenSlide(slide_path)
            self._setup_level_stages()
            self.mpp = self._read_mpp()
            self._build_icc_transform()
            self._build_calibration_lut()
        except Exception as e:
            raise

        # Create worker threads (each worker opens independent OpenSlide)
        self.workers = []
        for _ in range(num_workers):
            worker = TileLoader(slide_path, tile_size, self.icc_transform, self.calibration_flat_lut)
            worker.tileLoaded.connect(self.on_tile_loaded)
            worker.start()
            self.workers.append(worker)

        self.current_worker_idx = 0

        # Tile update batch timer (~60fps): only refresh once even if multiple tiles load consecutively
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(16)
        self._update_timer.timeout.connect(self.tilesUpdated)

    def _read_mpp(self):
        """Read slide MPP (um/px). Defaults to 0.25 if metadata is missing."""
        try:
            val = self.slide.properties.get('openslide.mpp-x')
            if val is not None:
                mpp = float(val)
                if mpp > 0:
                    return mpp
        except (ValueError, TypeError):
            pass
        return 0.25  # Default (based on 40x scan)

    def _build_icc_transform(self):
        """Build ICC color profile transform (slide → sRGB)"""
        try:
            icc_profile = self.slide.color_profile
            if icc_profile:
                srgb_profile = ImageCms.createProfile("sRGB")
                self.icc_transform = ImageCms.buildTransform(
                    icc_profile, srgb_profile, "RGB", "RGB"
                )
        except Exception as e:
            print(f"ICC profile not applied: {e}")
            self.icc_transform = None

    def _build_calibration_lut(self):
        """Build Aperio calibration LUT (white balance + gamma correction)

        Produces:
          - calibration_lut: (3, 256) NumPy array for thumbnail rendering
          - calibration_flat_lut: flat list of 768 ints for PIL Image.point() (tile rendering)
        """
        try:
            props = self.slide.properties
            avg_r = props.get('aperio.CalibrationAverageRed')
            avg_g = props.get('aperio.CalibrationAverageGreen')
            avg_b = props.get('aperio.CalibrationAverageBlue')
            gamma = props.get('aperio.Gamma')

            if avg_r is None or gamma is None:
                return

            avg_r, avg_g, avg_b = float(avg_r), float(avg_g), float(avg_b)
            gamma = float(gamma)

            # White balance: normalize each channel so calibration average → 255
            # Gamma correction: apply inverse gamma then re-encode
            lut = np.zeros((3, 256), dtype=np.uint8)
            for ch, avg in enumerate([avg_r, avg_g, avg_b]):
                scale = 255.0 / max(avg, 1.0)
                for i in range(256):
                    linear = (i / 255.0) ** gamma
                    corrected = min(linear * scale, 1.0)
                    lut[ch, i] = int(corrected ** (1.0 / gamma) * 255.0 + 0.5)

            self.calibration_lut = lut
            # Flat LUT for PIL Image.point(): [R0..R255, G0..G255, B0..B255]
            self.calibration_flat_lut = (
                lut[0].tolist() + lut[1].tolist() + lut[2].tolist()
            )
        except Exception as e:
            print(f"Aperio calibration not applied: {e}")
            self.calibration_lut = None
            self.calibration_flat_lut = None

    def _setup_level_stages(self):
        """Set up 4-stage level mapping"""
        if not self.slide:
            return

        total_levels = self.slide.level_count
        self.level_stages = [0, 0, 0, 0]
        if total_levels == 1:
            # If only 1 level, all stages are the same
            self.level_stages = [0, 0, 0, 0]
        elif total_levels == 2:
            self.level_stages = [0, 0, 1, 1]
        elif total_levels == 3:
            self.level_stages = [0, 1, 2, 2]
        elif total_levels >= 4:
            # If 4 or more, distribute evenly
            step = (total_levels - 1) / 3.0
            self.level_stages = [
                0,  # Highest magnification
                int(round(step)),
                int(round(step * 2)),
                min(total_levels - 1, int(round(step * 3)))  # Lowest magnification
            ]

    def get_stage_level(self, effective_mpp):
        """Select 4-stage tile level based on effective MPP (um/px).
        Switches at the same physical resolution thresholds regardless of slide size/MPP.

        Thresholds (based on cell diameter ~10-20 um):
          < 2  um/px : Individual cells identifiable  -> level 0 (highest resolution)
          < 15 um/px : Tissue structure level         -> level 1
          < 100um/px : Overall tissue overview        -> level 2
          >= 100um/px: Whole slide view               -> level 3
        """
        if not self.level_stages:
            return 0

        if effective_mpp < 2.0:
            return self.level_stages[0]
        elif effective_mpp < 15.0:
            return self.level_stages[1]
        elif effective_mpp < 100.0:
            return self.level_stages[2]
        else:
            return self.level_stages[3]

    def get_level_count(self):
        """Return level count"""
        return self.slide.level_count if self.slide else 0

    def get_level_dimensions(self, level):
        """Return dimensions for a specific level"""
        if self.slide and 0 <= level < self.slide.level_count:
            return self.slide.level_dimensions[level]
        return (0, 0)

    def get_level_downsample(self, level):
        """Return downsample factor for a specific level"""
        if self.slide and 0 <= level < self.slide.level_count:
            return self.slide.level_downsamples[level]
        return 1.0

    def get_best_level_for_downsample(self, downsample):
        """Find the best level for the given downsample factor"""
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

    def flush_all_workers(self):
        """Remove all pending tasks from workers (flush stale requests)"""
        for worker in self.workers:
            worker.flush_tasks()
        with self.loading_lock:
            self.loading_tiles.clear()

    def load_tiles_for_view(self, view_rect, level, force_reload=False):
        """Load tiles needed for the view area (prioritize visible area tiles)"""
        if not self.slide:
            return

        downsample = self.get_level_downsample(level)
        tile_size_at_level = self.tile_size

        # Visible area tile indices
        visible_start_x = max(0, int(view_rect.left() / downsample / tile_size_at_level))
        visible_start_y = max(0, int(view_rect.top() / downsample / tile_size_at_level))
        visible_end_x = int(view_rect.right() / downsample / tile_size_at_level) + 1
        visible_end_y = int(view_rect.bottom() / downsample / tile_size_at_level) + 1

        # Check if all visible area tiles are cached
        all_tiles_cached = True
        for ty in range(visible_start_y, visible_end_y):
            for tx in range(visible_start_x, visible_end_x):
                if self.cache.get((tx, ty, level)) is None:
                    all_tiles_cached = False
                    break
            if not all_tiles_cached:
                break

        # Detect level change
        level_changed = (self.last_loaded_level != level)

        if all_tiles_cached and not level_changed:
            return

        if level_changed:
            # Flush stale tasks from previous level on level change
            self.flush_all_workers()
            self.last_loaded_level = level

        # Buffer range (smaller buffer since 512px tiles are more numerous)
        buffer_tiles = 2
        start_tile_x = max(0, visible_start_x - buffer_tiles)
        start_tile_y = max(0, visible_start_y - buffer_tiles)
        end_tile_x = visible_end_x + buffer_tiles
        end_tile_y = visible_end_y + buffer_tiles

        level_width, level_height = self.get_level_dimensions(level)
        level_width_in_tiles = (level_width + self.tile_size - 1) // self.tile_size
        level_height_in_tiles = (level_height + self.tile_size - 1) // self.tile_size

        def _request_tile(tx, ty, priority):
            if tx >= level_width_in_tiles or ty >= level_height_in_tiles:
                return
            cache_key = (tx, ty, level)
            if self.cache.get(cache_key) is not None:
                return
            with self.loading_lock:
                if cache_key in self.loading_tiles:
                    return
                self.loading_tiles.add(cache_key)
            worker = self.workers[self.current_worker_idx]
            worker.add_task(tx, ty, level, priority=priority)
            self.current_worker_idx = (self.current_worker_idx + 1) % len(self.workers)

        # Phase 1: Visible area tiles first (priority=True -> insert at front of queue)
        for ty in range(visible_start_y, visible_end_y):
            for tx in range(visible_start_x, visible_end_x):
                _request_tile(tx, ty, priority=True)

        # Phase 2: Buffer tiles (priority=False -> append to end of queue)
        for ty in range(start_tile_y, end_tile_y):
            for tx in range(start_tile_x, end_tile_x):
                if visible_start_x <= tx < visible_end_x and visible_start_y <= ty < visible_end_y:
                    continue  # Already processed in phase 1
                _request_tile(tx, ty, priority=False)


    def get_tile(self, tile_x, tile_y, level):
        """Get tile from cache"""
        cache_key = (tile_x, tile_y, level)
        return self.cache.get(cache_key)

    def on_tile_loaded(self, pixmap, tile_x, tile_y, level):
        """Called when tile loading is complete"""
        cache_key = (tile_x, tile_y, level)

        # Remove loading indicator
        with self.loading_lock:
            self.loading_tiles.discard(cache_key)

        # Store in cache
        self.cache.put(cache_key, pixmap)

        # Start batch timer if inactive (refresh only once even if multiple tiles arrive within 16ms)
        if not self._update_timer.isActive():
            self._update_timer.start()

    def get_cached_tiles_info(self):
        """Return cached tile info (for minimap)"""
        cached_tiles = []
        for key in self.cache.get_all_keys():
            tx, ty, level = key
            downsample = self.get_level_downsample(level)
            cached_tiles.append((tx, ty, level, downsample))
        return cached_tiles

    def get_thumbnail(self, max_size=(400, 400)):
        """Return thumbnail image (for minimap)"""
        if not self.slide:
            return None

        try:
            thumbnail = self.slide.get_thumbnail(max_size)
            thumbnail_rgb = thumbnail.convert('RGB')

            # Apply ICC color profile (slide → sRGB)
            if self.icc_transform:
                ImageCms.applyTransform(thumbnail_rgb, self.icc_transform, inPlace=True)

            thumbnail_array = np.array(thumbnail_rgb)

            # Apply Aperio calibration (white balance + gamma)
            if self.calibration_lut is not None:
                thumbnail_array[:, :, 0] = self.calibration_lut[0][thumbnail_array[:, :, 0]]
                thumbnail_array[:, :, 1] = self.calibration_lut[1][thumbnail_array[:, :, 1]]
                thumbnail_array[:, :, 2] = self.calibration_lut[2][thumbnail_array[:, :, 2]]

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
            print(f"Failed to generate thumbnail: {e}")
            return None

    def get_slide_info(self):
        """Return slide information"""
        if not self.slide:
            return None

        info = {}

        # Basic information
        info['filename'] = os.path.basename(self.slide_path)
        info['level_count'] = self.slide.level_count
        info['dimensions'] = self.slide.level_dimensions[0]

        # MPP (Microns Per Pixel) information
        properties = self.slide.properties
        if 'openslide.mpp-x' in properties:
            info['mpp_x'] = float(properties['openslide.mpp-x'])
            info['mpp_y'] = float(properties['openslide.mpp-y'])
        else:
            info['mpp_x'] = None
            info['mpp_y'] = None

        # Magnification information
        if 'openslide.objective-power' in properties:
            info['objective_power'] = properties['openslide.objective-power']
        else:
            info['objective_power'] = 'Unknown'

        # Vendor information
        if 'openslide.vendor' in properties:
            info['vendor'] = properties['openslide.vendor']
        else:
            info['vendor'] = 'Unknown'

        # Per-level dimensions
        info['level_dimensions'] = list(self.slide.level_dimensions)
        info['level_downsamples'] = list(self.slide.level_downsamples)

        return info

    def close(self):
        """Clean up resources"""
        # Stop worker threads
        for worker in self.workers:
            worker.stop()
        for worker in self.workers:
            worker.wait()

        # Clear cache
        self.cache.clear_all()

        # Clear loading indicators
        with self.loading_lock:
            self.loading_tiles.clear()

        # Close slide
        if self.slide:
            self.slide.close()
            self.slide = None
