/**
 * AI Detection Result Visualization
 * 데스크톱 detection_visualization_dialog.py를 웹 Canvas로 포팅
 * 4개 탭: Class Distribution, Tumor Analysis, Spatial Heatmap, Confidence Distribution
 */

const CLASS_NAMES = {
    0: 'Neutrophil', 1: 'Epithelial', 2: 'Lymphocyte', 3: 'Plasma',
    4: 'Eosinophil', 5: 'Connective tissue', 6: 'Tumor Epithelial', 7: 'Benign Epithelial',
};
const CLASS_COLORS = {
    0: '#FF4500', 1: '#00FF00', 2: '#0000FF', 3: '#FFFF00',
    4: '#8A2BE2', 5: '#808080', 6: '#FF0000', 7: '#00FF00',
};

const $vizDialog = document.querySelector('#viz-dialog');
const $closeViz = document.querySelector('#close-viz');

// Tab switching
$vizDialog?.querySelectorAll('.viz-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        $vizDialog.querySelectorAll('.viz-tab').forEach(t => t.classList.remove('active'));
        $vizDialog.querySelectorAll('.viz-panel').forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(tab.dataset.tab)?.classList.add('active');
    });
});
$closeViz?.addEventListener('click', () => $vizDialog.close());

/**
 * 시각화 다이얼로그 열기
 * @param {Array} cells - [{x, y, class_id, confidence}, ...]
 * @param {Object|null} segData - {thumbnail, overlays, class_names, width, height}
 */
export function showVisualization(cells, segData = null) {
    if (!$vizDialog || !cells || cells.length === 0) return;

    // 클래스별 데이터 수집
    const countsByClass = {};
    const confsByClass = {};
    for (const c of cells) {
        const id = c.class_id;
        countsByClass[id] = (countsByClass[id] || 0) + 1;
        if (!confsByClass[id]) confsByClass[id] = [];
        confsByClass[id].push(c.confidence);
    }

    _renderClassDistribution(cells, countsByClass);
    _renderTumorAnalysis(countsByClass);
    _renderSpatialHeatmap(cells, countsByClass, segData);
    _renderConfidenceDistribution(confsByClass);

    // 첫 번째 탭 활성화
    $vizDialog.querySelectorAll('.viz-tab').forEach((t, i) => t.classList.toggle('active', i === 0));
    $vizDialog.querySelectorAll('.viz-panel').forEach((p, i) => p.classList.toggle('active', i === 0));

    $vizDialog.showModal();
}

// ── Class Distribution 탭 ──
function _renderClassDistribution(cells, countsByClass) {
    const panel = document.getElementById('viz-class-dist');
    panel.innerHTML = '';

    const active = Object.entries(countsByClass).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
    if (active.length === 0) { panel.innerHTML = '<p>No detection data</p>'; return; }

    const row = document.createElement('div');
    row.className = 'viz-chart-row';

    // Bar chart
    const barCanvas = document.createElement('canvas');
    barCanvas.width = 400; barCanvas.height = 300;
    row.appendChild(barCanvas);

    // Pie chart
    const pieCanvas = document.createElement('canvas');
    pieCanvas.width = 360; pieCanvas.height = 300;
    row.appendChild(pieCanvas);

    panel.appendChild(row);

    // Draw bar chart
    const ctx = barCanvas.getContext('2d');
    const maxVal = Math.max(...active.map(([, v]) => v));
    const barH = Math.min(28, (280 / active.length) - 4);
    const leftPad = 130, rightPad = 60, topPad = 30;

    ctx.fillStyle = '#222';
    ctx.font = 'bold 13px sans-serif';
    ctx.fillText('Cell Count by Class', leftPad, 18);

    for (let i = 0; i < active.length; i++) {
        const [idStr, count] = active[i];
        const id = parseInt(idStr);
        const y = topPad + i * (barH + 4);
        const barW = (count / maxVal) * (barCanvas.width - leftPad - rightPad);

        ctx.fillStyle = CLASS_COLORS[id] || '#888';
        ctx.fillRect(leftPad, y, barW, barH);

        ctx.fillStyle = '#333';
        ctx.font = '11px sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText(CLASS_NAMES[id] || `Class ${id}`, leftPad - 6, y + barH / 2 + 4);

        ctx.textAlign = 'left';
        ctx.fillText(count.toLocaleString(), leftPad + barW + 4, y + barH / 2 + 4);
    }

    // Draw pie chart
    const pctx = pieCanvas.getContext('2d');
    const total = cells.length;
    const cx = 160, cy = 140, radius = 100;
    let startAngle = -Math.PI / 2;

    pctx.fillStyle = '#222';
    pctx.font = 'bold 13px sans-serif';
    pctx.textAlign = 'center';
    pctx.fillText(`Proportion (Total ${total.toLocaleString()})`, 180, 18);

    for (const [idStr, count] of active) {
        const id = parseInt(idStr);
        const sliceAngle = (count / total) * Math.PI * 2;
        pctx.beginPath();
        pctx.moveTo(cx, cy);
        pctx.arc(cx, cy, radius, startAngle, startAngle + sliceAngle);
        pctx.closePath();
        pctx.fillStyle = CLASS_COLORS[id] || '#888';
        pctx.fill();
        pctx.strokeStyle = '#fff';
        pctx.lineWidth = 1.5;
        pctx.stroke();

        // Label
        const pct = (count / total * 100);
        if (pct > 3) {
            const midAngle = startAngle + sliceAngle / 2;
            const lx = cx + Math.cos(midAngle) * radius * 0.65;
            const ly = cy + Math.sin(midAngle) * radius * 0.65;
            pctx.fillStyle = '#fff';
            pctx.font = 'bold 10px sans-serif';
            pctx.textAlign = 'center';
            pctx.fillText(`${pct.toFixed(1)}%`, lx, ly + 4);
        }
        startAngle += sliceAngle;
    }

    // Legend
    let ly = 260;
    pctx.font = '10px sans-serif';
    pctx.textAlign = 'left';
    for (const [idStr, count] of active) {
        const id = parseInt(idStr);
        const lx = (ly > 280) ? 180 : 10;
        pctx.fillStyle = CLASS_COLORS[id] || '#888';
        pctx.fillRect(lx, ly - 6, 8, 8);
        pctx.fillStyle = '#333';
        pctx.fillText(`${CLASS_NAMES[id]}  (${count.toLocaleString()})`, lx + 12, ly);
        ly += 14;
    }
}

// ── Tumor Analysis 탭 ──
function _renderTumorAnalysis(countsByClass) {
    const panel = document.getElementById('viz-tumor');
    panel.innerHTML = '';

    const tumor = countsByClass[6] || 0;
    const benign = countsByClass[7] || 0;
    const totalEpi = tumor + benign;
    const tumorRatio = totalEpi > 0 ? (tumor / totalEpi * 100) : 0;

    const row = document.createElement('div');
    row.className = 'viz-chart-row';

    // Pie: Tumor vs Benign
    const pieCanvas = document.createElement('canvas');
    pieCanvas.width = 350; pieCanvas.height = 280;
    row.appendChild(pieCanvas);

    // Gauge bar
    const gaugeCanvas = document.createElement('canvas');
    gaugeCanvas.width = 400; gaugeCanvas.height = 280;
    row.appendChild(gaugeCanvas);

    panel.appendChild(row);

    // Pie
    const pctx = pieCanvas.getContext('2d');
    pctx.fillStyle = '#222';
    pctx.font = 'bold 13px sans-serif';
    pctx.textAlign = 'center';
    pctx.fillText('Tumor vs Benign Epithelial', 175, 22);

    if (totalEpi > 0) {
        const cx = 175, cy = 150, r = 90;
        const data = [
            { val: tumor, color: '#E84040', label: `Tumor Epithelial (${tumor.toLocaleString()})` },
            { val: benign, color: '#2196F3', label: `Benign Epithelial (${benign.toLocaleString()})` },
        ];
        let start = -Math.PI / 2;
        for (const d of data) {
            const angle = (d.val / totalEpi) * Math.PI * 2;
            pctx.beginPath();
            pctx.moveTo(cx, cy);
            pctx.arc(cx, cy, r, start, start + angle);
            pctx.closePath();
            pctx.fillStyle = d.color;
            pctx.fill();
            pctx.strokeStyle = '#fff';
            pctx.lineWidth = 2;
            pctx.stroke();

            const pct = (d.val / totalEpi * 100);
            if (pct > 3) {
                const mid = start + angle / 2;
                pctx.fillStyle = '#fff';
                pctx.font = 'bold 13px sans-serif';
                pctx.fillText(`${pct.toFixed(1)}%`, cx + Math.cos(mid) * r * 0.6, cy + Math.sin(mid) * r * 0.6 + 5);
            }
            start += angle;
        }
        // Legend
        let ly = 255;
        pctx.font = '11px sans-serif';
        pctx.textAlign = 'left';
        for (const d of data) {
            pctx.fillStyle = d.color;
            pctx.fillRect(60, ly - 8, 10, 10);
            pctx.fillStyle = '#333';
            pctx.fillText(d.label, 76, ly);
            ly += 18;
        }
    } else {
        pctx.fillStyle = '#999';
        pctx.font = '14px sans-serif';
        pctx.fillText('No Epithelial cells', 175, 150);
    }

    // Gauge
    const gctx = gaugeCanvas.getContext('2d');
    gctx.fillStyle = '#222';
    gctx.font = 'bold 13px sans-serif';
    gctx.textAlign = 'center';
    gctx.fillText(`Tumor / (Tumor + Benign)  [${totalEpi.toLocaleString()} total]`, 200, 22);

    gctx.fillStyle = '#666';
    gctx.font = '12px sans-serif';
    gctx.fillText('Tumor Ratio', 200, 70);

    const barColor = tumorRatio >= 50 ? '#E84040' : tumorRatio >= 20 ? '#FF8C00' : '#FFB347';
    // Background bar
    const barX = 30, barY = 120, barW = 340, barH = 30;
    gctx.fillStyle = '#e0e0e0';
    _roundRect(gctx, barX, barY, barW, barH, 4);
    gctx.fill();
    // Value bar
    if (tumorRatio > 0) {
        gctx.fillStyle = barColor;
        _roundRect(gctx, barX, barY, barW * tumorRatio / 100, barH, 4);
        gctx.fill();
    }

    // Ratio text
    gctx.fillStyle = barColor;
    gctx.font = 'bold 36px sans-serif';
    gctx.fillText(`${tumorRatio.toFixed(1)}%`, 200, 110);

    // Tick labels
    gctx.fillStyle = '#888';
    gctx.font = '10px sans-serif';
    for (const pct of [0, 25, 50, 75, 100]) {
        const x = barX + barW * pct / 100;
        gctx.fillText(`${pct}%`, x, barY + barH + 16);
    }

    // Summary
    const summary = document.createElement('div');
    summary.className = 'viz-summary';
    summary.innerHTML = `<strong>Tumor Epithelial:</strong> ${tumor.toLocaleString()} &nbsp;|&nbsp; ` +
        `<strong>Benign Epithelial:</strong> ${benign.toLocaleString()} &nbsp;|&nbsp; ` +
        `<strong>Tumor Ratio:</strong> <span style="color:${barColor};font-weight:700">${tumorRatio.toFixed(1)}%</span>`;
    panel.appendChild(summary);
}

// ── Spatial Heatmap 탭 ──
function _renderSpatialHeatmap(cells, countsByClass, segData) {
    const panel = document.getElementById('viz-heatmap');
    panel.innerHTML = '';

    // segmentation 데이터가 있으면 썸네일 + seg overlay 표시 (데스크톱과 동일)
    if (segData && segData.overlays && segData.thumbnail) {
        _renderSegHeatmap(panel, segData);
        return;
    }

    // fallback: cell density heatmap
    if (cells.length === 0) { panel.innerHTML = '<p>No cell data</p>'; return; }

    let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
    for (const c of cells) {
        if (c.x < xMin) xMin = c.x; if (c.x > xMax) xMax = c.x;
        if (c.y < yMin) yMin = c.y; if (c.y > yMax) yMax = c.y;
    }
    const rangeW = xMax - xMin || 1, rangeH = yMax - yMin || 1;

    const scroll = document.createElement('div');
    scroll.className = 'viz-heatmap-scroll';

    const activeClasses = Object.entries(countsByClass).filter(([, v]) => v > 0);
    const panels = [{ label: 'All Cells', classId: null }, ...activeClasses.map(([id]) => ({
        label: CLASS_NAMES[parseInt(id)] || `Class ${id}`,
        classId: parseInt(id),
    }))];

    const canvasW = 760, canvasH = Math.max(80, Math.round(760 * rangeH / rangeW));
    const binsX = 100, binsY = Math.max(10, Math.round(binsX * rangeH / rangeW));

    for (const { label, classId } of panels) {
        const titleEl = document.createElement('div');
        titleEl.style.cssText = 'font-weight:600; font-size:12px; padding:4px 0; color:#333;';
        const subset = classId === null ? cells : cells.filter(c => c.class_id === classId);
        titleEl.textContent = `${label}  (n=${subset.length.toLocaleString()})`;
        scroll.appendChild(titleEl);

        const canvas = document.createElement('canvas');
        canvas.width = canvasW;
        canvas.height = Math.min(canvasH, 300);
        scroll.appendChild(canvas);

        _drawHeatmap(canvas, subset, xMin, yMin, rangeW, rangeH, binsX, binsY,
            classId === null ? null : CLASS_COLORS[classId]);
    }

    panel.appendChild(scroll);
}

/** Segmentation 히트맵: 썸네일 위에 클래스별 오버레이 (데스크톱 동일) */
function _renderSegHeatmap(panel, segData) {
    const scroll = document.createElement('div');
    scroll.className = 'viz-heatmap-scroll';

    const modeLabel = document.createElement('div');
    modeLabel.style.cssText = 'font-size:11px; color:#666; padding:4px 0 8px;';
    modeLabel.textContent = 'Mode: Segmentation probability heatmap';
    scroll.appendChild(modeLabel);

    const thumbSrc = `data:image/jpeg;base64,${segData.thumbnail}`;
    const dispW = Math.min(760, segData.width);
    const dispH = Math.round(dispW * segData.height / segData.width);

    for (const clsName of Object.keys(segData.overlays)) {
        const titleEl = document.createElement('div');
        titleEl.style.cssText = 'font-weight:600; font-size:12px; padding:6px 0 2px; color:#333;';
        titleEl.textContent = clsName;
        scroll.appendChild(titleEl);

        const canvas = document.createElement('canvas');
        canvas.width = dispW;
        canvas.height = dispH;
        canvas.style.cssText = 'border-radius:4px; border:1px solid #ddd; display:block; margin-bottom:8px;';
        scroll.appendChild(canvas);

        const ctx = canvas.getContext('2d');
        const overlaySrc = `data:image/png;base64,${segData.overlays[clsName]}`;

        // 썸네일 먼저, 그 위에 오버레이
        const thumbImg = new Image();
        const overlayImg = new Image();
        let loaded = 0;
        const onBothLoaded = () => {
            if (++loaded < 2) return;
            ctx.drawImage(thumbImg, 0, 0, dispW, dispH);
            ctx.drawImage(overlayImg, 0, 0, dispW, dispH);
        };
        thumbImg.onload = onBothLoaded;
        overlayImg.onload = onBothLoaded;
        thumbImg.src = thumbSrc;
        overlayImg.src = overlaySrc;
    }

    panel.appendChild(scroll);
}

function _drawHeatmap(canvas, cells, xMin, yMin, rangeW, rangeH, binsX, binsY, baseColor) {
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    ctx.fillStyle = '#e8e8e8';
    ctx.fillRect(0, 0, w, h);

    if (cells.length === 0) {
        ctx.fillStyle = '#999'; ctx.font = '12px sans-serif';
        ctx.textAlign = 'center'; ctx.fillText('No cells', w / 2, h / 2);
        return;
    }

    // histogram2d
    const grid = new Float32Array(binsY * binsX);
    for (const c of cells) {
        const col = Math.min(Math.floor((c.x - xMin) / rangeW * binsX), binsX - 1);
        const row = Math.min(Math.floor((c.y - yMin) / rangeH * binsY), binsY - 1);
        if (col >= 0 && row >= 0) grid[row * binsX + col]++;
    }

    // Gaussian blur (box blur 3 passes)
    const blurred = _blurGrid(grid, binsX, binsY, 3);
    let maxVal = 0;
    for (let i = 0; i < blurred.length; i++) if (blurred[i] > maxVal) maxVal = blurred[i];
    if (maxVal === 0) return;

    // Draw
    const imgData = ctx.createImageData(binsX, binsY);
    const data = imgData.data;
    for (let i = 0; i < blurred.length; i++) {
        const norm = blurred[i] / maxVal;
        if (norm < 0.01) { data[i * 4 + 3] = 0; continue; }
        let r, g, b;
        if (baseColor) {
            const br = parseInt(baseColor.slice(1, 3), 16);
            const bg = parseInt(baseColor.slice(3, 5), 16);
            const bb = parseInt(baseColor.slice(5, 7), 16);
            r = Math.round(br * norm); g = Math.round(bg * norm); b = Math.round(bb * norm);
        } else {
            [r, g, b] = _jetColor(norm);
        }
        data[i * 4] = r; data[i * 4 + 1] = g; data[i * 4 + 2] = b;
        data[i * 4 + 3] = Math.round(norm * 200);
    }

    const offscreen = new OffscreenCanvas(binsX, binsY);
    offscreen.getContext('2d').putImageData(imgData, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(offscreen, 0, 0, w, h);
}

// ── Confidence Distribution 탭 ──
function _renderConfidenceDistribution(confsByClass) {
    const panel = document.getElementById('viz-confidence');
    panel.innerHTML = '';

    const activeClasses = Object.entries(confsByClass).filter(([, v]) => v.length > 0);
    if (activeClasses.length === 0) { panel.innerHTML = '<p>No data</p>'; return; }

    const cols = Math.min(3, activeClasses.length);
    const chartW = 240, chartH = 180;
    const container = document.createElement('div');
    container.style.cssText = `display:flex; flex-wrap:wrap; gap:12px;`;

    for (const [idStr, confs] of activeClasses) {
        const id = parseInt(idStr);
        const canvas = document.createElement('canvas');
        canvas.width = chartW; canvas.height = chartH;
        container.appendChild(canvas);

        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#f8f8f8';
        ctx.fillRect(0, 0, chartW, chartH);

        // Title
        ctx.fillStyle = '#333';
        ctx.font = 'bold 11px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(`${CLASS_NAMES[id]} (n=${confs.length.toLocaleString()})`, chartW / 2, 14);

        // Histogram (20 bins, 0~1)
        const nBins = 20;
        const bins = new Float32Array(nBins);
        for (const v of confs) {
            const idx = Math.min(Math.floor(v * nBins), nBins - 1);
            if (idx >= 0) bins[idx]++;
        }
        const maxBin = Math.max(...bins, 1);
        const color = CLASS_COLORS[id] || '#4488CC';
        const plotLeft = 35, plotRight = chartW - 10, plotTop = 24, plotBottom = chartH - 24;
        const plotW = plotRight - plotLeft, plotH = plotBottom - plotTop;
        const binW = plotW / nBins;

        for (let i = 0; i < nBins; i++) {
            const barH = (bins[i] / maxBin) * plotH;
            ctx.fillStyle = color;
            ctx.globalAlpha = 0.8;
            ctx.fillRect(plotLeft + i * binW, plotBottom - barH, binW - 1, barH);
        }
        ctx.globalAlpha = 1;

        // Mean line
        const mean = confs.reduce((a, b) => a + b, 0) / confs.length;
        const meanX = plotLeft + mean * plotW;
        ctx.strokeStyle = '#555';
        ctx.setLineDash([4, 2]);
        ctx.beginPath();
        ctx.moveTo(meanX, plotTop);
        ctx.lineTo(meanX, plotBottom);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = '#555';
        ctx.font = '9px sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(`avg ${mean.toFixed(2)}`, meanX + 2, plotTop + 10);

        // Axes
        ctx.strokeStyle = '#ccc';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(plotLeft, plotTop);
        ctx.lineTo(plotLeft, plotBottom);
        ctx.lineTo(plotRight, plotBottom);
        ctx.stroke();

        ctx.fillStyle = '#888';
        ctx.font = '8px sans-serif';
        ctx.textAlign = 'center';
        for (const v of [0, 0.5, 1]) {
            ctx.fillText(v.toFixed(1), plotLeft + v * plotW, plotBottom + 12);
        }
        ctx.textAlign = 'center';
        ctx.fillText('Confidence', plotLeft + plotW / 2, chartH - 2);
    }

    panel.appendChild(container);
}

// ── Utility ──
function _blurGrid(src, w, h, passes) {
    let a = new Float32Array(src);
    let b = new Float32Array(w * h);
    for (let p = 0; p < passes; p++) {
        for (let y = 0; y < h; y++) {
            for (let x = 0; x < w; x++) {
                const l = x > 0 ? a[y * w + x - 1] : a[y * w + x];
                const c = a[y * w + x];
                const r = x < w - 1 ? a[y * w + x + 1] : a[y * w + x];
                b[y * w + x] = (l + c + r) / 3;
            }
        }
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

function _jetColor(t) {
    t = Math.max(0, Math.min(1, t));
    let r, g, b;
    if (t < 0.25) { r = 0; g = t * 4; b = 1; }
    else if (t < 0.5) { r = 0; g = 1; b = 1 - (t - 0.25) * 4; }
    else if (t < 0.75) { r = (t - 0.5) * 4; g = 1; b = 0; }
    else { r = 1; g = 1 - (t - 0.75) * 4; b = 0; }
    return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
}

function _roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
}
