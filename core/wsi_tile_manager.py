"""
WSI Tile Manager
Tile-based rendering system inspired by ASAP's TileManager
"""

import openslide
import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal, QThread, QRect, QRectF, QTimer
from PyQt5.QtGui import QImage, QPixmap
from collections import OrderedDict
import threading
import os

class TileCache:
    """Tile cache management (inspired by ASAP's WSITileGraphicsItemCache)
    Memory-efficient management with per-level size limits
    """

    def __init__(self, max_tiles_per_level=None):
        # Per-level LRU cache
        self.cache = OrderedDict()  # {(tx, ty, level): pixmap}

        # Max tiles per level (fewer for high resolution, more for low resolution)
        if max_tiles_per_level is None:
            self.max_tiles_per_level = {
                0: 500,   # Level 0 (highest resolution): 500 tiles (512x512x4 bytes ~ 500MB)
                1: 800,   # Level 1: 800 tiles
                2: 1200,  # Level 2: 1200 tiles
                3: 2000,  # Level 3+ (low resolution): 2000 tiles
            }
        else:
            self.max_tiles_per_level = max_tiles_per_level

        # Track current tile count per level
        self.level_counts = {0: 0, 1: 0, 2: 0, 3: 0}
        self.lock = threading.Lock()
        self.total_evictions = 0

    def get(self, key):
        """Get tile from cache"""
        with self.lock:
            if key in self.cache:
                # LRU: Move recently used item to the end
                self.cache.move_to_end(key)
                return self.cache[key]
        return None

    def put(self, key, pixmap):
        """Store tile in cache (with per-level size limit)"""
        tile_x, tile_y, level = key

        with self.lock:
            # If already exists, just update position
            if key in self.cache:
                self.cache.move_to_end(key)
                return

            # Check max size for this level
            max_for_level = self.max_tiles_per_level.get(level, self.max_tiles_per_level[3])

            # Evict oldest tile if level limit exceeded
            if self.level_counts.get(level, 0) >= max_for_level:
                self._evict_oldest_tile_for_level(level)

            # Add new tile
            self.cache[key] = pixmap
            self.level_counts[level] = self.level_counts.get(level, 0) + 1

    def _evict_oldest_tile_for_level(self, target_level):
        """Evict the oldest tile for a specific level"""
        # Find tiles for this level (in oldest-first order)
        for key in list(self.cache.keys()):
            tx, ty, level = key
            if level == target_level:
                del self.cache[key]
                self.level_counts[level] -= 1
                self.total_evictions += 1
                return

    def get_all_keys(self):
        """Return all cache keys"""
        with self.lock:
            return list(self.cache.keys())

    def get_stats(self):
        """Return cache statistics"""
        with self.lock:
            return {
                'total_tiles': len(self.cache),
                'level_counts': dict(self.level_counts),
                'total_evictions': self.total_evictions
            }

    def clear(self):
        """Clear cache"""
        with self.lock:
            self.cache.clear()
            self.level_counts = {0: 0, 1: 0, 2: 0, 3: 0}

    def clear_all(self):
        """Clear all caches"""
        self.clear()


class TileLoader(QThread):
    """Tile loading worker thread (inspired by ASAP's IOWorker)"""

    tileLoaded = pyqtSignal(QPixmap, int, int, int)  # pixmap, tile_x, tile_y, level

    def __init__(self, slide_path, tile_size=512):
        super().__init__()
        self.slide_path = slide_path
        self._slide = None  # Opened exclusively within run() for this thread
        self.tile_size = tile_size
        self.tasks = []
        self.running = True
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)

    def add_task(self, tile_x, tile_y, level, priority=False):
        """Add tile loading task (priority=True inserts at front of queue)"""
        with self.lock:
            task = (tile_x, tile_y, level)
            if task not in self.tasks:
                if priority:
                    self.tasks.insert(0, task)
                else:
                    self.tasks.append(task)
                self.condition.notify()

    def flush_tasks(self):
        """Remove all pending tasks"""
        with self.lock:
            self.tasks.clear()

    def run(self):
        """Worker thread execution - opens thread-exclusive OpenSlide"""
        try:
            self._slide = openslide.OpenSlide(self.slide_path)
        except Exception as e:
            print(f"TileLoader failed to open OpenSlide: {e}")
            return
        try:
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
        finally:
            if self._slide:
                self._slide.close()
                self._slide = None

    def load_tile(self, tile_x, tile_y, level):
        """Load actual tile"""
        if self._slide is None:
            return None
        try:
            # Calculate image coordinates
            downsample = self._slide.level_downsamples[level]
            x = int(tile_x * self.tile_size * downsample)
            y = int(tile_y * self.tile_size * downsample)

            # Slide boundary check (based on level 0)
            level_0_width, level_0_height = self._slide.level_dimensions[0]
            if x >= level_0_width or y >= level_0_height:
                return None

            # Read tile
            tile = self._slide.read_region(
                (x, y),
                level,
                (self.tile_size, self.tile_size)
            )

            # RGBA to RGB conversion
            tile_rgb = tile.convert('RGB')

            # Convert to NumPy array
            tile_array = np.array(tile_rgb)

            # Convert to QImage
            height, width, channel = tile_array.shape
            bytes_per_line = 3 * width
            q_image = QImage(
                tile_array.data,
                width,
                height,
                bytes_per_line,
                QImage.Format_RGB888
            )

            # Convert to QPixmap
            return QPixmap.fromImage(q_image.copy())

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

    def __init__(self, slide_path, tile_size=2048, num_workers=8):
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

        # Open WSI with OpenSlide
        try:
            self.slide = openslide.OpenSlide(slide_path)
            self._setup_level_stages()
            self.mpp = self._read_mpp()
        except Exception as e:
            raise

        # Create worker threads (each worker opens independent OpenSlide)
        self.workers = []
        for _ in range(num_workers):
            worker = TileLoader(slide_path, tile_size)
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

        # Buffer range
        buffer_tiles = 4
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
