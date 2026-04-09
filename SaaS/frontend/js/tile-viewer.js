/**
 * WSI Tile Viewer — Canvas 기반 타일 렌더링 엔진
 * PyQt5 wsi_view_widget.py + wsi_tile_manager.py 로직을 JS로 포팅
 *
 * 좌표계: WSI level-0 픽셀 좌표 (scene 좌표)
 * 렌더링: 현재 zoom에 맞는 OpenSlide level의 타일을 서버에서 로드하여 canvas에 그림
 */

import { api } from './api.js';

const TILE_SIZE = 512;

export class TileViewer {
    constructor(canvas, overlayCanvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.overlayCanvas = overlayCanvas;
        this.overlayCtx = overlayCanvas.getContext('2d');

        // 슬라이드 상태
        this.slideId = null;
        this.slideInfo = null;  // {dimensions, level_count, level_dimensions, level_downsamples, mpp}

        // 뷰 상태 (scene 좌표계)
        this.viewCenterX = 0;  // level-0 px
        this.viewCenterY = 0;
        this.zoom = 1.0;       // canvas px / scene px
        this.minZoom = 0.001;
        this.maxZoom = 40.0;

        // 타일 캐시 (LRU)
        this._tileCache = new Map();  // "level/tx/ty" -> Image
        this._tileLoading = new Set();
        this._maxCacheTiles = 2000;

        // 패닝 상태
        this._isPanning = false;
        this._lastPanX = 0;
        this._lastPanY = 0;

        // 검출 결과
        this.detectionCells = [];
        this.classVisibility = {};
        this.confidenceThreshold = 0.30;

        // 콜백
        this.onZoomChange = null;
        this.onViewChange = null;

        // 렌더 루프 제어
        this._renderPending = false;

        this._setupEvents();
        this._resizeCanvas();
        window.addEventListener('resize', () => this._resizeCanvas());
    }

    // ── 슬라이드 로드 ──

    loadSlide(slideId, slideInfo) {
        this.slideId = slideId;
        this.slideInfo = slideInfo;

        // 캐시 초기화
        this._tileCache.clear();
        this._tileLoading.clear();
        this.detectionCells = [];

        // 초기 뷰: 전체 보기
        this.fitToWindow();
    }

    fitToWindow() {
        if (!this.slideInfo) return;
        const [imgW, imgH] = this.slideInfo.dimensions;
        const vw = this.canvas.width;
        const vh = this.canvas.height;
        this.zoom = Math.min(vw / imgW, vh / imgH);
        this.minZoom = this.zoom;
        this.viewCenterX = imgW / 2;
        this.viewCenterY = imgH / 2;

        // max zoom: 80x 배율 제한
        const baseMag = (0.25 / this.slideInfo.mpp) * 40.0;
        this.maxZoom = 80.0 / baseMag;

        this._emitZoomChange();
        this.requestRender();
    }

    // ── 좌표 변환 ──

    /** scene(level-0) → canvas 좌표 */
    sceneToCanvas(sx, sy) {
        const cx = (sx - this.viewCenterX) * this.zoom + this.canvas.width / 2;
        const cy = (sy - this.viewCenterY) * this.zoom + this.canvas.height / 2;
        return [cx, cy];
    }

    /** canvas → scene(level-0) 좌표 */
    canvasToScene(cx, cy) {
        const sx = (cx - this.canvas.width / 2) / this.zoom + this.viewCenterX;
        const sy = (cy - this.canvas.height / 2) / this.zoom + this.viewCenterY;
        return [sx, sy];
    }

    /** 현재 화면의 effective MPP */
    getEffectiveMpp() {
        if (!this.slideInfo || this.zoom <= 0) return Infinity;
        return this.slideInfo.mpp / this.zoom;
    }

    /** 현재 배율 (40x 기준) */
    getMagnification() {
        if (!this.slideInfo || this.zoom <= 0) return 0;
        const baseMag = (0.25 / this.slideInfo.mpp) * 40.0;
        return baseMag * this.zoom;
    }

    /** effective MPP → 4단계 레벨 선택 (기존 get_stage_level 로직) */
    _getStageLevel(effectiveMpp) {
        if (!this.slideInfo) return 0;
        const stages = this._getLevelStages();
        if (effectiveMpp < 2.0) return stages[0];
        if (effectiveMpp < 15.0) return stages[1];
        if (effectiveMpp < 100.0) return stages[2];
        return stages[3];
    }

    _getLevelStages() {
        const total = this.slideInfo.level_count;
        if (total === 1) return [0, 0, 0, 0];
        if (total === 2) return [0, 0, 1, 1];
        if (total === 3) return [0, 1, 2, 2];
        const step = (total - 1) / 3.0;
        return [
            0,
            Math.round(step),
            Math.round(step * 2),
            Math.min(total - 1, Math.round(step * 3)),
        ];
    }

    // ── 줌 ──

    setZoom(newZoom, anchorCanvasX = null, anchorCanvasY = null) {
        newZoom = Math.max(this.minZoom, Math.min(this.maxZoom, newZoom));
        if (newZoom === this.zoom) return;

        if (anchorCanvasX !== null && anchorCanvasY !== null) {
            // 마우스 위치 기준 줌 (기존 set_zoom의 anchor 로직)
            const [sceneX, sceneY] = this.canvasToScene(anchorCanvasX, anchorCanvasY);
            const strength = 0.3;
            this.viewCenterX += (sceneX - this.viewCenterX) * strength;
            this.viewCenterY += (sceneY - this.viewCenterY) * strength;
        }

        this.zoom = newZoom;
        this._clampView();
        this._emitZoomChange();
        this.requestRender();
    }

    zoomIn(anchorX = null, anchorY = null) {
        this.setZoom(this.zoom * 1.1, anchorX, anchorY);
    }

    zoomOut(anchorX = null, anchorY = null) {
        this.setZoom(this.zoom / 1.1, anchorX, anchorY);
    }

    _clampView() {
        if (!this.slideInfo) return;
        const [imgW, imgH] = this.slideInfo.dimensions;
        const halfVW = (this.canvas.width / this.zoom) / 2;
        const halfVH = (this.canvas.height / this.zoom) / 2;

        if (imgW > halfVW * 2) {
            this.viewCenterX = Math.max(halfVW, Math.min(this.viewCenterX, imgW - halfVW));
        } else {
            this.viewCenterX = imgW / 2;
        }
        if (imgH > halfVH * 2) {
            this.viewCenterY = Math.max(halfVH, Math.min(this.viewCenterY, imgH - halfVH));
        } else {
            this.viewCenterY = imgH / 2;
        }
    }

    _emitZoomChange() {
        if (this.onZoomChange) {
            this.onZoomChange(this.zoom, this.getMagnification(), this.getEffectiveMpp());
        }
        if (this.onViewChange) {
            this.onViewChange();
        }
    }

    // ── 이벤트 ──

    _setupEvents() {
        // 마우스 휠 → 줌
        this.canvas.addEventListener('wheel', (e) => {
            e.preventDefault();
            if (!this.slideInfo) return;
            const rect = this.canvas.getBoundingClientRect();
            const cx = e.clientX - rect.left;
            const cy = e.clientY - rect.top;
            if (e.deltaY < 0) this.zoomIn(cx, cy);
            else this.zoomOut(cx, cy);
        }, { passive: false });

        // 마우스 드래그 → 패닝
        this.canvas.addEventListener('mousedown', (e) => {
            if (e.button === 0 || e.button === 1) {
                this._isPanning = true;
                this._lastPanX = e.clientX;
                this._lastPanY = e.clientY;
                this.canvas.style.cursor = 'grabbing';
            }
        });
        window.addEventListener('mousemove', (e) => {
            if (!this._isPanning) return;
            const dx = e.clientX - this._lastPanX;
            const dy = e.clientY - this._lastPanY;
            this._lastPanX = e.clientX;
            this._lastPanY = e.clientY;

            this.viewCenterX -= dx / this.zoom;
            this.viewCenterY -= dy / this.zoom;
            this._clampView();
            this.requestRender();
            if (this.onViewChange) this.onViewChange();
        });
        window.addEventListener('mouseup', () => {
            if (this._isPanning) {
                this._isPanning = false;
                this.canvas.style.cursor = 'grab';
            }
        });

        // 터치 지원 (pinch zoom + pan)
        let lastTouchDist = 0;
        let lastTouchCenter = null;
        this.canvas.addEventListener('touchstart', (e) => {
            if (e.touches.length === 1) {
                this._isPanning = true;
                this._lastPanX = e.touches[0].clientX;
                this._lastPanY = e.touches[0].clientY;
            } else if (e.touches.length === 2) {
                const dx = e.touches[1].clientX - e.touches[0].clientX;
                const dy = e.touches[1].clientY - e.touches[0].clientY;
                lastTouchDist = Math.sqrt(dx * dx + dy * dy);
                lastTouchCenter = {
                    x: (e.touches[0].clientX + e.touches[1].clientX) / 2,
                    y: (e.touches[0].clientY + e.touches[1].clientY) / 2,
                };
            }
            e.preventDefault();
        }, { passive: false });
        this.canvas.addEventListener('touchmove', (e) => {
            if (e.touches.length === 1 && this._isPanning) {
                const dx = e.touches[0].clientX - this._lastPanX;
                const dy = e.touches[0].clientY - this._lastPanY;
                this._lastPanX = e.touches[0].clientX;
                this._lastPanY = e.touches[0].clientY;
                this.viewCenterX -= dx / this.zoom;
                this.viewCenterY -= dy / this.zoom;
                this._clampView();
                this.requestRender();
            } else if (e.touches.length === 2 && lastTouchDist > 0) {
                const dx = e.touches[1].clientX - e.touches[0].clientX;
                const dy = e.touches[1].clientY - e.touches[0].clientY;
                const dist = Math.sqrt(dx * dx + dy * dy);
                const scale = dist / lastTouchDist;
                const rect = this.canvas.getBoundingClientRect();
                this.setZoom(
                    this.zoom * scale,
                    lastTouchCenter.x - rect.left,
                    lastTouchCenter.y - rect.top
                );
                lastTouchDist = dist;
            }
            e.preventDefault();
        }, { passive: false });
        this.canvas.addEventListener('touchend', () => {
            this._isPanning = false;
            lastTouchDist = 0;
        });

        this.canvas.style.cursor = 'grab';
    }

    _resizeCanvas() {
        const container = this.canvas.parentElement;
        const w = container.clientWidth;
        const h = container.clientHeight;
        this.canvas.width = w;
        this.canvas.height = h;
        this.overlayCanvas.width = w;
        this.overlayCanvas.height = h;
        if (this.slideInfo) {
            this._clampView();
            this.requestRender();
        }
    }

    // ── 렌더링 ──

    requestRender() {
        if (this._renderPending) return;
        this._renderPending = true;
        requestAnimationFrame(() => {
            this._renderPending = false;
            this._render();
        });
    }

    _render() {
        if (!this.slideInfo) {
            this.ctx.fillStyle = '#000';
            this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
            return;
        }

        const ctx = this.ctx;
        ctx.fillStyle = '#000';
        ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

        // 현재 뷰에 맞는 레벨과 타일 계산
        const effectiveMpp = this.getEffectiveMpp();
        const level = this._getStageLevel(effectiveMpp);
        const downsample = this.slideInfo.level_downsamples[level];
        const [levelW, levelH] = this.slideInfo.level_dimensions[level];

        // 뷰 영역 (scene 좌표)
        const halfVW = this.canvas.width / this.zoom / 2;
        const halfVH = this.canvas.height / this.zoom / 2;
        const viewLeft = this.viewCenterX - halfVW;
        const viewTop = this.viewCenterY - halfVH;
        const viewRight = this.viewCenterX + halfVW;
        const viewBottom = this.viewCenterY + halfVH;

        // 필요한 타일 범위 (해당 레벨의 타일 좌표)
        const tileSceneSize = TILE_SIZE * downsample; // 타일 1장이 커버하는 scene 크기
        const txMin = Math.max(0, Math.floor(viewLeft / tileSceneSize));
        const tyMin = Math.max(0, Math.floor(viewTop / tileSceneSize));
        const txMax = Math.min(Math.ceil(levelW / TILE_SIZE) - 1, Math.ceil(viewRight / tileSceneSize));
        const tyMax = Math.min(Math.ceil(levelH / TILE_SIZE) - 1, Math.ceil(viewBottom / tileSceneSize));

        // 타일 렌더링
        for (let ty = tyMin; ty <= tyMax; ty++) {
            for (let tx = txMin; tx <= txMax; tx++) {
                const key = `${level}/${tx}/${ty}`;
                const img = this._tileCache.get(key);

                // 타일의 scene 좌표
                const sceneX = tx * tileSceneSize;
                const sceneY = ty * tileSceneSize;
                const [canvasX, canvasY] = this.sceneToCanvas(sceneX, sceneY);
                const canvasSize = tileSceneSize * this.zoom;

                if (img && img.complete && img.naturalWidth > 0) {
                    ctx.drawImage(img, canvasX, canvasY, canvasSize, canvasSize);
                } else if (!this._tileLoading.has(key)) {
                    this._loadTile(level, tx, ty);
                }
            }
        }

        // 검출 오버레이 렌더링
        this._renderDetectionOverlay();
    }

    _loadTile(level, tx, ty) {
        const key = `${level}/${tx}/${ty}`;
        if (this._tileLoading.has(key) || this._tileCache.has(key)) return;

        this._tileLoading.add(key);

        const img = new Image();
        img.onload = () => {
            this._tileLoading.delete(key);
            this._putCache(key, img);
            this.requestRender();
        };
        img.onerror = () => {
            this._tileLoading.delete(key);
        };
        img.src = api.tileUrl(this.slideId, level, tx, ty);
    }

    _putCache(key, img) {
        // LRU: 오래된 항목 제거
        if (this._tileCache.size >= this._maxCacheTiles) {
            const oldest = this._tileCache.keys().next().value;
            this._tileCache.delete(oldest);
        }
        this._tileCache.set(key, img);
    }

    // ── 검출 오버레이 ──

    setDetectionResults(cells) {
        this.detectionCells = cells || [];
        // 클래스별 가시성 초기화
        this.classVisibility = {};
        const classIds = new Set(cells.map(c => c.class_id));
        classIds.forEach(id => { this.classVisibility[id] = true; });
        this.requestRender();
    }

    _renderDetectionOverlay() {
        const octx = this.overlayCtx;
        octx.clearRect(0, 0, this.overlayCanvas.width, this.overlayCanvas.height);

        if (!this.detectionCells.length) return;

        const mag = this.getMagnification();
        // 배율이 낮으면 셀 표시 안 함 (성능)
        if (mag < 5) return;

        // 뷰 범위 계산
        const halfVW = this.canvas.width / this.zoom / 2;
        const halfVH = this.canvas.height / this.zoom / 2;
        const viewLeft = this.viewCenterX - halfVW;
        const viewTop = this.viewCenterY - halfVH;
        const viewRight = this.viewCenterX + halfVW;
        const viewBottom = this.viewCenterY + halfVH;

        // 셀 크기 (화면 픽셀 기준)
        const cellRadius = Math.max(3, 8 * this.zoom);

        const CLASS_COLORS = {
            0: '#FF4500', 1: '#00FF00', 2: '#0000FF', 3: '#FFFF00',
            4: '#8A2BE2', 5: '#808080', 6: '#FF0000', 7: '#00FF00',
        };

        for (const cell of this.detectionCells) {
            // 필터링
            if (cell.confidence < this.confidenceThreshold) continue;
            if (this.classVisibility[cell.class_id] === false) continue;

            // 뷰 범위 체크
            if (cell.x < viewLeft || cell.x > viewRight || cell.y < viewTop || cell.y > viewBottom) continue;

            const [cx, cy] = this.sceneToCanvas(cell.x, cell.y);
            const color = CLASS_COLORS[cell.class_id] || '#FFFFFF';

            octx.beginPath();
            octx.arc(cx, cy, cellRadius, 0, Math.PI * 2);
            octx.strokeStyle = color;
            octx.lineWidth = 2;
            octx.stroke();
        }
    }

    // ── 미니맵 ──

    getViewRect() {
        if (!this.slideInfo) return null;
        const halfVW = this.canvas.width / this.zoom / 2;
        const halfVH = this.canvas.height / this.zoom / 2;
        return {
            x: this.viewCenterX - halfVW,
            y: this.viewCenterY - halfVH,
            width: halfVW * 2,
            height: halfVH * 2,
        };
    }

    navigateTo(sceneX, sceneY) {
        this.viewCenterX = sceneX;
        this.viewCenterY = sceneY;
        this._clampView();
        this.requestRender();
        if (this.onViewChange) this.onViewChange();
    }
}
