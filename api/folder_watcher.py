"""
Folder Watcher (Multi-Instance)

Supports multiple independent watcher instances, each with:
- Its own watch folder
- Configurable GPU device (cuda:0, cuda:1, cpu, ...)
- Tissue type for epithelial reclassification (Breast/Stomach/Other)
- Independent 10-second scan loop + detection pipeline
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Supported slide/image extensions
SUPPORTED_EXTENSIONS = {
    ".svs", ".ndpi", ".vms", ".vmu", ".scn", ".mrxs",
    ".tiff", ".tif", ".png", ".jpg", ".jpeg",
}

# Internal registry filename (per watch folder)
REGISTRY_FILENAME = "_pathology_ai_registry.json"


# ============================================================================
# Slide Registry (per folder)
# ============================================================================

class SlideRegistry:
    """Manages the internal JSON registry of slides for one watch folder."""

    def __init__(self, registry_path: Path):
        self._path = registry_path
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = {"slides": []}
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                if "slides" not in self._data:
                    self._data["slides"] = []
            except (json.JSONDecodeError, OSError):
                self._data = {"slides": []}

    def _save(self):
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"[Registry] Failed to save: {e}")

    def get_all_slides(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._data["slides"])

    def register_slide(self, slide_path: str) -> bool:
        """Register a new slide. Returns True if newly added."""
        with self._lock:
            for entry in self._data["slides"]:
                if entry["slide_path"] == slide_path:
                    return False
            self._data["slides"].append({
                "slide_path": slide_path,
                "file_name": Path(slide_path).name,
                "ai_completed": False,
                "ai_result_path": None,
                "registered_at": datetime.now().isoformat(),
                "completed_at": None,
            })
            self._save()
            return True

    def mark_completed(self, slide_path: str, result_path: str):
        with self._lock:
            for entry in self._data["slides"]:
                if entry["slide_path"] == slide_path:
                    entry["ai_completed"] = True
                    entry["ai_result_path"] = result_path
                    entry["completed_at"] = datetime.now().isoformat()
                    entry.pop("last_error", None)
                    entry.pop("last_error_at", None)
                    break
            self._save()

    def mark_failed(self, slide_path: str, error: str):
        with self._lock:
            for entry in self._data["slides"]:
                if entry["slide_path"] == slide_path:
                    entry["ai_completed"] = False
                    entry["ai_result_path"] = None
                    entry["last_error"] = error
                    entry["last_error_at"] = datetime.now().isoformat()
                    break
            self._save()

    def get_pending_slides(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(e) for e in self._data["slides"] if not e["ai_completed"]]

    @property
    def total_count(self) -> int:
        with self._lock:
            return len(self._data["slides"])

    @property
    def completed_count(self) -> int:
        with self._lock:
            return sum(1 for e in self._data["slides"] if e["ai_completed"])

    @property
    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for e in self._data["slides"] if not e["ai_completed"])


# ============================================================================
# Single Watcher Instance
# ============================================================================

class FolderWatcher:
    """
    One independent watcher instance.

    Each instance has its own:
    - watch folder + output folder
    - GPU device assignment
    - tissue type for epithelial reclassification
    - detection service (model loaded on assigned GPU)
    - scan loop thread
    """

    def __init__(
        self,
        instance_id: str,
        watch_folder: str,
        output_folder: Optional[str] = None,
        device: str = "cuda:0",
        tissue_type: str = "Other",
        auto_epithelial_classify: bool = False,
        scan_interval: int = 10,
    ):
        self.instance_id = instance_id
        self.watch_folder = Path(watch_folder)
        self.device = device
        self.tissue_type = tissue_type
        self.auto_epithelial_classify = auto_epithelial_classify
        self.scan_interval = max(5, scan_interval)

        if not self.watch_folder.exists():
            raise FileNotFoundError(f"Watch folder not found: {watch_folder}")

        if output_folder:
            self.output_folder = Path(output_folder)
        else:
            self.output_folder = self.watch_folder / "ai_results"
        self.output_folder.mkdir(parents=True, exist_ok=True)

        # Registry
        self._registry = SlideRegistry(self.watch_folder / REGISTRY_FILENAME)

        # Watcher state
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Detection state
        self._detecting = False
        self._detection_lock = threading.Lock()
        self._current_detection: Optional[Dict[str, Any]] = None
        self._detection_history: List[Dict[str, Any]] = []

        # Detection service (lazy, per-instance with assigned GPU)
        self._detection_service = None

    # ------------------------------------------------------------------
    # Detection Service (lazy init with specific GPU)
    # ------------------------------------------------------------------

    def _get_detection_service(self):
        if self._detection_service is None:
            from api.services.detection_api_service import DetectionAPIService
            self._detection_service = DetectionAPIService(device=self.device)
        return self._detection_service

    def _ensure_model_loaded(self):
        """Ensure detection model is loaded on this instance's GPU."""
        service = self._get_detection_service()
        if not service.is_detection_model_loaded:
            self._update_progress(0, "Loading detection model...")
            if not service.load_detection_model():
                raise RuntimeError(f"Failed to load detection model on {self.device}")

    # ------------------------------------------------------------------
    # Watcher Control
    # ------------------------------------------------------------------

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._watch_loop, daemon=True,
            name=f"watcher-{self.instance_id}",
        )
        self._thread.start()
        print(f"[{self.instance_id}] Watcher started: {self.watch_folder} (GPU: {self.device})")

    def stop(self):
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=15)
        print(f"[{self.instance_id}] Watcher stopped.")

    def destroy(self):
        """Stop watcher and unload model to free GPU memory."""
        self.stop()
        if self._detection_service is not None:
            self._detection_service.unload_detection_model()
            self._detection_service = None
        print(f"[{self.instance_id}] Instance destroyed, GPU memory released.")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_detecting(self) -> bool:
        return self._detecting

    # ------------------------------------------------------------------
    # Watch Loop
    # ------------------------------------------------------------------

    def _watch_loop(self):
        while self._running and not self._stop_event.is_set():
            try:
                if not self._detecting:
                    self._scan_and_process()
            except Exception as e:
                print(f"[{self.instance_id}] Watcher error: {e}\n{traceback.format_exc()}")

            for _ in range(self.scan_interval * 10):
                if self._stop_event.is_set():
                    return
                time.sleep(0.1)

    def _scan_and_process(self):
        """Scan for new files and process the first pending slide."""
        # 1. Register new files
        for file_path in self.watch_folder.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                if self._registry.register_slide(str(file_path)):
                    print(f"[{self.instance_id}] New slide: {file_path.name}")

        # 2. Process first pending
        pending = self._registry.get_pending_slides()
        if pending:
            self._run_detection(pending[0])

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def _run_detection(self, slide_entry: Dict[str, Any]):
        slide_path = slide_entry["slide_path"]
        file_name = slide_entry["file_name"]

        with self._detection_lock:
            self._detecting = True
            self._current_detection = {
                "slide_path": slide_path,
                "file_name": file_name,
                "started_at": datetime.now().isoformat(),
                "progress": 0,
                "message": "Starting detection...",
            }

        print(f"[{self.instance_id}] Detection start: {file_name} (GPU: {self.device})")
        start_time = time.time()

        try:
            self._ensure_model_loaded()
            service = self._get_detection_service()

            result = service.run_detection(
                slide_path=slide_path,
                tissue_type=self.tissue_type,
                confidence_threshold=0.01,
                iou_threshold=0.3,
                auto_epithelial_classify=self.auto_epithelial_classify,
                include_segmentation=False,
                progress_callback=self._update_progress,
            )

            # Save result
            output_path = self.output_folder / f"{Path(file_name).stem}_result.json"
            self._save_result_json(result, output_path, file_name)
            self._registry.mark_completed(slide_path, str(output_path))

            elapsed = time.time() - start_time
            self._detection_history.append({
                "file_name": file_name,
                "slide_path": slide_path,
                "status": "success",
                "total_cells": result["summary"]["total_cells"],
                "processing_time_sec": round(elapsed, 2),
                "result_path": str(output_path),
                "completed_at": datetime.now().isoformat(),
            })
            print(f"[{self.instance_id}] Detection done: {file_name} "
                  f"({result['summary']['total_cells']} cells, {elapsed:.1f}s)")

        except Exception as e:
            elapsed = time.time() - start_time
            self._registry.mark_failed(slide_path, str(e))
            self._detection_history.append({
                "file_name": file_name,
                "slide_path": slide_path,
                "status": "failed",
                "error": str(e),
                "processing_time_sec": round(elapsed, 2),
                "completed_at": datetime.now().isoformat(),
            })
            print(f"[{self.instance_id}] Detection failed: {file_name} - {e}")

        finally:
            with self._detection_lock:
                self._detecting = False
                self._current_detection = None

    def _update_progress(self, pct: int, msg: str):
        with self._detection_lock:
            if self._current_detection:
                if pct >= 0:
                    self._current_detection["progress"] = pct
                self._current_detection["message"] = msg

    @staticmethod
    def _save_result_json(result: Dict[str, Any], output_path: Path, file_name: str):
        cells = [
            {"x": c["x"], "y": c["y"], "cls_id": c["cls_id"], "confidence": c["confidence"]}
            for c in result.get("cells", [])
        ]
        data = {
            "metadata": {
                "model_type": "detection",
                "model_name": "HnE Cell Detection",
                "version": "1.0",
                "timestamp": datetime.now().isoformat(),
                "image_name": file_name,
            },
            "result": {
                "status": "success",
                "num_cells": result["summary"]["total_cells"],
                "class_counts": result["summary"]["class_counts"],
                "cells": cells,
                "message": f"Detection complete: {result['summary']['total_cells']} cells detected",
            },
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        status = {
            "instance_id": self.instance_id,
            "config": {
                "watch_folder": str(self.watch_folder),
                "output_folder": str(self.output_folder),
                "device": self.device,
                "tissue_type": self.tissue_type,
                "auto_epithelial_classify": self.auto_epithelial_classify,
                "scan_interval_sec": self.scan_interval,
            },
            "watcher_running": self._running,
            "detection": {
                "is_running": self._detecting,
                "current": None,
            },
            "summary": {
                "total_slides": self._registry.total_count,
                "completed": self._registry.completed_count,
                "pending": self._registry.pending_count,
            },
        }

        with self._detection_lock:
            if self._current_detection:
                current = dict(self._current_detection)
                started = datetime.fromisoformat(current["started_at"])
                current["elapsed_sec"] = round(
                    (datetime.now() - started).total_seconds(), 1
                )
                status["detection"]["current"] = current

        status["detection"]["recent_history"] = list(
            reversed(self._detection_history[-10:])
        )
        return status

    def get_slides(self) -> List[Dict[str, Any]]:
        return self._registry.get_all_slides()


# ============================================================================
# Watcher Manager (manages multiple instances)
# ============================================================================

class WatcherManager:
    """
    Manages multiple FolderWatcher instances.

    Each instance is identified by a unique instance_id and runs independently
    with its own folder, GPU device, and tissue type configuration.
    """

    def __init__(self):
        self._instances: Dict[str, FolderWatcher] = {}
        self._lock = threading.Lock()

    def create_instance(
        self,
        instance_id: str,
        watch_folder: str,
        output_folder: Optional[str] = None,
        device: str = "cuda:0",
        tissue_type: str = "Other",
        auto_epithelial_classify: bool = False,
        scan_interval: int = 10,
        auto_start: bool = True,
    ) -> FolderWatcher:
        """Create and register a new watcher instance."""
        with self._lock:
            if instance_id in self._instances:
                raise ValueError(f"Instance '{instance_id}' already exists. Delete it first.")

            watcher = FolderWatcher(
                instance_id=instance_id,
                watch_folder=watch_folder,
                output_folder=output_folder,
                device=device,
                tissue_type=tissue_type,
                auto_epithelial_classify=auto_epithelial_classify,
                scan_interval=scan_interval,
            )
            self._instances[instance_id] = watcher

        if auto_start:
            watcher.start()

        return watcher

    def get_instance(self, instance_id: str) -> Optional[FolderWatcher]:
        with self._lock:
            return self._instances.get(instance_id)

    def delete_instance(self, instance_id: str) -> bool:
        """Stop and remove an instance, freeing GPU memory."""
        with self._lock:
            watcher = self._instances.pop(instance_id, None)
        if watcher is None:
            return False
        watcher.destroy()
        return True

    def list_instances(self) -> List[Dict[str, Any]]:
        """Return summary of all instances."""
        with self._lock:
            instances = list(self._instances.values())
        return [w.get_status() for w in instances]

    def stop_all(self):
        """Stop all instances (for shutdown)."""
        with self._lock:
            instances = list(self._instances.values())
        for w in instances:
            w.destroy()
        with self._lock:
            self._instances.clear()
        print("All watcher instances stopped.")

    @property
    def instance_count(self) -> int:
        with self._lock:
            return len(self._instances)


# ============================================================================
# Singleton Manager
# ============================================================================

_manager_instance: Optional[WatcherManager] = None
_manager_lock = threading.Lock()


def get_watcher_manager() -> WatcherManager:
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = WatcherManager()
    return _manager_instance
