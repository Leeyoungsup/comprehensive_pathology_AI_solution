/**
 * MeDICus Studio SaaS — 메인 앱
 * UI 이벤트 바인딩, 업로드, AI 분석 연동
 */

import { api } from './api.js';
import { TileViewer } from './tile-viewer.js';

// ── DOM ──
const $canvas = document.getElementById('wsi-canvas');
const $overlay = document.getElementById('overlay-canvas');
const $slideName = document.getElementById('slide-name');
const $zoomInfo = document.getElementById('zoom-info');
const $btnUpload = document.getElementById('btn-upload');
const $fileInput = document.getElementById('file-input');
const $uploadProgress = document.getElementById('upload-progress');
const $btnDetect = document.getElementById('btn-detect');
const $detectionProgress = document.getElementById('detection-progress');
const $detectionInfo = document.getElementById('detection-info');
const $classFilterPanel = document.getElementById('class-filter-panel');
const $classFilters = document.getElementById('class-filters');
const $confSlider = document.getElementById('conf-slider');
const $confValue = document.getElementById('conf-value');
const $btnZoomIn = document.getElementById('btn-zoom-in');
const $btnZoomOut = document.getElementById('btn-zoom-out');
const $btnFit = document.getElementById('btn-fit');
const $dropOverlay = document.getElementById('drop-overlay');
const $minimapContainer = document.getElementById('minimap-container');
const $minimapCanvas = document.getElementById('minimap-canvas');
const $minimapViewport = document.getElementById('minimap-viewport');

// ── 상태 ──
let currentSlideId = null;
let currentSlideInfo = null;
let minimapImage = null;

// ── 뷰어 초기화 ──
const viewer = new TileViewer($canvas, $overlay);

viewer.onZoomChange = (zoom, mag, mpp) => {
    $zoomInfo.textContent = `${mag.toFixed(1)}x | MPP: ${mpp.toFixed(3)} μm/px`;
};

viewer.onViewChange = () => {
    updateMinimap();
};

// ── 파일 업로드 ──

$btnUpload.addEventListener('click', () => $fileInput.click());
$fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) uploadFile(e.target.files[0]);
});

async function uploadFile(file) {
    const CHUNK_SIZE = 5 * 1024 * 1024; // 5MB

    $slideName.textContent = `업로드 중: ${file.name}`;
    $uploadProgress.hidden = false;
    setProgress($uploadProgress, 0);

    try {
        // 1. 업로드 시작
        const { upload_id } = await api.uploadStart(file.name);

        // 2. 청크 전송
        const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
        for (let i = 0; i < totalChunks; i++) {
            const start = i * CHUNK_SIZE;
            const end = Math.min(start + CHUNK_SIZE, file.size);
            const blob = file.slice(start, end);
            await api.uploadChunk(upload_id, i, blob);
            setProgress($uploadProgress, Math.round(((i + 1) / totalChunks) * 90));
        }

        // 3. 완료 — 슬라이드 열기
        setProgress($uploadProgress, 95);
        const slideInfo = await api.uploadComplete(upload_id, file.name, totalChunks);
        setProgress($uploadProgress, 100);

        // 슬라이드 로드
        onSlideLoaded(slideInfo.slide_id, slideInfo, file.name);

    } catch (err) {
        alert(`업로드 실패: ${err.message}`);
    } finally {
        setTimeout(() => { $uploadProgress.hidden = true; }, 1000);
    }
}

function onSlideLoaded(slideId, slideInfo, filename) {
    currentSlideId = slideId;
    currentSlideInfo = slideInfo;

    $slideName.textContent = filename;
    $btnDetect.disabled = false;

    // 뷰어 로드
    viewer.loadSlide(slideId, slideInfo);

    // 미니맵 로드
    loadMinimap(slideId, slideInfo);

    // 검출 결과 초기화
    $classFilterPanel.hidden = true;
    $detectionInfo.hidden = true;
}

// ── 드래그 앤 드롭 ──

const viewerContainer = document.getElementById('viewer-container');
viewerContainer.addEventListener('dragover', (e) => {
    e.preventDefault();
    $dropOverlay.classList.add('visible');
});
viewerContainer.addEventListener('dragleave', (e) => {
    if (!viewerContainer.contains(e.relatedTarget)) {
        $dropOverlay.classList.remove('visible');
    }
});
viewerContainer.addEventListener('drop', (e) => {
    e.preventDefault();
    $dropOverlay.classList.remove('visible');
    if (e.dataTransfer.files.length > 0) {
        uploadFile(e.dataTransfer.files[0]);
    }
});

// ── 미니맵 ──

async function loadMinimap(slideId, slideInfo) {
    const img = new Image();
    img.onload = () => {
        minimapImage = img;
        $minimapCanvas.width = img.width;
        $minimapCanvas.height = img.height;
        const ctx = $minimapCanvas.getContext('2d');
        ctx.drawImage(img, 0, 0);
        $minimapContainer.hidden = false;
        updateMinimap();
    };
    img.src = api.thumbnailUrl(slideId, 200);
}

function updateMinimap() {
    if (!minimapImage || !currentSlideInfo) return;

    const viewRect = viewer.getViewRect();
    if (!viewRect) return;

    const [imgW, imgH] = currentSlideInfo.dimensions;
    const mw = $minimapCanvas.width;
    const mh = $minimapCanvas.height;
    const scaleX = mw / imgW;
    const scaleY = mh / imgH;

    $minimapViewport.style.left = `${viewRect.x * scaleX}px`;
    $minimapViewport.style.top = `${viewRect.y * scaleY}px`;
    $minimapViewport.style.width = `${Math.max(4, viewRect.width * scaleX)}px`;
    $minimapViewport.style.height = `${Math.max(4, viewRect.height * scaleY)}px`;
}

// 미니맵 클릭 → 이동
$minimapCanvas.addEventListener('click', (e) => {
    if (!currentSlideInfo || !minimapImage) return;
    const rect = $minimapCanvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const [imgW, imgH] = currentSlideInfo.dimensions;
    const sceneX = (mx / $minimapCanvas.width) * imgW;
    const sceneY = (my / $minimapCanvas.height) * imgH;
    viewer.navigateTo(sceneX, sceneY);
});

// ── 줌 컨트롤 ──

$btnZoomIn.addEventListener('click', () => viewer.zoomIn());
$btnZoomOut.addEventListener('click', () => viewer.zoomOut());
$btnFit.addEventListener('click', () => viewer.fitToWindow());

// ── AI 검출 ──

$btnDetect.addEventListener('click', startDetection);

async function startDetection() {
    if (!currentSlideId) return;

    $btnDetect.disabled = true;
    $detectionProgress.hidden = false;
    $detectionInfo.hidden = false;
    $detectionInfo.textContent = '검출 시작 중...';
    setProgress($detectionProgress, 0);

    try {
        const { task_id } = await api.startDetection(currentSlideId);
        await pollTask(task_id);
    } catch (err) {
        $detectionInfo.textContent = `검출 실패: ${err.message}`;
        $btnDetect.disabled = false;
    }
}

async function pollTask(taskId) {
    while (true) {
        await sleep(1000);
        const status = await api.getTaskStatus(taskId);

        setProgress($detectionProgress, status.progress);
        $detectionInfo.textContent = `진행률: ${status.progress}%`;

        if (status.status === 'completed') {
            onDetectionComplete(status.result);
            return;
        } else if (status.status === 'error') {
            throw new Error(status.error);
        }
    }
}

function onDetectionComplete(result) {
    $detectionProgress.hidden = true;
    $detectionInfo.textContent = `검출 완료: ${result.total_cells}개 세포`;
    $btnDetect.disabled = false;

    // 뷰어에 결과 설정
    viewer.setDetectionResults(result.cells);

    // 클래스 필터 UI 생성
    buildClassFilters(result.class_names, result.class_colors);
}

function buildClassFilters(classNames, classColors) {
    $classFilters.innerHTML = '';
    for (const [id, name] of Object.entries(classNames)) {
        const classId = parseInt(id);
        const color = classColors[id] || '#FFFFFF';

        const item = document.createElement('div');
        item.className = 'class-filter-item';

        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = true;
        cb.addEventListener('change', () => {
            viewer.classVisibility[classId] = cb.checked;
            viewer.requestRender();
        });

        const dot = document.createElement('span');
        dot.className = 'class-color-dot';
        dot.style.backgroundColor = color;

        const label = document.createElement('span');
        label.textContent = name;

        item.append(cb, dot, label);
        $classFilters.appendChild(item);
    }

    $classFilterPanel.hidden = false;
}

// ── Confidence 슬라이더 ──

$confSlider.addEventListener('input', () => {
    const val = parseFloat($confSlider.value);
    $confValue.textContent = val.toFixed(2);
    viewer.confidenceThreshold = val;
    viewer.requestRender();
});

// ── 유틸리티 ──

function setProgress(el, percent) {
    el.querySelector('.progress-fill').style.width = `${percent}%`;
    el.querySelector('.progress-text').textContent = `${percent}%`;
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}
