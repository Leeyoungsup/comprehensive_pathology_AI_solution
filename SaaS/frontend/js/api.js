/**
 * API 클라이언트 — FastAPI 백엔드와 통신
 */

const API_BASE = '/api';

export const api = {
    // ── 슬라이드 ──

    /** 폴더 탐색 (하위 폴더 + 슬라이드 목록) */
    async browse(path = '') {
        const res = await fetch(`${API_BASE}/slides/browse?path=${encodeURIComponent(path)}`);
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },

    /** 서버에 파일이 있는지 확인 후 바로 열기 */
    async openSlide(filename, path = '') {
        const form = new FormData();
        form.append('filename', filename);
        form.append('path', path);
        const res = await fetch(`${API_BASE}/slides/open`, { method: 'POST', body: form });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },

    /** 폴더 생성 */
    async createFolder(path, name) {
        const form = new FormData();
        form.append('path', path);
        form.append('name', name);
        const res = await fetch(`${API_BASE}/slides/folder/create`, { method: 'POST', body: form });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },

    /** 폴더 이름 변경 */
    async renameFolder(path, newName) {
        const form = new FormData();
        form.append('path', path);
        form.append('new_name', newName);
        const res = await fetch(`${API_BASE}/slides/folder/rename`, { method: 'POST', body: form });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },

    /** 폴더 삭제 */
    async deleteFolder(path) {
        const form = new FormData();
        form.append('path', path);
        const res = await fetch(`${API_BASE}/slides/folder/delete`, { method: 'POST', body: form });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },

    /** 파일 이동 */
    async moveFile(filename, srcPath, dstPath) {
        const form = new FormData();
        form.append('filename', filename);
        form.append('src_path', srcPath);
        form.append('dst_path', dstPath);
        const res = await fetch(`${API_BASE}/slides/file/move`, { method: 'POST', body: form });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },

    /** 청크 업로드 시작 */
    async uploadStart(filename) {
        const form = new FormData();
        form.append('filename', filename);
        const res = await fetch(`${API_BASE}/slides/upload/start`, { method: 'POST', body: form });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },

    /** 청크 업로드 */
    async uploadChunk(uploadId, chunkIndex, blob) {
        const form = new FormData();
        form.append('upload_id', uploadId);
        form.append('chunk_index', chunkIndex.toString());
        form.append('chunk', blob);
        const res = await fetch(`${API_BASE}/slides/upload/chunk`, { method: 'POST', body: form });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },

    /** 청크 업로드 완료 */
    async uploadComplete(uploadId, filename, totalChunks, path = '') {
        const form = new FormData();
        form.append('upload_id', uploadId);
        form.append('filename', filename);
        form.append('total_chunks', totalChunks.toString());
        form.append('path', path);
        const res = await fetch(`${API_BASE}/slides/upload/complete`, { method: 'POST', body: form });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },

    /** 슬라이드 정보 */
    async getSlideInfo(slideId) {
        const res = await fetch(`${API_BASE}/slides/${slideId}/info`);
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },

    /** 썸네일 URL (slide_id 기반 — 슬라이드 열린 후) */
    thumbnailUrl(slideId, size = 300) {
        return `${API_BASE}/slides/${slideId}/thumbnail?size=${size}`;
    },

    /** 고해상도 프리뷰 URL (PDF 리포트용) */
    previewUrl(slideId, size = 2048) {
        return `${API_BASE}/slides/${slideId}/preview?size=${size}`;
    },

    /** 썸네일 URL (파일명 기반 — 리스트용, slide_manager 불필요) */
    thumbnailUrlByName(filename, path = '', size = 300) {
        return `${API_BASE}/slides/thumbnail-by-name?filename=${encodeURIComponent(filename)}&path=${encodeURIComponent(path)}&size=${size}`;
    },

    // ── 타일 ──

    /** 타일 이미지 URL (프리제네레이트된 정적 타일) */
    tileUrl(slideId, level, tileX, tileY) {
        return `${API_BASE}/tiles/${slideId}/${level}/${tileX}/${tileY}.jpeg`;
    },

    /** stage level 조회 */
    async getStageLevel(slideId, effectiveMpp) {
        const res = await fetch(`${API_BASE}/tiles/${slideId}/stage-level?effective_mpp=${effectiveMpp}`);
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },

    // ── 타일 생성 진행 상태 ──

    /** 타일 프리제네레이션 진행 상태 */
    async getTileProgress(slideId) {
        const res = await fetch(`${API_BASE}/slides/tile-progress/${slideId}`);
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },

    // ── Annotation ──

    /** annotation 저장 */
    async saveAnnotations(slideId, annotations) {
        const form = new FormData();
        form.append('data', JSON.stringify(annotations));
        const res = await fetch(`${API_BASE}/slides/${slideId}/annotations/save`, { method: 'POST', body: form });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },

    /** annotation 불러오기 */
    async loadAnnotations(slideId) {
        const res = await fetch(`${API_BASE}/slides/${slideId}/annotations/load`);
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },

    // ── AI ──

    /** 검출 시작 */
    async startDetection(slideId, roiPolygons = null, tissueType = 'Stomach') {
        const form = new FormData();
        form.append('slide_id', slideId);
        if (roiPolygons) form.append('roi_polygons', JSON.stringify(roiPolygons));
        form.append('tissue_type', tissueType);
        const res = await fetch(`${API_BASE}/ai/detect`, { method: 'POST', body: form });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },

    /** 검출 결과 내부 저장 */
    async saveDetectionResult(slideId, tissueType, result) {
        const form = new FormData();
        form.append('slide_id', slideId);
        form.append('tissue_type', tissueType);
        form.append('result', JSON.stringify(result));
        const res = await fetch(`${API_BASE}/ai/save-result`, { method: 'POST', body: form });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },

    /** 작업 상태 조회 */
    async getTaskStatus(taskId) {
        const res = await fetch(`${API_BASE}/ai/task/${taskId}`);
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },

    /** Virtual Stain (VS-IHC) 시작 */
    async startVirtualStain(slideId, stainType = 'ihc_membrane', roiPolygons = null, targetMpp = 2.0) {
        const form = new FormData();
        form.append('slide_id', slideId);
        form.append('stain_type', stainType);
        form.append('target_mpp', String(targetMpp));
        if (roiPolygons) form.append('roi_polygons', JSON.stringify(roiPolygons));
        const res = await fetch(`${API_BASE}/ai/virtual-stain`, { method: 'POST', body: form });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },

    /** Virtual Stain 결과 PNG URL (리포트/PDF용 풀해상도 composite) */
    virtualStainImageUrl(slideId, stainType = 'ihc_membrane', targetMpp = 2.0) {
        return `${API_BASE}/ai/virtual-stain/${slideId}/${stainType}.png?target_mpp=${targetMpp}&t=${Date.now()}`;
    },

    /** Virtual Stain 피라미드 타일 URL (뷰어 렌더용) */
    virtualStainTileUrl(slideId, stainType, targetMpp, level, tx, ty) {
        return `${API_BASE}/ai/virtual-stain/${slideId}/${stainType}/tile/${level}/${tx}_${ty}.jpeg?target_mpp=${targetMpp}`;
    },
};
