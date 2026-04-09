/**
 * WSI Tile Viewer — Canvas 기반 타일 렌더링 엔진
 * PyQt5 wsi_view_widget.py + wsi_tile_manager.py 로직을 JS로 포팅
 *
 * 좌표계: WSI level-0 픽셀 좌표 (scene 좌표)
 * 렌더링: 현재 zoom에 맞는 OpenSlide level의 타일을 서버에서 로드하여 canvas에 그림
 *
 * 핵심 원리 (PyQt5 원본과 동일):
 *  - 레벨 변경 시 이전 레벨 타일을 스케일해서 먼저 보여줌 (fallback)
 *  - 새 레벨 타일이 로드되면 점차 교체 → 검은 화면 없음
 */

import { api } from './api.js';

const TILE_SIZE = 512;
const MAX_CONCURRENT_LOADS = 12;  // 동시 타일 로딩 수

export class TileViewer {
    constructor(canvas, overlayCanvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.overlayCanvas = overlayCanvas;
        this.overlayCtx = overlayCanvas.getContext('2d');

        // 슬라이드 상태
        this.slideId = null;
        this.slideInfo = null;

        // 뷰 상태 (scene 좌표계 = level-0 px)
        this.viewCenterX = 0;
        this.viewCenterY = 0;
        this.zoom = 1.0;
        this.minZoom = 0.001;
        this.maxZoom = 40.0;

        // 타일 캐시 — 모든 레벨의 타일을 보관 (fallback용)
        this._tileCache = new Map();  // "level/tx/ty" -> Image
        this._tileLoading = new Set();
        this._maxCacheTiles = 3000;
        this._loadQueue = [];         // 우선순위 로드 큐
        this._activeLoads = 0;

        // 패닝 상태
        this._isPanning = false;
        this._lastPanX = 0;
        this._lastPanY = 0;

        // 검출 결과
        this.detectionCells = [];
        this.classVisibility = {};   // {class_id: bool}
        this.classConfidence = {};   // {class_id: float} 클래스별 threshold (기본 0.01)

        // ── Annotation ──
        this.annotations = [];        // [{id, name, type, coordinates, color, visible, selected, group}]
        this.drawMode = null;         // 'polygon' | 'rectangle' | 'point' | null
        this._drawingPoints = [];     // 진행 중인 폴리곤 좌표 (scene)
        this._drawingStart = null;    // 사각형 시작점 (scene)
        this._drawingCurrent = null;  // 사각형/폴리곤 현재 마우스 (scene)
        this._isDrawing = false;
        this._annotationCounter = 0;
        this.selectedAnnotationId = null;
        this._dragControlPoint = null;  // {annId, pointIndex} 드래그 중인 컨트롤포인트
        this._dragAnnotation = null;    // {annId, startScene} 어노테이션 전체 이동
        this._lastDrawDragScene = null; // 폴리곤 드래그 점 추가용

        // 콜백
        this.onZoomChange = null;
        this.onViewChange = null;
        this.onAnnotationCreated = null;   // (annotation) => {}
        this.onAnnotationSelected = null;  // (annotation|null) => {}
        this.onAnnotationDeleted = null;   // (annotation) => {}
        this.onAnnotationChanged = null;   // (annotation) => {}
        this.onDrawModeChange = null;      // (mode) => {}

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

        this._tileCache.clear();
        this._tileLoading.clear();
        this._loadQueue = [];
        this._activeLoads = 0;
        this.detectionCells = [];

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

        const baseMag = (0.25 / this.slideInfo.mpp) * 40.0;
        this.maxZoom = 80.0 / baseMag;

        this._emitZoomChange();
        this.requestRender();
    }

    // ── 좌표 변환 ──

    sceneToCanvas(sx, sy) {
        const cx = (sx - this.viewCenterX) * this.zoom + this.canvas.width / 2;
        const cy = (sy - this.viewCenterY) * this.zoom + this.canvas.height / 2;
        return [cx, cy];
    }

    canvasToScene(cx, cy) {
        const sx = (cx - this.canvas.width / 2) / this.zoom + this.viewCenterX;
        const sy = (cy - this.canvas.height / 2) / this.zoom + this.viewCenterY;
        return [sx, sy];
    }

    getEffectiveMpp() {
        if (!this.slideInfo || this.zoom <= 0) return Infinity;
        return this.slideInfo.mpp / this.zoom;
    }

    getMagnification() {
        if (!this.slideInfo || this.zoom <= 0) return 0;
        const baseMag = (0.25 / this.slideInfo.mpp) * 40.0;
        return baseMag * this.zoom;
    }

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
        // ── 줌 ──
        this.canvas.addEventListener('wheel', (e) => {
            e.preventDefault();
            if (!this.slideInfo) return;
            const rect = this.canvas.getBoundingClientRect();
            const cx = e.clientX - rect.left;
            const cy = e.clientY - rect.top;
            if (e.deltaY < 0) this.zoomIn(cx, cy);
            else this.zoomOut(cx, cy);
        }, { passive: false });

        // ── 마우스 ──
        this.canvas.addEventListener('mousedown', (e) => {
            const rect = this.canvas.getBoundingClientRect();
            const cx = e.clientX - rect.left;
            const cy = e.clientY - rect.top;
            const [sx, sy] = this.canvasToScene(cx, cy);

            // 그리기 모드
            if (this.drawMode && e.button === 0 && !e.ctrlKey) {
                this._onDrawMouseDown(sx, sy, cx, cy, e);
                return;
            }

            // 컨트롤포인트 드래그 감지 (선택된 annotation의 꼭짓점)
            if (e.button === 0 && !this.drawMode) {
                const cp = this._hitControlPoint(cx, cy);
                if (cp) {
                    this._dragControlPoint = cp;
                    this.canvas.style.cursor = 'move';
                    return;
                }

                // annotation 클릭 선택 / 이동
                const hitAnn = this._hitAnnotation(sx, sy);
                if (hitAnn) {
                    this.selectAnnotation(hitAnn.id);
                    this._dragAnnotation = { annId: hitAnn.id, startScene: [sx, sy], origCoords: hitAnn.coordinates.map(c => [...c]) };
                    this.canvas.style.cursor = 'move';
                    return;
                }

                // 빈 공간 클릭 → 선택 해제
                if (!e.ctrlKey && this.selectedAnnotationId) {
                    this.selectAnnotation(null);
                }
            }

            // Ctrl+좌클릭 또는 일반 패닝
            if (e.button === 0 || e.button === 1) {
                this._isPanning = true;
                this._lastPanX = e.clientX;
                this._lastPanY = e.clientY;
                this.canvas.style.cursor = 'grabbing';
            }
        });

        window.addEventListener('mousemove', (e) => {
            const rect = this.canvas.getBoundingClientRect();
            const cx = e.clientX - rect.left;
            const cy = e.clientY - rect.top;
            const [sx, sy] = this.canvasToScene(cx, cy);

            // 컨트롤포인트 드래그
            if (this._dragControlPoint) {
                const ann = this.annotations.find(a => a.id === this._dragControlPoint.annId);
                if (ann) {
                    ann.coordinates[this._dragControlPoint.pointIndex] = [sx, sy];
                    if (this.onAnnotationChanged) this.onAnnotationChanged(ann);
                    this.requestRender();
                }
                return;
            }

            // annotation 전체 이동
            if (this._dragAnnotation) {
                const ann = this.annotations.find(a => a.id === this._dragAnnotation.annId);
                if (ann) {
                    const dx = sx - this._dragAnnotation.startScene[0];
                    const dy = sy - this._dragAnnotation.startScene[1];
                    ann.coordinates = this._dragAnnotation.origCoords.map(([ox, oy]) => [ox + dx, oy + dy]);
                    if (this.onAnnotationChanged) this.onAnnotationChanged(ann);
                    this.requestRender();
                }
                return;
            }

            // 그리기 모드
            if (this.drawMode && this._isDrawing) {
                this._onDrawMouseMove(sx, sy, cx, cy);
                return;
            }

            // 패닝
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

        window.addEventListener('mouseup', (e) => {
            if (this._dragControlPoint) {
                this._dragControlPoint = null;
                this.canvas.style.cursor = this.drawMode ? 'crosshair' : 'grab';
                return;
            }
            if (this._dragAnnotation) {
                this._dragAnnotation = null;
                this.canvas.style.cursor = this.drawMode ? 'crosshair' : 'grab';
                return;
            }
            if (this.drawMode && this._isDrawing) {
                const rect = this.canvas.getBoundingClientRect();
                const cx = e.clientX - rect.left;
                const cy = e.clientY - rect.top;
                const [sx, sy] = this.canvasToScene(cx, cy);
                this._onDrawMouseUp(sx, sy);
                return;
            }
            if (this._isPanning) {
                this._isPanning = false;
                this.canvas.style.cursor = this.drawMode ? 'crosshair' : 'grab';
            }
        });

        // ── 우클릭: 컨텍스트 메뉴 방지 ──
        this.canvas.addEventListener('contextmenu', (e) => {
            e.preventDefault();
        });

        // ── 더블클릭: annotation 센터링 ──
        this.canvas.addEventListener('dblclick', (e) => {
            if (!this.drawMode) {
                const rect = this.canvas.getBoundingClientRect();
                const [sx, sy] = this.canvasToScene(e.clientX - rect.left, e.clientY - rect.top);
                const hitAnn = this._hitAnnotation(sx, sy);
                if (hitAnn) this.centerOnAnnotation(hitAnn);
            }
        });

        // ── 키보드 ──
        window.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                if (this.drawMode) {
                    this.setDrawMode(null); // 모드 해제
                }
            }
            if (e.key === 'Delete' && this.selectedAnnotationId) {
                this.deleteAnnotation(this.selectedAnnotationId);
            }
        });

        // ── 터치 ──
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

    /**
     * 특정 scene 영역을 커버하는 fallback 타일을 캐시에서 찾는다.
     * 다른 레벨의 타일 중 해당 scene 영역과 겹치는 것을 반환.
     * 낮은 해상도(높은 레벨) → 높은 해상도(낮은 레벨) 순으로 탐색.
     */
    _findFallbackTile(sceneX, sceneY, sceneSize, currentLevel) {
        // 낮은 해상도 레벨부터 (빠르게 찾을 확률 높음)
        const levels = [];
        for (let l = this.slideInfo.level_count - 1; l >= 0; l--) {
            if (l !== currentLevel) levels.push(l);
        }

        for (const l of levels) {
            const ds = this.slideInfo.level_downsamples[l];
            const tileScene = TILE_SIZE * ds;
            // 이 scene 영역의 중심이 속하는 타일
            const centerX = sceneX + sceneSize / 2;
            const centerY = sceneY + sceneSize / 2;
            const ftx = Math.floor(centerX / tileScene);
            const fty = Math.floor(centerY / tileScene);
            const key = `${l}/${ftx}/${fty}`;
            const img = this._tileCache.get(key);
            if (img && img.complete && img.naturalWidth > 0) {
                // 이 fallback 타일의 scene 좌표와 크기
                return {
                    img,
                    srcSceneX: ftx * tileScene,
                    srcSceneY: fty * tileScene,
                    srcSceneSize: tileScene,
                    srcPixelSize: TILE_SIZE,
                };
            }
        }
        return null;
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

        // 타일 범위
        const tileSceneSize = TILE_SIZE * downsample;
        const txMin = Math.max(0, Math.floor(viewLeft / tileSceneSize));
        const tyMin = Math.max(0, Math.floor(viewTop / tileSceneSize));
        const txMax = Math.min(Math.ceil(levelW / TILE_SIZE) - 1, Math.ceil(viewRight / tileSceneSize));
        const tyMax = Math.min(Math.ceil(levelH / TILE_SIZE) - 1, Math.ceil(viewBottom / tileSceneSize));

        // 로드 큐 초기화 (새 프레임마다 현재 뷰 기준으로 재구성)
        this._loadQueue = [];

        // ── Pass 1: fallback 먼저 그리기 (낮은 해상도 타일 스케일) ──
        // ── Pass 2: 현재 레벨 타일 그리기 (있으면 덮어씀) ──
        for (let ty = tyMin; ty <= tyMax; ty++) {
            for (let tx = txMin; tx <= txMax; tx++) {
                const key = `${level}/${tx}/${ty}`;
                const img = this._tileCache.get(key);

                const sceneX = tx * tileSceneSize;
                const sceneY = ty * tileSceneSize;
                const [canvasX, canvasY] = this.sceneToCanvas(sceneX, sceneY);
                const canvasSize = tileSceneSize * this.zoom;

                if (img && img.complete && img.naturalWidth > 0) {
                    // LRU touch: 삭제 후 재삽입으로 순서 갱신
                    this._tileCache.delete(key);
                    this._tileCache.set(key, img);
                    ctx.drawImage(img, canvasX, canvasY, canvasSize, canvasSize);
                } else {
                    // ── Fallback: 다른 레벨 캐시 타일을 스케일해서 그리기 ──
                    const fb = this._findFallbackTile(sceneX, sceneY, tileSceneSize, level);
                    if (fb) {
                        // fallback 타일 내에서 현재 타일 영역에 해당하는 소스 영역 계산
                        const srcScale = fb.srcPixelSize / fb.srcSceneSize;
                        const srcX = (sceneX - fb.srcSceneX) * srcScale;
                        const srcY = (sceneY - fb.srcSceneY) * srcScale;
                        const srcW = tileSceneSize * srcScale;
                        const srcH = tileSceneSize * srcScale;

                        // 소스 영역이 유효한 범위 내인지 확인
                        if (srcX >= 0 && srcY >= 0 &&
                            srcX + srcW <= fb.srcPixelSize + 1 &&
                            srcY + srcH <= fb.srcPixelSize + 1) {
                            ctx.drawImage(
                                fb.img,
                                srcX, srcY, srcW, srcH,
                                canvasX, canvasY, canvasSize, canvasSize
                            );
                        }
                    }

                    // 현재 레벨 타일 로드 요청
                    if (!this._tileLoading.has(key)) {
                        this._loadQueue.push({ level, tx, ty, key });
                    }
                }
            }
        }

        // 큐에 있는 타일 로딩 시작
        this._processLoadQueue();

        // 오버레이 렌더링
        this._renderDetectionOverlay();
        this._renderAnnotations(this.overlayCtx);
    }

    // ── 타일 로딩 (병렬, 큐 기반) ──

    _processLoadQueue() {
        while (this._loadQueue.length > 0 && this._activeLoads < MAX_CONCURRENT_LOADS) {
            const task = this._loadQueue.shift();
            this._loadTile(task.level, task.tx, task.ty);
        }
    }

    _loadTile(level, tx, ty) {
        const key = `${level}/${tx}/${ty}`;
        if (this._tileLoading.has(key) || this._tileCache.has(key)) return;

        this._tileLoading.add(key);
        this._activeLoads++;

        const img = new Image();
        img.onload = () => {
            this._tileLoading.delete(key);
            this._activeLoads--;
            this._putCache(key, img);
            // 다음 큐 처리
            this._processLoadQueue();
            this.requestRender();
        };
        img.onerror = () => {
            this._tileLoading.delete(key);
            this._activeLoads--;
            // 타일이 아직 생성되지 않았을 수 있음 (404) — 나중에 재시도
            this._processLoadQueue();
        };
        img.src = api.tileUrl(this.slideId, level, tx, ty);
    }

    _putCache(key, img) {
        // LRU 제거
        if (this._tileCache.size >= this._maxCacheTiles) {
            // 가장 오래된 (Map 첫 번째) 항목 제거
            const oldest = this._tileCache.keys().next().value;
            this._tileCache.delete(oldest);
        }
        this._tileCache.set(key, img);
    }

    /** 타일 캐시 비우고 다시 렌더 (타일 생성 완료 후 호출) */
    clearCacheAndRender() {
        this._tileCache.clear();
        this._tileLoading.clear();
        this._loadQueue = [];
        this._activeLoads = 0;
        this.requestRender();
    }

    // ── 검출 오버레이 ──

    setDetectionResults(cells, roiPolygons = null) {
        let filtered = cells || [];

        // ROI 폴리곤이 있으면 폴리곤 내부 셀만 필터링
        if (roiPolygons && roiPolygons.length > 0) {
            filtered = filtered.filter(c =>
                roiPolygons.some(poly => this._pointInPolygon(c.x, c.y, poly))
            );
        }

        this.detectionCells = filtered;
        this.classVisibility = {};
        this.classConfidence = {};
        const classIds = new Set(filtered.map(c => c.class_id));
        classIds.forEach(id => {
            this.classVisibility[id] = true;
            this.classConfidence[id] = 0.01;
        });

        this._heatmapDirty = true;
        this._buildHeatmapCache();
        this.requestRender();
    }

    /**
     * 클래스별 density 그리드 사전 계산 (기존 TiledDetectionOverlay._build_heatmap_cache)
     * 종횡비 유지한 2048 해상도 그리드에 histogram2d
     * confidence 필터링은 클래스별로 적용
     */
    _buildHeatmapCache() {
        this._heatmapCache = null;
        if (!this.detectionCells.length || !this.slideInfo) return;

        // 셀 범위 계산
        let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
        for (const c of this.detectionCells) {
            if (c.x < xMin) xMin = c.x;
            if (c.x > xMax) xMax = c.x;
            if (c.y < yMin) yMin = c.y;
            if (c.y > yMax) yMax = c.y;
        }
        const spanW = Math.max(xMax - xMin, 1);
        const spanH = Math.max(yMax - yMin, 1);

        const GRID_SIZE = 2048;
        let gw, gh;
        if (spanW >= spanH) {
            gw = GRID_SIZE;
            gh = Math.max(1, Math.round(GRID_SIZE * spanH / spanW));
        } else {
            gh = GRID_SIZE;
            gw = Math.max(1, Math.round(GRID_SIZE * spanW / spanH));
        }

        const sx = gw / spanW;
        const sy = gh / spanH;

        // 클래스별 density 그리드
        const clsDensities = {};
        for (const cell of this.detectionCells) {
            const cls = cell.class_id;
            const threshold = this.classConfidence[cls] ?? 0.01;
            if (cell.confidence < threshold) continue;

            if (!clsDensities[cls]) {
                clsDensities[cls] = new Float32Array(gh * gw);
            }
            const col = Math.min(Math.floor((cell.x - xMin) * sx), gw - 1);
            const row = Math.min(Math.floor((cell.y - yMin) * sy), gh - 1);
            if (col >= 0 && row >= 0) {
                clsDensities[cls][row * gw + col]++;
            }
        }

        this._heatmapCache = { clsDensities, xMin, yMin, xMax, yMax, gw, gh, sx, sy };
        this._heatmapDirty = false;
    }

    /**
     * 가우시안 블러 (3x3 반복 적용으로 근사)
     * GPU 없이 빠르게 처리하기 위한 box blur 근사
     */
    _blurGrid(src, w, h, passes) {
        let a = new Float32Array(src);
        let b = new Float32Array(w * h);
        for (let p = 0; p < passes; p++) {
            // 수평 블러
            for (let y = 0; y < h; y++) {
                for (let x = 0; x < w; x++) {
                    const l = x > 0 ? a[y * w + x - 1] : a[y * w + x];
                    const c = a[y * w + x];
                    const r = x < w - 1 ? a[y * w + x + 1] : a[y * w + x];
                    b[y * w + x] = (l + c + r) / 3;
                }
            }
            // 수직 블러
            for (let y = 0; y < h; y++) {
                for (let x = 0; x < w; x++) {
                    const t = y > 0 ? b[(y - 1) * w + x] : b[y * w + x];
                    const c = b[y * w + x];
                    const bt = y < h - 1 ? b[(y + 1) * w + x] : b[y * w + x];
                    a[y * w + x] = (t + c + bt) / 3;
                }
            }
        }
        return a;
    }

    /** jet 컬러맵: 0~1 → [r, g, b] */
    _jetColor(t) {
        t = Math.max(0, Math.min(1, t));
        let r, g, b;
        if (t < 0.25) { r = 0; g = t * 4; b = 1; }
        else if (t < 0.5) { r = 0; g = 1; b = 1 - (t - 0.25) * 4; }
        else if (t < 0.75) { r = (t - 0.5) * 4; g = 1; b = 0; }
        else { r = 1; g = 1 - (t - 0.75) * 4; b = 0; }
        return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
    }

    _renderDetectionOverlay() {
        const octx = this.overlayCtx;
        octx.clearRect(0, 0, this.overlayCanvas.width, this.overlayCanvas.height);
        if (!this.detectionCells.length) return;

        if (this._heatmapDirty) this._buildHeatmapCache();

        const mag = this.getMagnification();
        if (mag < 5) {
            this._renderHeatmap(octx);
        } else {
            this._renderCells(octx);
        }
    }

    /**
     * 히트맵 렌더링 (기존 create_heatmap_mask와 동일 방식)
     * 1. 가시 클래스 density를 합산
     * 2. 현재 뷰 영역만 crop
     * 3. 가우시안 블러
     * 4. jet 컬러맵 + 알파를 ImageData로 그리기
     */
    _renderHeatmap(octx) {
        const cache = this._heatmapCache;
        if (!cache) return;

        const { clsDensities, xMin, yMin, gw, gh, sx, sy } = cache;

        // 뷰 영역
        const halfVW = this.canvas.width / this.zoom / 2;
        const halfVH = this.canvas.height / this.zoom / 2;
        const viewLeft = this.viewCenterX - halfVW;
        const viewTop = this.viewCenterY - halfVH;
        const viewRight = this.viewCenterX + halfVW;
        const viewBottom = this.viewCenterY + halfVH;

        // 그리드 인덱스로 변환 (crop 범위)
        const gx0 = Math.max(0, Math.floor((viewLeft - xMin) * sx));
        const gy0 = Math.max(0, Math.floor((viewTop - yMin) * sy));
        const gx1 = Math.min(gw, Math.ceil((viewRight - xMin) * sx) + 1);
        const gy1 = Math.min(gh, Math.ceil((viewBottom - yMin) * sy) + 1);

        const cropW = gx1 - gx0;
        const cropH = gy1 - gy0;
        if (cropW <= 0 || cropH <= 0) return;

        // 가시 클래스 합산 (crop 영역만)
        const combined = new Float32Array(cropH * cropW);
        let hasData = false;
        for (const [clsStr, density] of Object.entries(clsDensities)) {
            const cls = parseInt(clsStr);
            if (this.classVisibility[cls] === false) continue;
            for (let y = 0; y < cropH; y++) {
                for (let x = 0; x < cropW; x++) {
                    const val = density[(y + gy0) * gw + (x + gx0)];
                    if (val > 0) {
                        combined[y * cropW + x] += val;
                        hasData = true;
                    }
                }
            }
        }
        if (!hasData) return;

        // 출력 해상도 (캔버스에 맞게, 최대 512px)
        const maxDim = 512;
        let outW, outH;
        if (cropW >= cropH) {
            outW = Math.min(maxDim, cropW);
            outH = Math.max(1, Math.round(outW * cropH / cropW));
        } else {
            outH = Math.min(maxDim, cropH);
            outW = Math.max(1, Math.round(outH * cropW / cropH));
        }

        // 리사이즈 (nearest → bilinear 근사: 작은 크기라 nearest로 충분)
        const resized = new Float32Array(outH * outW);
        const rxScale = cropW / outW;
        const ryScale = cropH / outH;
        for (let y = 0; y < outH; y++) {
            for (let x = 0; x < outW; x++) {
                const srcX = Math.min(Math.floor(x * rxScale), cropW - 1);
                const srcY = Math.min(Math.floor(y * ryScale), cropH - 1);
                resized[y * outW + x] = combined[srcY * cropW + srcX];
            }
        }

        // 가우시안 블러 (box blur 8 passes ≈ gaussian sigma ~5)
        const blurred = this._blurGrid(resized, outW, outH, 8);

        // 최대값
        let maxVal = 0;
        for (let i = 0; i < blurred.length; i++) {
            if (blurred[i] > maxVal) maxVal = blurred[i];
        }
        if (maxVal === 0) return;

        // ImageData 생성 (jet 컬러맵 + 밀도 비례 알파)
        const imgData = octx.createImageData(outW, outH);
        const data = imgData.data;
        const ALPHA_MAX = 180;  // 기존 self.alpha = 180

        for (let i = 0; i < blurred.length; i++) {
            const norm = blurred[i] / maxVal;
            if (norm < 0.01) {
                data[i * 4 + 3] = 0;  // 투명
                continue;
            }
            const [r, g, b] = this._jetColor(norm);
            data[i * 4 + 0] = r;
            data[i * 4 + 1] = g;
            data[i * 4 + 2] = b;
            data[i * 4 + 3] = Math.round(norm * ALPHA_MAX);
        }

        // 오프스크린 캔버스에 ImageData → 메인 캔버스에 스케일해서 그리기
        const offscreen = new OffscreenCanvas(outW, outH);
        const offCtx = offscreen.getContext('2d');
        offCtx.putImageData(imgData, 0, 0);

        // crop 영역의 scene 좌표
        const sceneLeft = xMin + gx0 / sx;
        const sceneTop = yMin + gy0 / sy;
        const sceneW = cropW / sx;
        const sceneH = cropH / sy;

        const [canvasX, canvasY] = this.sceneToCanvas(sceneLeft, sceneTop);
        const canvasW = sceneW * this.zoom;
        const canvasH = sceneH * this.zoom;

        octx.imageSmoothingEnabled = true;
        octx.drawImage(offscreen, canvasX, canvasY, canvasW, canvasH);
    }

    _renderCells(octx) {
        const halfVW = this.canvas.width / this.zoom / 2;
        const halfVH = this.canvas.height / this.zoom / 2;
        const viewLeft = this.viewCenterX - halfVW;
        const viewTop = this.viewCenterY - halfVH;
        const viewRight = this.viewCenterX + halfVW;
        const viewBottom = this.viewCenterY + halfVH;

        const cellRadius = Math.max(3, 8 * this.zoom);

        const CLASS_COLORS = {
            0: '#FF4500', 1: '#00FF00', 2: '#0000FF', 3: '#FFFF00',
            4: '#8A2BE2', 5: '#808080', 6: '#FF0000', 7: '#00FF00',
        };

        for (const cell of this.detectionCells) {
            const threshold = this.classConfidence[cell.class_id] ?? 0.01;
            if (cell.confidence < threshold) continue;
            if (this.classVisibility[cell.class_id] === false) continue;
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

    // ── Annotation 그리기 ──

    setDrawMode(mode) {
        // mode: 'polygon' | 'rectangle' | 'point' | null
        this._cancelDrawing();
        this.drawMode = mode;
        this.canvas.style.cursor = mode ? 'crosshair' : 'grab';
        if (this.onDrawModeChange) this.onDrawModeChange(mode);
    }

    _onDrawMouseDown(sx, sy, cx, cy, e) {
        if (this.drawMode === 'polygon') {
            // 누르는 순간 시작, 드래그하면서 점 추가, 떼면 완성
            this._drawingPoints = [[sx, sy]];
            this._isDrawing = true;
            this._drawingCurrent = [sx, sy];
            this._lastDrawDragCanvas = [cx, cy];
            this.requestRender();
        } else if (this.drawMode === 'rectangle') {
            this._drawingStart = [sx, sy];
            this._drawingCurrent = [sx, sy];
            this._isDrawing = true;
        } else if (this.drawMode === 'point') {
            this._createAnnotation('point', [[sx, sy]]);
        }
    }

    _onDrawMouseMove(sx, sy, cx, cy) {
        this._drawingCurrent = [sx, sy];

        // 폴리곤 드래그로 점 추가 (10px 간격)
        if (this.drawMode === 'polygon' && this._drawingPoints.length > 0 && (cx !== undefined)) {
            if (this._lastDrawDragCanvas) {
                const ddx = cx - this._lastDrawDragCanvas[0];
                const ddy = cy - this._lastDrawDragCanvas[1];
                if (Math.sqrt(ddx * ddx + ddy * ddy) >= 10) {
                    this._drawingPoints.push([sx, sy]);
                    this._lastDrawDragCanvas = [cx, cy];
                }
            }
        }

        this.requestRender();
    }

    _onDrawMouseUp(sx, sy) {
        if (this.drawMode === 'polygon' && this._isDrawing) {
            // 마우스 떼면 폴리곤 완성 (최소 3점)
            if (this._drawingPoints.length >= 3) {
                this._finishPolygon();
            } else {
                this._cancelDrawing();
            }
            return;
        }
        if (this.drawMode === 'rectangle' && this._drawingStart) {
            const [x0, y0] = this._drawingStart;
            const w = Math.abs(sx - x0);
            const h = Math.abs(sy - y0);
            if (w > 5 / this.zoom && h > 5 / this.zoom) {
                const xMin = Math.min(x0, sx), yMin = Math.min(y0, sy);
                const xMax = Math.max(x0, sx), yMax = Math.max(y0, sy);
                this._createAnnotation('rectangle', [
                    [xMin, yMin], [xMax, yMin], [xMax, yMax], [xMin, yMax]
                ]);
            }
            this._drawingStart = null;
            this._drawingCurrent = null;
            this._isDrawing = false;
            this.requestRender();
        }
    }

    _finishPolygon() {
        if (this._drawingPoints.length >= 3) {
            // 자기교차(self-intersection) 검사 — 닫는 선분 포함
            if (this._isSelfIntersecting(this._drawingPoints)) {
                this._cancelDrawing();
                return;
            }
            this._createAnnotation('polygon', [...this._drawingPoints]);
        }
        this._drawingPoints = [];
        this._drawingCurrent = null;
        this._isDrawing = false;
        this._lastDrawDragCanvas = null;
        this.requestRender();
    }

    /** 폴리곤 선분들이 자기 자신과 교차하는지 검사 */
    _isSelfIntersecting(pts) {
        const n = pts.length;
        if (n < 4) return false; // 삼각형은 교차 불가
        // 닫힌 폴리곤의 모든 변(edge) 쌍 검사
        for (let i = 0; i < n; i++) {
            const a = pts[i], b = pts[(i + 1) % n];
            for (let j = i + 2; j < n; j++) {
                if (i === 0 && j === n - 1) continue; // 인접 변 (첫-끝) 건너뛰기
                const c = pts[j], d = pts[(j + 1) % n];
                if (this._segmentsIntersect(a, b, c, d)) return true;
            }
        }
        return false;
    }

    /** 두 선분 (p1-p2, p3-p4) 교차 판정 */
    _segmentsIntersect(p1, p2, p3, p4) {
        const d1 = this._cross(p3, p4, p1);
        const d2 = this._cross(p3, p4, p2);
        const d3 = this._cross(p1, p2, p3);
        const d4 = this._cross(p1, p2, p4);
        if (((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) &&
            ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))) return true;
        return false;
    }

    _cross(a, b, c) {
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    }

    _cancelDrawing() {
        this._drawingPoints = [];
        this._drawingStart = null;
        this._drawingCurrent = null;
        this._isDrawing = false;
        this._lastDrawDragCanvas = null;
        this.requestRender();
    }

    _createAnnotation(type, coordinates) {
        this._annotationCounter++;
        const COLORS = { polygon: [0, 255, 0], rectangle: [255, 0, 0], point: [0, 0, 255] };
        const NAMES = { polygon: 'ROI', rectangle: 'Rectangle', point: 'Point' };
        const ann = {
            id: crypto.randomUUID?.() || `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
            name: `${NAMES[type]}_${this._annotationCounter}`,
            type,
            coordinates,
            color: COLORS[type],
            visible: true,
            selected: false,
        };
        this.annotations.push(ann);
        this.selectAnnotation(ann.id);
        if (this.onAnnotationCreated) this.onAnnotationCreated(ann);
        this.requestRender();
        return ann;
    }

    selectAnnotation(id) {
        this.annotations.forEach(a => a.selected = (a.id === id));
        this.selectedAnnotationId = id;
        if (this.onAnnotationSelected) {
            this.onAnnotationSelected(this.annotations.find(a => a.id === id) || null);
        }
        this.requestRender();
    }

    deleteAnnotation(id) {
        this.annotations = this.annotations.filter(a => a.id !== id);
        if (this.selectedAnnotationId === id) {
            this.selectedAnnotationId = null;
            if (this.onAnnotationSelected) this.onAnnotationSelected(null);
        }
        this.requestRender();
    }

    clearAnnotations() {
        this.annotations = [];
        this.selectedAnnotationId = null;
        this._annotationCounter = 0;
        this.requestRender();
    }

    // ── Annotation 렌더링 ──

    _renderAnnotations(octx) {
        // 확정된 annotation
        for (const ann of this.annotations) {
            if (!ann.visible) continue;
            const [r, g, b] = ann.color;
            const strokeColor = `rgb(${r},${g},${b})`;
            const fillColor = `rgba(${r},${g},${b},0.1)`;
            const lineWidth = ann.selected ? 3 : 2;

            if (ann.type === 'polygon') {
                this._drawPolygon(octx, ann.coordinates, strokeColor, fillColor, lineWidth);
                if (ann.selected) this._drawControlPoints(octx, ann.coordinates, strokeColor);
            } else if (ann.type === 'rectangle') {
                this._drawPolygon(octx, ann.coordinates, strokeColor, fillColor, lineWidth);
                if (ann.selected) this._drawControlPoints(octx, ann.coordinates, strokeColor);
            } else if (ann.type === 'point') {
                const [cx, cy] = this.sceneToCanvas(ann.coordinates[0][0], ann.coordinates[0][1]);
                const radius = 6;
                octx.beginPath();
                octx.arc(cx, cy, radius, 0, Math.PI * 2);
                octx.fillStyle = strokeColor;
                octx.fill();
                if (ann.selected) {
                    octx.strokeStyle = '#fff';
                    octx.lineWidth = 2;
                    octx.stroke();
                }
            }
        }

        // 진행 중인 그리기 프리뷰
        this._renderDrawingPreview(octx);
    }

    _drawPolygon(octx, coords, strokeColor, fillColor, lineWidth) {
        if (coords.length < 2) return;
        octx.beginPath();
        const [cx0, cy0] = this.sceneToCanvas(coords[0][0], coords[0][1]);
        octx.moveTo(cx0, cy0);
        for (let i = 1; i < coords.length; i++) {
            const [cx, cy] = this.sceneToCanvas(coords[i][0], coords[i][1]);
            octx.lineTo(cx, cy);
        }
        octx.closePath();
        octx.fillStyle = fillColor;
        octx.fill();
        octx.strokeStyle = strokeColor;
        octx.lineWidth = lineWidth;
        octx.stroke();
    }

    _drawControlPoints(octx, coords, color) {
        for (const [sx, sy] of coords) {
            const [cx, cy] = this.sceneToCanvas(sx, sy);
            octx.beginPath();
            octx.arc(cx, cy, 5, 0, Math.PI * 2);
            octx.fillStyle = '#fff';
            octx.fill();
            octx.strokeStyle = color;
            octx.lineWidth = 2;
            octx.stroke();
        }
    }

    _renderDrawingPreview(octx) {
        if (this.drawMode === 'polygon' && this._drawingPoints.length > 0) {
            octx.beginPath();
            const [cx0, cy0] = this.sceneToCanvas(this._drawingPoints[0][0], this._drawingPoints[0][1]);
            octx.moveTo(cx0, cy0);
            for (let i = 1; i < this._drawingPoints.length; i++) {
                const [cx, cy] = this.sceneToCanvas(this._drawingPoints[i][0], this._drawingPoints[i][1]);
                octx.lineTo(cx, cy);
            }
            if (this._drawingCurrent) {
                const [cx, cy] = this.sceneToCanvas(this._drawingCurrent[0], this._drawingCurrent[1]);
                octx.lineTo(cx, cy);
            }
            octx.strokeStyle = 'rgba(0,255,0,0.8)';
            octx.lineWidth = 2;
            octx.setLineDash([6, 3]);
            octx.stroke();
            octx.setLineDash([]);

            // 시작점 표시
            octx.beginPath();
            octx.arc(cx0, cy0, 6, 0, Math.PI * 2);
            octx.fillStyle = 'rgba(0,255,0,0.6)';
            octx.fill();
            octx.strokeStyle = '#fff';
            octx.lineWidth = 1;
            octx.stroke();

            // 각 점
            for (const [sx, sy] of this._drawingPoints) {
                const [cx, cy] = this.sceneToCanvas(sx, sy);
                octx.beginPath();
                octx.arc(cx, cy, 3, 0, Math.PI * 2);
                octx.fillStyle = '#0f0';
                octx.fill();
            }
        }

        if (this.drawMode === 'rectangle' && this._drawingStart && this._drawingCurrent) {
            const [cx0, cy0] = this.sceneToCanvas(this._drawingStart[0], this._drawingStart[1]);
            const [cx1, cy1] = this.sceneToCanvas(this._drawingCurrent[0], this._drawingCurrent[1]);
            const x = Math.min(cx0, cx1), y = Math.min(cy0, cy1);
            const w = Math.abs(cx1 - cx0), h = Math.abs(cy1 - cy0);
            octx.fillStyle = 'rgba(255,0,0,0.1)';
            octx.fillRect(x, y, w, h);
            octx.strokeStyle = 'rgba(255,0,0,0.8)';
            octx.lineWidth = 2;
            octx.setLineDash([6, 3]);
            octx.strokeRect(x, y, w, h);
            octx.setLineDash([]);
        }
    }

    // ── Hit Testing ──

    /** 캔버스 좌표에서 선택된 annotation의 컨트롤포인트 히트 테스트 */
    _hitControlPoint(cx, cy) {
        const sel = this.annotations.find(a => a.id === this.selectedAnnotationId);
        if (!sel || !sel.visible) return null;
        const HIT_RADIUS = 8;
        for (let i = 0; i < sel.coordinates.length; i++) {
            const [pcx, pcy] = this.sceneToCanvas(sel.coordinates[i][0], sel.coordinates[i][1]);
            const dx = cx - pcx, dy = cy - pcy;
            if (dx * dx + dy * dy <= HIT_RADIUS * HIT_RADIUS) {
                return { annId: sel.id, pointIndex: i };
            }
        }
        return null;
    }

    /** scene 좌표에서 annotation 히트 테스트 (역순: 위에 그려진 것 우선) */
    _hitAnnotation(sx, sy) {
        for (let i = this.annotations.length - 1; i >= 0; i--) {
            const ann = this.annotations[i];
            if (!ann.visible) continue;

            if (ann.type === 'point') {
                const threshold = 15 / this.zoom;
                const dx = sx - ann.coordinates[0][0];
                const dy = sy - ann.coordinates[0][1];
                if (dx * dx + dy * dy <= threshold * threshold) return ann;
            } else if (ann.type === 'rectangle') {
                const xs = ann.coordinates.map(c => c[0]);
                const ys = ann.coordinates.map(c => c[1]);
                const xMin = Math.min(...xs), xMax = Math.max(...xs);
                const yMin = Math.min(...ys), yMax = Math.max(...ys);
                if (sx >= xMin && sx <= xMax && sy >= yMin && sy <= yMax) return ann;
            } else if (ann.type === 'polygon') {
                // Ray-casting algorithm
                if (this._pointInPolygon(sx, sy, ann.coordinates)) return ann;
            }
        }
        return null;
    }

    /** Ray-casting point-in-polygon test */
    _pointInPolygon(px, py, polygon) {
        let inside = false;
        for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
            const xi = polygon[i][0], yi = polygon[i][1];
            const xj = polygon[j][0], yj = polygon[j][1];
            if ((yi > py) !== (yj > py) && px < (xj - xi) * (py - yi) / (yj - yi) + xi) {
                inside = !inside;
            }
        }
        return inside;
    }

    /** annotation 중심으로 뷰 이동 */
    centerOnAnnotation(ann) {
        if (!ann || !ann.coordinates || ann.coordinates.length === 0) return;
        const xs = ann.coordinates.map(c => c[0]);
        const ys = ann.coordinates.map(c => c[1]);
        const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
        const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
        this.viewCenterX = cx;
        this.viewCenterY = cy;
        this._clampView();
        this.requestRender();
        if (this.onViewChange) this.onViewChange();
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
