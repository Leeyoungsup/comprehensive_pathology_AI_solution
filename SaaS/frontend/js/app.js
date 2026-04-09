/**
 * MeDICus Studio SaaS — 메인 앱
 * 기존 PyQt5 viewer.py의 UI 로직을 JS로 포팅
 */

import { api } from './api.js';
import { TileViewer } from './tile-viewer.js';
import { showVisualization } from './visualization.js';

// ── DOM 요소 ──
const $ = (sel) => document.querySelector(sel);

const $canvas = $('#wsi-canvas');
const $overlay = $('#overlay-canvas');
const $slideName = $('#slide-name');
const $statusText = $('#status-text');
const $zoomInfo = $('#zoom-info');
const $fileInput = $('#file-input');
const $dropOverlay = $('#drop-overlay');
const $minimapContainer = $('#minimap-container');
const $minimapCanvas = $('#minimap-canvas');
const $minimapViewport = $('#minimap-viewport');
const $progressLabel = $('#progress-label');
const $progressBar = $('#progress-bar');
const $resultList = $('#result-list');
const $slideInfoDialog = $('#slide-info-dialog');
const $slideInfoContent = $('#slide-info-content');

// 툴바 버튼
const $btnOpen = $('#btn-open');
const $btnSave = $('#btn-save');
const $btnInfo = $('#btn-info');
const $btnFit = $('#btn-fit');
const $btnZoomIn = $('#btn-zoom-in');
const $btnZoomOut = $('#btn-zoom-out');
const $btnDetect = $('#btn-detect');
const $btnTumorSeg = $('#btn-tumor-seg');
const $btnVisualize = $('#btn-visualize');
const $btnClearResults = $('#btn-clear-results');
const $btnSaveResults = $('#btn-save-results');
const $btnLoadResults = $('#btn-load-results');
const $btnDrawPolygon = $('#btn-draw-polygon');
const $btnDrawRect = $('#btn-draw-rect');
const $btnDrawPoint = $('#btn-draw-point');

const $slideList = $('#slide-list');

// ── 상태 ──
let currentSlideId = null;
let currentSlideInfo = null;
let minimapImage = null;
let lastSegData = null;  // segmentation overlay data from epithelial classification

// ── 뷰어 초기화 ──
const viewer = new TileViewer($canvas, $overlay);

viewer.onZoomChange = (zoom, mag, mpp) => {
    $zoomInfo.textContent = `${mag.toFixed(1)}x  |  MPP ${mpp.toFixed(3)} μm/px`;
};
viewer.onViewChange = () => updateMinimap();

// ═══════════════════════════
// 탭 전환
// ═══════════════════════════
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        if (btn.disabled) return;
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        $(`#${btn.dataset.tab}`).classList.add('active');
    });
});

// ═══════════════════════════
// 파일 열기 + 업로드
// ═══════════════════════════
$btnOpen.addEventListener('click', () => $fileInput.click());
$fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) uploadFile(e.target.files[0]);
    e.target.value = '';  // 같은 파일 재선택 가능하도록
});

async function uploadFile(file) {
    $slideName.textContent = file.name;
    setStatus('확인 중...');

    try {
        // 1) 현재 폴더에서 이미 있는지 확인
        const check = await api.openSlide(file.name, currentBrowsePath);
        if (check.exists) {
            onSlideLoaded(check.slide_id, check, file.name);
            return;
        }

        // 2) 없으면 현재 폴더에 업로드
        const CHUNK_SIZE = 5 * 1024 * 1024;
        setStatus('업로드 중...');
        setProgress(0);

        const { upload_id } = await api.uploadStart(file.name);
        const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

        for (let i = 0; i < totalChunks; i++) {
            const start = i * CHUNK_SIZE;
            const blob = file.slice(start, Math.min(start + CHUNK_SIZE, file.size));
            await api.uploadChunk(upload_id, i, blob);
            setProgress(Math.round(((i + 1) / totalChunks) * 90), `Uploading... ${i + 1}/${totalChunks} chunks`);
        }

        setStatus('슬라이드 열는 중...');
        setProgress(95);
        const info = await api.uploadComplete(upload_id, file.name, totalChunks, currentBrowsePath);
        setProgress(100);

        onSlideLoaded(info.slide_id, info, file.name);
        loadSlideList();  // 리스트 갱신
    } catch (err) {
        setStatus(`실패: ${err.message}`);
    }
}

function onSlideLoaded(slideId, slideInfo, filename) {
    currentSlideId = slideId;
    currentSlideInfo = slideInfo;

    $slideName.textContent = filename;
    setStatus(`Loaded: ${slideInfo.dimensions[0]}x${slideInfo.dimensions[1]} (${slideInfo.level_count} levels)`);

    // 버튼 활성화
    $btnDetect.disabled = false;
    $btnTumorSeg.disabled = false;
    $btnInfo.disabled = false;
    $btnSave.disabled = false;
    document.querySelectorAll('.toggle-btn').forEach(b => b.disabled = false);

    // 뷰어 로드 (타일은 요청 시 즉석 생성 + 백그라운드 프리제네레이션)
    viewer.loadSlide(slideId, slideInfo);

    // 미니맵
    loadMinimap(slideId);

    // 결과 초기화
    clearResults();

    // annotation 자동 불러오기
    loadAnnotations();

    setProgress(0);
}

// ═══════════════════════════
// 드래그 앤 드롭
// ═══════════════════════════
const $viewerContainer = $('#viewer-container');
$viewerContainer.addEventListener('dragover', (e) => {
    e.preventDefault();
    $dropOverlay.classList.add('visible');
});
$viewerContainer.addEventListener('dragleave', (e) => {
    if (!$viewerContainer.contains(e.relatedTarget)) {
        $dropOverlay.classList.remove('visible');
    }
});
$viewerContainer.addEventListener('drop', (e) => {
    e.preventDefault();
    $dropOverlay.classList.remove('visible');
    if (e.dataTransfer.files.length > 0) uploadFile(e.dataTransfer.files[0]);
});

// ═══════════════════════════
// 미니맵
// ═══════════════════════════
async function loadMinimap(slideId) {
    const img = new Image();
    img.onload = () => {
        minimapImage = img;
        $minimapCanvas.width = img.width;
        $minimapCanvas.height = img.height;
        $minimapCanvas.getContext('2d').drawImage(img, 0, 0);
        $minimapContainer.hidden = false;
        updateMinimap();
    };
    img.src = api.thumbnailUrl(slideId, 200);
}

function updateMinimap() {
    if (!minimapImage || !currentSlideInfo) return;
    const vr = viewer.getViewRect();
    if (!vr) return;
    const [imgW, imgH] = currentSlideInfo.dimensions;
    const sx = $minimapCanvas.width / imgW;
    const sy = $minimapCanvas.height / imgH;
    $minimapViewport.style.left = `${vr.x * sx}px`;
    $minimapViewport.style.top = `${vr.y * sy}px`;
    $minimapViewport.style.width = `${Math.max(4, vr.width * sx)}px`;
    $minimapViewport.style.height = `${Math.max(4, vr.height * sy)}px`;
}

$minimapCanvas.addEventListener('click', (e) => {
    if (!currentSlideInfo) return;
    const rect = $minimapCanvas.getBoundingClientRect();
    const [imgW, imgH] = currentSlideInfo.dimensions;
    viewer.navigateTo(
        ((e.clientX - rect.left) / $minimapCanvas.width) * imgW,
        ((e.clientY - rect.top) / $minimapCanvas.height) * imgH
    );
});

// ═══════════════════════════
// 줌 컨트롤
// ═══════════════════════════
$btnZoomIn.addEventListener('click', () => viewer.zoomIn());
$btnZoomOut.addEventListener('click', () => viewer.zoomOut());
$btnFit.addEventListener('click', () => viewer.fitToWindow());

// ═══════════════════════════
// Annotation 그리기 도구
// ═══════════════════════════
const drawButtons = { polygon: $btnDrawPolygon, rectangle: $btnDrawRect, point: $btnDrawPoint };

function setDrawMode(mode) {
    // 같은 버튼 다시 클릭 → 해제
    const newMode = viewer.drawMode === mode ? null : mode;
    viewer.setDrawMode(newMode);
    Object.values(drawButtons).forEach(b => b.classList.remove('active'));
    if (newMode && drawButtons[newMode]) drawButtons[newMode].classList.add('active');
}

$btnDrawPolygon.addEventListener('click', () => setDrawMode('polygon'));
$btnDrawRect.addEventListener('click', () => setDrawMode('rectangle'));
$btnDrawPoint.addEventListener('click', () => setDrawMode('point'));

// ESC 등으로 drawMode가 변경될 때 버튼 동기화
viewer.onDrawModeChange = (mode) => {
    Object.values(drawButtons).forEach(b => b.classList.remove('active'));
    if (mode && drawButtons[mode]) drawButtons[mode].classList.add('active');
};

// ── Annotation Panel ──
const $annList = $('#annotation-list');
const $btnAnnClear = $('#btn-ann-clear');
const $btnAnnSave = $('#btn-ann-save');
const $btnAnnLoad = $('#btn-ann-load');

function renderAnnotationPanel() {
    if (!$annList) return;
    $annList.innerHTML = '';
    for (const ann of viewer.annotations) {
        const [r, g, b] = ann.color;
        const el = document.createElement('div');
        el.className = 'ann-item' + (ann.selected ? ' selected' : '');
        el.dataset.id = ann.id;
        el.innerHTML = `
            <input type="color" class="ann-color-swatch" value="${rgbToHex(r, g, b)}"
                   title="Change color" style="background:rgb(${r},${g},${b})">
            <span class="ann-name" title="Double-click to rename">${ann.name}</span>
            <span class="ann-type">${ann.type}</span>
            <button class="ann-btn-vis" title="Toggle visibility">${ann.visible ? '👁' : '👁‍🗨'}</button>
            <button class="ann-btn-del" title="Delete">✕</button>
        `;
        // 클릭 → 선택
        el.addEventListener('click', (e) => {
            if (e.target.closest('.ann-color-swatch') || e.target.closest('.ann-btn-vis') ||
                e.target.closest('.ann-btn-del') || e.target.closest('.ann-name-input')) return;
            viewer.selectAnnotation(ann.id);
        });
        // 더블클릭 이름 → 리네임
        el.querySelector('.ann-name').addEventListener('dblclick', (e) => {
            e.stopPropagation();
            const nameSpan = e.target;
            const input = document.createElement('input');
            input.className = 'ann-name-input';
            input.value = ann.name;
            nameSpan.replaceWith(input);
            input.focus();
            input.select();
            const finish = () => {
                ann.name = input.value.trim() || ann.name;
                if (viewer.onAnnotationChanged) viewer.onAnnotationChanged(ann);
                renderAnnotationPanel();
            };
            input.addEventListener('blur', finish);
            input.addEventListener('keydown', (ke) => { if (ke.key === 'Enter') input.blur(); });
        });
        // 색상 변경
        el.querySelector('.ann-color-swatch').addEventListener('input', (e) => {
            const hex = e.target.value;
            ann.color = hexToRgb(hex);
            e.target.style.background = `rgb(${ann.color[0]},${ann.color[1]},${ann.color[2]})`;
            if (viewer.onAnnotationChanged) viewer.onAnnotationChanged(ann);
            viewer.requestRender();
        });
        // 가시성 토글
        el.querySelector('.ann-btn-vis').addEventListener('click', (e) => {
            e.stopPropagation();
            ann.visible = !ann.visible;
            viewer.requestRender();
            renderAnnotationPanel();
        });
        // 삭제
        el.querySelector('.ann-btn-del').addEventListener('click', (e) => {
            e.stopPropagation();
            viewer.deleteAnnotation(ann.id);
        });
        $annList.appendChild(el);
    }
}

function rgbToHex(r, g, b) {
    return '#' + [r, g, b].map(v => v.toString(16).padStart(2, '0')).join('');
}
function hexToRgb(hex) {
    const m = hex.match(/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
    return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : [0, 255, 0];
}

// 캔버스 ↔ 패널 동기화
viewer.onAnnotationCreated = (ann) => {
    setStatus(`${ann.name} created`);
    renderAnnotationPanel();
};
viewer.onAnnotationSelected = (ann) => {
    renderAnnotationPanel();
};
viewer.onAnnotationDeleted = (ann) => {
    renderAnnotationPanel();
};
viewer.onAnnotationChanged = (ann) => {
    // 이미 렌더링 요청됨 — 패널만 갱신 필요 시
};

// deleteAnnotation에서 콜백 호출되도록 오버라이드
const _origDelete = viewer.deleteAnnotation.bind(viewer);
viewer.deleteAnnotation = (id) => {
    const ann = viewer.annotations.find(a => a.id === id);
    _origDelete(id);
    if (ann && viewer.onAnnotationDeleted) viewer.onAnnotationDeleted(ann);
};

// Clear All
$btnAnnClear?.addEventListener('click', () => {
    viewer.clearAnnotations();
    renderAnnotationPanel();
    setStatus('Annotations cleared');
});

// Save annotation
$btnAnnSave?.addEventListener('click', async () => {
    if (!currentSlideId || viewer.annotations.length === 0) return;
    try {
        const result = await api.saveAnnotations(currentSlideId, viewer.annotations);
        setStatus(`Annotations saved (${result.count})`);
    } catch (err) { setStatus(`Save failed: ${err.message}`); }
});
// 툴바 Save 버튼도 annotation 저장
$btnSave.addEventListener('click', async () => {
    if (!currentSlideId || viewer.annotations.length === 0) return;
    try {
        const result = await api.saveAnnotations(currentSlideId, viewer.annotations);
        setStatus(`Annotations saved (${result.count})`);
    } catch (err) { setStatus(`Save failed: ${err.message}`); }
});

// Load annotation
async function loadAnnotations() {
    if (!currentSlideId) return;
    try {
        const anns = await api.loadAnnotations(currentSlideId);
        if (anns.length > 0) {
            viewer.annotations = anns;
            viewer._annotationCounter = anns.length;
            viewer.requestRender();
            renderAnnotationPanel();
            setStatus(`Annotations loaded (${anns.length})`);
        }
    } catch { /* 없으면 무시 */ }
}
$btnAnnLoad?.addEventListener('click', loadAnnotations);

// ═══════════════════════════
// 슬라이드 정보 다이얼로그
// ═══════════════════════════
$btnInfo.addEventListener('click', () => {
    if (!currentSlideInfo) return;
    const info = currentSlideInfo;
    const mag = info.objective_power !== 'Unknown' ? `${info.objective_power}x` : '-';
    const physW = info.physical_width_mm?.toFixed(2) ?? '-';
    const physH = info.physical_height_mm?.toFixed(2) ?? '-';

    let html = '<table>';
    html += `<tr><td>Filename</td><td>${info.filename}</td></tr>`;
    html += `<tr><td>Vendor</td><td>${info.vendor}</td></tr>`;
    html += `<tr><td>Magnification</td><td>${mag}</td></tr>`;
    html += `<tr><td>Pixel Size</td><td>${info.dimensions[0].toLocaleString()} × ${info.dimensions[1].toLocaleString()} px</td></tr>`;
    html += `<tr><td>MPP</td><td>${info.mpp_x?.toFixed(4) ?? '-'} × ${info.mpp_y?.toFixed(4) ?? '-'} μm/px</td></tr>`;
    html += `<tr><td>Physical Size</td><td>${physW} × ${physH} mm</td></tr>`;
    html += '</table>';
    $slideInfoContent.innerHTML = html;
    $slideInfoDialog.showModal();
});
$('#close-slide-info').addEventListener('click', () => $slideInfoDialog.close());

// ═══════════════════════════
// AI 검출
// ═══════════════════════════
$btnDetect.addEventListener('click', startDetection);

async function startDetection() {
    if (!currentSlideId) return;
    $btnDetect.disabled = true;
    $progressLabel.textContent = 'Cell Detection...';
    setProgress(0);
    setStatus('검출 시작...');

    // AI 시작 → 그리기 모드 해제
    viewer.setDrawMode(null);

    try {
        const tissueType = document.querySelector('input[name="tissue-type"]:checked')?.value || 'Stomach';

        // point 제외한 polygon/rectangle annotation → ROI로 전달
        const roiAnnotations = viewer.annotations.filter(a => a.visible && a.type !== 'point' && a.coordinates.length >= 3);
        const roiPolygons = roiAnnotations.length > 0 ? roiAnnotations.map(a => a.coordinates) : null;

        const { task_id } = await api.startDetection(currentSlideId, roiPolygons, tissueType);

        // 폴링
        while (true) {
            await sleep(1000);
            const st = await api.getTaskStatus(task_id);
            const msg = st.status_msg || `${st.progress}%`;
            setProgress(st.progress, msg);
            setStatus(msg);

            // 진행 단계에 따라 라벨 업데이트
            if (st.progress <= 50) {
                $progressLabel.textContent = 'Cell Detection';
            } else if (st.progress < 92) {
                $progressLabel.textContent = 'WSI Segmentation';
            } else if (st.progress < 100) {
                $progressLabel.textContent = 'Epithelial Reclassification';
            }

            if (st.status === 'completed') {
                onDetectionComplete(st.result, roiPolygons);
                return;
            } else if (st.status === 'error') {
                throw new Error(st.error);
            }
        }
    } catch (err) {
        setStatus(`검출 실패: ${err.message}`);
    } finally {
        $btnDetect.disabled = false;
        $progressLabel.textContent = 'AI Progress';
    }
}

function onDetectionComplete(result, roiPolygons = null) {
    $progressLabel.textContent = 'Detection Complete';

    // AI 완료 → 기존 annotation 제거 (ROI 저장 후)
    viewer.clearAnnotations();
    renderAnnotationPanel();

    // segmentation 데이터 저장 (Spatial Heatmap 시각화용)
    lastSegData = result.seg_data || null;

    // ROI 폴리곤 내부 셀만 필터링하여 표시
    viewer.setDetectionResults(result.cells, roiPolygons);

    const displayCount = viewer.detectionCells.length;
    setProgress(100);
    setStatus(`Detection complete: ${displayCount.toLocaleString()} cells`);
    buildResultList(result);

    $btnVisualize.disabled = false;
    $btnClearResults.disabled = false;
    $btnSaveResults.disabled = false;
}

// ═══════════════════════════
// 결과 리스트 (기존 resultList 재현)
// ═══════════════════════════
const CLASS_COLORS = {
    0: '#FF4500', 1: '#00FF00', 2: '#0000FF', 3: '#FFFF00',
    4: '#8A2BE2', 5: '#808080', 6: '#FF0000', 7: '#00FF00',
};

// confidence 슬라이더 debounce용
let _confDebounceTimer = null;
function _debouncedRender() {
    if (_confDebounceTimer) clearTimeout(_confDebounceTimer);
    _confDebounceTimer = setTimeout(() => {
        viewer._heatmapDirty = true;
        viewer.requestRender();
    }, 150);
}

function buildResultList(result) {
    $resultList.innerHTML = '';

    // 클래스별 카운트
    const counts = {};
    for (const cell of result.cells) {
        counts[cell.class_id] = (counts[cell.class_id] || 0) + 1;
    }

    // 클래스별 체크박스 참조 저장
    const classCbs = {};

    // 총 셀 수 (전체 토글 체크박스)
    const totalItem = document.createElement('div');
    totalItem.className = 'result-item';

    const totalCb = document.createElement('input');
    totalCb.type = 'checkbox';
    totalCb.checked = true;
    totalCb.addEventListener('change', () => {
        const checked = totalCb.checked;
        for (const [id, cb] of Object.entries(classCbs)) {
            cb.checked = checked;
            viewer.classVisibility[parseInt(id)] = checked;
        }
        viewer._heatmapDirty = true;
        viewer.requestRender();
    });

    const totalName = document.createElement('span');
    totalName.className = 'class-name';
    totalName.style.fontWeight = '600';
    totalName.textContent = 'Total Cells';

    const totalCount = document.createElement('span');
    totalCount.className = 'class-count';
    totalCount.textContent = result.total_cells.toLocaleString();

    totalItem.append(totalCb, totalName, totalCount);
    $resultList.appendChild(totalItem);

    // 클래스별 항목 (체크박스 + 색상 + 이름 + 카운트 + 개별 confidence 슬라이더)
    for (const [idStr, name] of Object.entries(result.class_names)) {
        const id = parseInt(idStr);
        const count = counts[id] || 0;
        if (count === 0) continue;

        const color = CLASS_COLORS[id] || '#fff';

        const item = document.createElement('div');
        item.className = 'result-item';

        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = true;
        classCbs[id] = cb;
        cb.addEventListener('change', () => {
            viewer.classVisibility[id] = cb.checked;
            // 전체 체크박스 동기화
            const allChecked = Object.values(classCbs).every(c => c.checked);
            const noneChecked = Object.values(classCbs).every(c => !c.checked);
            totalCb.checked = allChecked;
            totalCb.indeterminate = !allChecked && !noneChecked;
            viewer._heatmapDirty = true;
            viewer.requestRender();
        });

        const dot = document.createElement('span');
        dot.className = 'class-dot';
        dot.style.backgroundColor = color;

        const nameSpan = document.createElement('span');
        nameSpan.className = 'class-name';
        nameSpan.textContent = name;

        const countSpan = document.createElement('span');
        countSpan.className = 'class-count';
        countSpan.textContent = count.toLocaleString();

        item.append(cb, dot, nameSpan, countSpan);
        $resultList.appendChild(item);

        // 개별 confidence 슬라이더
        const sliderRow = document.createElement('div');
        sliderRow.className = 'class-conf-slider';

        const sliderLabel = document.createElement('span');
        sliderLabel.className = 'conf-label';
        sliderLabel.textContent = '0.01';

        const slider = document.createElement('input');
        slider.type = 'range';
        slider.min = '0';
        slider.max = '1';
        slider.step = '0.01';
        slider.value = '0.01';
        slider.addEventListener('input', () => {
            const val = parseFloat(slider.value);
            sliderLabel.textContent = val.toFixed(2);
            viewer.classConfidence[id] = val;
            _debouncedRender();
        });

        sliderRow.append(slider, sliderLabel);
        $resultList.appendChild(sliderRow);
    }
}

function clearResults() {
    $resultList.innerHTML = '';
    $btnVisualize.disabled = true;
    $btnClearResults.disabled = true;
    $btnSaveResults.disabled = true;
    viewer.setDetectionResults([]);
    lastSegData = null;
}

$btnClearResults.addEventListener('click', clearResults);

$btnVisualize.addEventListener('click', () => {
    if (viewer.detectionCells.length === 0) return;
    showVisualization(viewer.detectionCells, lastSegData);
});

// ═══════════════════════════
// 유틸리티
// ═══════════════════════════
function setProgress(pct, statusMsg = '') {
    $progressBar.querySelector('.progress-fill').style.width = `${pct}%`;
    const $text = $('#progress-text');
    if (pct > 0 && pct < 100) {
        $text.textContent = statusMsg || `${pct}%`;
    } else if (pct >= 100) {
        $text.textContent = 'Complete';
    } else {
        $text.textContent = '';
    }
}

function setStatus(msg) {
    $statusText.textContent = msg;
}

function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
}

// ═══════════════════════════
// 좌측 패널 리사이즈
// ═══════════════════════════
const $leftPanel = $('#left-panel');
const $resizer = $('#left-panel-resizer');

$resizer.addEventListener('mousedown', (e) => {
    e.preventDefault();
    $resizer.classList.add('dragging');
    const startX = e.clientX;
    const startW = $leftPanel.offsetWidth;

    function onMove(ev) {
        const w = Math.max(140, Math.min(500, startW + ev.clientX - startX));
        $leftPanel.style.width = `${w}px`;
        viewer._resizeCanvas();
    }
    function onUp() {
        $resizer.classList.remove('dragging');
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
    }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
});

// ═══════════════════════════
// 좌측 슬라이드 리스트 + 폴더 탐색
// ═══════════════════════════
let currentBrowsePath = '';  // uploads/ 기준 상대경로
const $breadcrumb = $('#folder-breadcrumb');

async function loadSlideList() {
    try {
        const data = await api.browse(currentBrowsePath);
        $slideList.innerHTML = '';

        // 빈 폴더
        if (data.folders.length === 0 && data.slides.length === 0) {
            $slideList.innerHTML = '<div style="padding:12px;color:var(--text-dim);font-size:11px;text-align:center;">Empty</div>';
        }

        // 폴더 항목
        for (const f of data.folders) {
            const folderPath = currentBrowsePath ? `${currentBrowsePath}/${f.name}` : f.name;
            const item = document.createElement('div');
            item.className = 'slide-list-item folder-item';
            item.dataset.folderPath = folderPath;

            const icon = document.createElement('span');
            icon.className = 'folder-icon';
            icon.textContent = '📁';

            const name = document.createElement('div');
            name.className = 'slide-list-name';
            name.textContent = f.name;

            item.append(icon, name);

            // 더블클릭 → 폴더 진입
            item.addEventListener('dblclick', () => navigateToFolder(folderPath));
            // 우클릭 → 컨텍스트 메뉴
            item.addEventListener('contextmenu', (e) => {
                e.preventDefault();
                showFolderContextMenu(e, folderPath, f.name);
            });
            // 드래그 대상 (파일을 폴더에 드롭)
            item.addEventListener('dragover', (e) => { e.preventDefault(); item.classList.add('drag-over'); });
            item.addEventListener('dragleave', () => item.classList.remove('drag-over'));
            item.addEventListener('drop', async (e) => {
                e.preventDefault();
                item.classList.remove('drag-over');
                await _dropMoveFiles(e, folderPath);
            });

            $slideList.appendChild(item);
        }

        // 슬라이드 항목
        for (const s of data.slides) {
            const item = document.createElement('div');
            item.className = 'slide-list-item';
            item.dataset.filename = s.filename;
            item.dataset.slideId = s.slide_id;
            item.draggable = true;

            const thumb = document.createElement('img');
            thumb.className = 'slide-thumb';
            thumb.alt = s.filename;
            thumb.loading = 'lazy';
            thumb.src = api.thumbnailUrlByName(s.filename, currentBrowsePath, 96);
            thumb.onerror = () => { thumb.style.display = 'none'; };

            const name = document.createElement('div');
            name.className = 'slide-list-name';
            name.textContent = s.filename;
            name.title = `${s.filename} (${s.size_mb} MB)`;

            item.append(thumb, name);

            // 클릭: Ctrl/Shift 다중 선택, 일반 클릭은 단일 선택+열기
            item.addEventListener('click', (e) => {
                if (e.ctrlKey || e.metaKey) {
                    item.classList.toggle('selected');
                } else if (e.shiftKey) {
                    // Shift: 범위 선택
                    const allItems = [...$slideList.querySelectorAll('.slide-list-item:not(.folder-item)')];
                    const lastIdx = allItems.findIndex(el => el.classList.contains('selected'));
                    const curIdx = allItems.indexOf(item);
                    if (lastIdx >= 0 && curIdx >= 0) {
                        const [from, to] = lastIdx < curIdx ? [lastIdx, curIdx] : [curIdx, lastIdx];
                        for (let i = from; i <= to; i++) allItems[i].classList.add('selected');
                    } else {
                        item.classList.add('selected');
                    }
                } else {
                    // 단일 클릭 → 선택 초기화 + 열기
                    $slideList.querySelectorAll('.slide-list-item.selected').forEach(el => el.classList.remove('selected'));
                    item.classList.add('selected');
                    openSavedSlide(s.filename, item);
                }
            });

            // 드래그: 선택된 파일 전부 포함
            item.addEventListener('dragstart', (e) => {
                // 드래그 시작한 아이템이 선택 안 되어 있으면 단독 선택
                if (!item.classList.contains('selected')) {
                    $slideList.querySelectorAll('.slide-list-item.selected').forEach(el => el.classList.remove('selected'));
                    item.classList.add('selected');
                }
                const selectedFiles = [...$slideList.querySelectorAll('.slide-list-item.selected')]
                    .map(el => el.dataset.filename)
                    .filter(Boolean);
                e.dataTransfer.setData('text/filenames', JSON.stringify(selectedFiles));
                e.dataTransfer.setData('text/filename', selectedFiles[0]); // 호환
                e.dataTransfer.effectAllowed = 'move';
                requestAnimationFrame(() => {
                    $slideList.querySelectorAll('.slide-list-item.selected').forEach(el => el.classList.add('dragging'));
                });
            });
            item.addEventListener('dragend', () => {
                $slideList.querySelectorAll('.slide-list-item.dragging').forEach(el => el.classList.remove('dragging'));
            });

            $slideList.appendChild(item);
        }

        updateBreadcrumb();
    } catch (err) {
        console.error('슬라이드 목록 로드 실패:', err);
    }
}

function navigateToFolder(path) {
    currentBrowsePath = path;
    loadSlideList();
}

async function _dropMoveFiles(e, targetPath) {
    // 다중 파일 이동
    let filenames = [];
    try { filenames = JSON.parse(e.dataTransfer.getData('text/filenames') || '[]'); } catch {}
    if (!filenames.length) {
        const single = e.dataTransfer.getData('text/filename');
        if (single) filenames = [single];
    }
    if (!filenames.length || targetPath === currentBrowsePath) return;
    try {
        for (const fn of filenames) {
            await api.moveFile(fn, currentBrowsePath, targetPath);
        }
        loadSlideList();
        setStatus(`${filenames.length}개 파일 이동 완료`);
    } catch (err) { setStatus(`이동 실패: ${err.message}`); }
}

function _makeBreadcrumbDroppable(el, targetPath) {
    el.addEventListener('dragover', (e) => { e.preventDefault(); el.style.background = 'var(--accent-light)'; });
    el.addEventListener('dragleave', () => { el.style.background = ''; });
    el.addEventListener('drop', async (e) => {
        e.preventDefault();
        el.style.background = '';
        await _dropMoveFiles(e, targetPath);
    });
}

function updateBreadcrumb() {
    $breadcrumb.innerHTML = '';
    const root = document.createElement('span');
    root.className = 'breadcrumb-item';
    root.textContent = 'Root';
    root.addEventListener('click', () => navigateToFolder(''));
    _makeBreadcrumbDroppable(root, '');
    $breadcrumb.appendChild(root);

    if (currentBrowsePath) {
        const parts = currentBrowsePath.split('/');
        let accumulated = '';
        for (const part of parts) {
            accumulated = accumulated ? `${accumulated}/${part}` : part;
            const sep = document.createElement('span');
            sep.className = 'breadcrumb-sep';
            sep.textContent = '›';
            $breadcrumb.appendChild(sep);

            const crumb = document.createElement('span');
            crumb.className = 'breadcrumb-item';
            crumb.textContent = part;
            const targetPath = accumulated;
            crumb.addEventListener('click', () => navigateToFolder(targetPath));
            _makeBreadcrumbDroppable(crumb, targetPath);
            $breadcrumb.appendChild(crumb);
        }
    }
}

async function openSavedSlide(filename, itemEl) {
    setStatus('열는 중...');
    try {
        const info = await api.openSlide(filename, currentBrowsePath);
        if (info.exists) {
            $slideList.querySelectorAll('.slide-list-item').forEach(el => el.classList.remove('active'));
            if (itemEl) itemEl.classList.add('active');
            onSlideLoaded(info.slide_id, info, filename);
        }
    } catch (err) {
        setStatus(`열기 실패: ${err.message}`);
    }
}

// ── 폴더 생성 ──
$('#btn-new-folder').addEventListener('click', async () => {
    const name = prompt('새 폴더 이름:');
    if (!name || !name.trim()) return;
    try {
        await api.createFolder(currentBrowsePath, name.trim());
        loadSlideList();
    } catch (err) {
        alert(`폴더 생성 실패: ${err.message}`);
    }
});

// ── 폴더 우클릭 컨텍스트 메뉴 ──
let _ctxMenu = null;

function removeCtxMenu() {
    if (_ctxMenu) { _ctxMenu.remove(); _ctxMenu = null; }
}
document.addEventListener('click', removeCtxMenu);

function showFolderContextMenu(e, folderPath, folderName) {
    removeCtxMenu();
    const menu = document.createElement('div');
    menu.className = 'ctx-menu';
    menu.style.left = `${e.clientX}px`;
    menu.style.top = `${e.clientY}px`;

    const renameBtn = document.createElement('div');
    renameBtn.className = 'ctx-menu-item';
    renameBtn.textContent = 'Rename';
    renameBtn.addEventListener('click', async () => {
        removeCtxMenu();
        const newName = prompt('새 이름:', folderName);
        if (!newName || !newName.trim() || newName.trim() === folderName) return;
        try {
            await api.renameFolder(folderPath, newName.trim());
            loadSlideList();
        } catch (err) { alert(`이름 변경 실패: ${err.message}`); }
    });

    const deleteBtn = document.createElement('div');
    deleteBtn.className = 'ctx-menu-item danger';
    deleteBtn.textContent = 'Delete';
    deleteBtn.addEventListener('click', async () => {
        removeCtxMenu();
        if (!confirm(`"${folderName}" 폴더를 삭제하시겠습니까?`)) return;
        try {
            await api.deleteFolder(folderPath);
            loadSlideList();
        } catch (err) { alert(`삭제 실패: ${err.message}`); }
    });

    menu.append(renameBtn, deleteBtn);
    document.body.appendChild(menu);
    _ctxMenu = menu;
}

// ── 뷰 토글 (리스트 / 그리드) ──
const $btnViewList = $('#btn-view-list');
const $btnViewGrid = $('#btn-view-grid');

$btnViewList.addEventListener('click', () => {
    $slideList.classList.remove('grid-view');
    $btnViewList.classList.add('active');
    $btnViewGrid.classList.remove('active');
});
$btnViewGrid.addEventListener('click', () => {
    $slideList.classList.add('grid-view');
    $btnViewGrid.classList.add('active');
    $btnViewList.classList.remove('active');
});

// 페이지 로드 시 슬라이드 목록 가져오기
loadSlideList();
