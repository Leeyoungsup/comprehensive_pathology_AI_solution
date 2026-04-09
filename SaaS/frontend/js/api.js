/**
 * API 클라이언트 — FastAPI 백엔드와 통신
 */

const API_BASE = '/api';

export const api = {
    // ── 슬라이드 ──

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
    async uploadComplete(uploadId, filename, totalChunks) {
        const form = new FormData();
        form.append('upload_id', uploadId);
        form.append('filename', filename);
        form.append('total_chunks', totalChunks.toString());
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

    /** 썸네일 URL */
    thumbnailUrl(slideId, size = 300) {
        return `${API_BASE}/slides/${slideId}/thumbnail?size=${size}`;
    },

    // ── 타일 ──

    /** 타일 이미지 URL */
    tileUrl(slideId, level, tileX, tileY) {
        return `${API_BASE}/tiles/${slideId}/${level}/${tileX}/${tileY}.jpeg`;
    },

    /** stage level 조회 */
    async getStageLevel(slideId, effectiveMpp) {
        const res = await fetch(`${API_BASE}/tiles/${slideId}/stage-level?effective_mpp=${effectiveMpp}`);
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

    /** 작업 상태 조회 */
    async getTaskStatus(taskId) {
        const res = await fetch(`${API_BASE}/ai/task/${taskId}`);
        if (!res.ok) throw new Error(await res.text());
        return res.json();
    },
};
