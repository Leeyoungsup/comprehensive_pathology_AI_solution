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

// 가장 최근에 시각화된 데이터 (PDF export용)
let _vizState = null;

/**
 * 시각화 다이얼로그 열기
 * @param {Array} cells - [{x, y, class_id, confidence}, ...]
 * @param {Object|null} segData - {thumbnail, overlays, class_names, width, height}
 */
export function showVisualization(cells, segData = null, thumbnailUrl = null, meta = {}) {
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

    _vizState = {
        cells, countsByClass, confsByClass, segData,
        thumbnailUrl, thumbnailImg: null,
        slideName: meta.slideName || 'slide',
        tissue: meta.tissue || 'Stomach',
        slideDims: meta.slideDims || null,
    };

    // 썸네일 비동기 프리로드 (PDF용) — same-origin이므로 crossOrigin 불필요
    if (thumbnailUrl) {
        const img = new Image();
        img.onload = () => { if (_vizState) _vizState.thumbnailImg = img; };
        img.onerror = (e) => console.warn('[viz] thumbnail preload failed', e);
        img.src = thumbnailUrl;
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

// Export PDF 버튼
const $btnExportPdf = document.querySelector('#btn-export-pdf');
$btnExportPdf?.addEventListener('click', async () => {
    if (!_vizState) return;
    const orig = $btnExportPdf.textContent;
    $btnExportPdf.textContent = 'Generating...';
    $btnExportPdf.disabled = true;
    try {
        await _exportPDF(_vizState);
    } catch (e) {
        console.error(e);
        alert('PDF generation failed: ' + e.message);
    } finally {
        $btnExportPdf.textContent = orig;
        $btnExportPdf.disabled = false;
    }
});

// ── 애니메이션 유틸리티 ──
function _easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }
function _easeOutElastic(t) {
    if (t === 0 || t === 1) return t;
    return Math.pow(2, -10 * t) * Math.sin((t - 0.075) * (2 * Math.PI) / 0.3) + 1;
}

function _animate(duration, drawFn, onDone) {
    const start = performance.now();
    function step(now) {
        const t = Math.min((now - start) / duration, 1);
        drawFn(t);
        if (t < 1) requestAnimationFrame(step);
        else if (onDone) onDone();
    }
    requestAnimationFrame(step);
}

/** HiDPI 캔버스 생성: CSS 크기와 실제 픽셀 분리하여 선명하게 렌더링 */
function _createHiDPICanvas(cssW, cssH) {
    const dpr = window.devicePixelRatio || 1;
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    canvas.style.width = cssW + 'px';
    canvas.style.height = cssH + 'px';
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    // 논리 크기 저장 (draw 시 참조)
    canvas._cssW = cssW;
    canvas._cssH = cssH;
    return canvas;
}

// ── Class Distribution 탭 ──
function _renderClassDistribution(cells, countsByClass) {
    const panel = document.getElementById('viz-class-dist');
    panel.innerHTML = '';

    const active = Object.entries(countsByClass).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
    if (active.length === 0) { panel.innerHTML = '<p>No detection data</p>'; return; }

    const row = document.createElement('div');
    row.className = 'viz-chart-row';
    panel.appendChild(row);

    // 패널 실제 폭 기반 동적 크기
    const panelW = panel.clientWidth || 780;
    const gap = 16;
    const barW_canvas = Math.floor((panelW - gap) * 0.52);
    const pieW_canvas = Math.floor((panelW - gap) * 0.48);

    const barH_each = Math.min(28, (280 / active.length) - 4);
    const barH_canvas = Math.max(280, active.length * (barH_each + 4) + 40);
    const barCanvas = _createHiDPICanvas(barW_canvas, barH_canvas);
    row.appendChild(barCanvas);

    const legendH = active.length * 16 + 16;
    const pieRadius = Math.min(pieW_canvas / 2 - 20, 110);
    const pieH_canvas = pieRadius * 2 + 60 + legendH;
    const pieCanvas = _createHiDPICanvas(pieW_canvas, pieH_canvas);
    row.appendChild(pieCanvas);

    const total = cells.length;
    const maxVal = Math.max(...active.map(([, v]) => v));
    const leftPad = Math.min(130, barW_canvas * 0.32);
    const rightPad = 50;
    const topPad = 30;

    _animate(800, (t) => {
        const ease = _easeOutCubic(t);

        // ── Bar chart ──
        const ctx = barCanvas.getContext('2d');
        ctx.clearRect(0, 0, barW_canvas, barH_canvas);

        ctx.fillStyle = '#000';
        ctx.font = 'bold 15px sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText('Cell Count by Class', leftPad, 20);

        for (let i = 0; i < active.length; i++) {
            const [idStr, count] = active[i];
            const id = parseInt(idStr);
            const y = topPad + i * (barH_each + 4);
            const fullW = (count / maxVal) * (barW_canvas - leftPad - rightPad);
            const bw = fullW * ease;

            ctx.fillStyle = 'rgba(0,0,0,0.08)';
            _roundRect(ctx, leftPad + 1, y + 1, bw, barH_each, 3);
            ctx.fill();

            const grad = ctx.createLinearGradient(leftPad, y, leftPad + bw, y);
            const baseColor = CLASS_COLORS[id] || '#888';
            grad.addColorStop(0, baseColor);
            grad.addColorStop(1, _lightenColor(baseColor, 0.2));
            ctx.fillStyle = grad;
            _roundRect(ctx, leftPad, y, Math.max(0, bw), barH_each, 3);
            ctx.fill();

            ctx.fillStyle = '#000';
            ctx.font = 'bold 13px sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText(CLASS_NAMES[id] || `Class ${id}`, leftPad - 6, y + barH_each / 2 + 5);

            if (ease > 0.3) {
                ctx.textAlign = 'left';
                ctx.fillText(Math.round(count * ease).toLocaleString(), leftPad + bw + 6, y + barH_each / 2 + 5);
            }
        }

        // ── Pie chart ──
        const pctx = pieCanvas.getContext('2d');
        pctx.clearRect(0, 0, pieW_canvas, pieH_canvas);

        const cx = pieW_canvas / 2, cy = pieRadius + 30;
        const sweepTotal = Math.PI * 2 * ease;
        let startAngle = -Math.PI / 2;

        pctx.fillStyle = '#000';
        pctx.font = 'bold 15px sans-serif';
        pctx.textAlign = 'center';
        pctx.fillText(`Proportion (Total ${total.toLocaleString()})`, cx, 20);

        pctx.beginPath();
        pctx.arc(cx + 2, cy + 2, pieRadius, 0, Math.PI * 2);
        pctx.fillStyle = 'rgba(0,0,0,0.1)';
        pctx.fill();

        for (const [idStr, count] of active) {
            const id = parseInt(idStr);
            const sliceAngle = (count / total) * sweepTotal;
            pctx.beginPath();
            pctx.moveTo(cx, cy);
            pctx.arc(cx, cy, pieRadius, startAngle, startAngle + sliceAngle);
            pctx.closePath();
            pctx.fillStyle = CLASS_COLORS[id] || '#888';
            pctx.fill();
            pctx.strokeStyle = '#fff';
            pctx.lineWidth = 1.5;
            pctx.stroke();

            if (t > 0.7) {
                const pct = (count / total * 100);
                if (pct > 3) {
                    const labelAlpha = Math.min(1, (t - 0.7) / 0.3);
                    const midAngle = startAngle + sliceAngle / 2;
                    const lx = cx + Math.cos(midAngle) * pieRadius * 0.65;
                    const ly = cy + Math.sin(midAngle) * pieRadius * 0.65;
                    pctx.globalAlpha = labelAlpha;
                    pctx.fillStyle = '#fff';
                    pctx.font = 'bold 12px sans-serif';
                    pctx.textAlign = 'center';
                    pctx.fillText(`${pct.toFixed(1)}%`, lx, ly + 4);
                    pctx.globalAlpha = 1;
                }
            }
            startAngle += sliceAngle;
        }

        // 레전드 — 파이 아래
        if (t > 0.5) {
            const la = Math.min(1, (t - 0.5) / 0.3);
            pctx.globalAlpha = la;
            let ly = cy + pieRadius + 24;
            pctx.font = 'bold 12px sans-serif';
            pctx.textAlign = 'left';
            for (const [idStr, count] of active) {
                const id = parseInt(idStr);
                pctx.fillStyle = CLASS_COLORS[id] || '#888';
                pctx.fillRect(14, ly - 7, 10, 10);
                pctx.fillStyle = '#000';
                pctx.fillText(`${CLASS_NAMES[id]}  (${count.toLocaleString()})`, 30, ly);
                ly += 18;
            }
            pctx.globalAlpha = 1;
        }
    });
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
    panel.appendChild(row);

    const summary = document.createElement('div');
    summary.className = 'viz-summary';
    panel.appendChild(summary);

    // 패널 폭 기반 동적 크기
    const panelW = panel.clientWidth || 780;
    const gap = 16;
    const pieW = Math.floor((panelW - gap) * 0.45);
    const gaugeW = Math.floor((panelW - gap) * 0.55);
    const chartH = 290;

    const pieCanvas = _createHiDPICanvas(pieW, chartH);
    row.appendChild(pieCanvas);

    const gaugeCanvas = _createHiDPICanvas(gaugeW, chartH);
    row.appendChild(gaugeCanvas);

    const barColor = tumorRatio >= 50 ? '#E84040' : tumorRatio >= 20 ? '#FF8C00' : '#FFB347';
    const data = [
        { val: tumor, color: '#E84040', label: `Tumor Epithelial (${tumor.toLocaleString()})` },
        { val: benign, color: '#2196F3', label: `Benign Epithelial (${benign.toLocaleString()})` },
    ];

    _animate(900, (t) => {
        const ease = _easeOutCubic(t);
        const easeElastic = t < 0.5 ? _easeOutCubic(t * 2) : _easeOutElastic((t - 0.5) * 2) * 0.5 + 0.5;

        // ── Donut Pie ──
        const pctx = pieCanvas.getContext('2d');
        pctx.clearRect(0, 0, pieW, chartH);

        const pieCx = pieW / 2, pieCy = chartH / 2;
        const outerR = Math.min(pieCx, pieCy) - 30;
        const innerR = Math.max(20, outerR * 0.55);

        pctx.fillStyle = '#000';
        pctx.font = 'bold 15px sans-serif';
        pctx.textAlign = 'center';
        pctx.fillText('Tumor vs Benign Epithelial', pieCx, 20);

        if (totalEpi > 0) {
            const sweepTotal = Math.PI * 2 * ease;

            pctx.beginPath();
            pctx.arc(pieCx + 2, pieCy + 2, outerR, 0, Math.PI * 2);
            pctx.fillStyle = 'rgba(0,0,0,0.08)';
            pctx.fill();

            let start = -Math.PI / 2;
            for (const d of data) {
                const angle = (d.val / totalEpi) * sweepTotal;
                pctx.beginPath();
                pctx.arc(pieCx, pieCy, outerR, start, start + angle);
                pctx.arc(pieCx, pieCy, innerR, start + angle, start, true);
                pctx.closePath();
                pctx.fillStyle = d.color;
                pctx.fill();
                pctx.strokeStyle = '#fff';
                pctx.lineWidth = 2;
                pctx.stroke();

                if (t > 0.6) {
                    const pct = (d.val / totalEpi * 100);
                    if (pct > 3) {
                        const la = Math.min(1, (t - 0.6) / 0.3);
                        const mid = start + angle / 2;
                        const lr = (outerR + innerR) / 2;
                        pctx.globalAlpha = la;
                        pctx.fillStyle = '#fff';
                        pctx.font = 'bold 14px sans-serif';
                        pctx.fillText(`${pct.toFixed(1)}%`, pieCx + Math.cos(mid) * lr, pieCy + Math.sin(mid) * lr + 5);
                        pctx.globalAlpha = 1;
                    }
                }
                start += angle;
            }

            if (t > 0.4) {
                const ca = Math.min(1, (t - 0.4) / 0.3);
                pctx.globalAlpha = ca;
                pctx.fillStyle = '#000';
                pctx.font = 'bold 20px sans-serif';
                pctx.textAlign = 'center';
                pctx.fillText(Math.round(totalEpi * ease).toLocaleString(), pieCx, pieCy - 2);
                pctx.font = 'bold 12px sans-serif';
                pctx.fillStyle = '#000';
                pctx.fillText('cells', pieCx, pieCy + 16);
                pctx.globalAlpha = 1;
            }

            if (t > 0.5) {
                const la = Math.min(1, (t - 0.5) / 0.3);
                pctx.globalAlpha = la;
                let ly = chartH - 40;
                pctx.font = 'bold 13px sans-serif';
                pctx.textAlign = 'left';
                for (const d of data) {
                    pctx.fillStyle = d.color;
                    _roundRect(pctx, 14, ly - 9, 12, 12, 2); pctx.fill();
                    pctx.fillStyle = '#000';
                    pctx.fillText(d.label, 32, ly);
                    ly += 20;
                }
                pctx.globalAlpha = 1;
            }
        } else {
            pctx.fillStyle = '#000';
            pctx.font = 'bold 16px sans-serif';
            pctx.fillText('No Epithelial cells', pieCx, pieCy);
        }

        // ── Gauge ──
        const gctx = gaugeCanvas.getContext('2d');
        gctx.clearRect(0, 0, gaugeW, chartH);

        const gaugeCx = gaugeW / 2;

        gctx.fillStyle = '#000';
        gctx.font = 'bold 15px sans-serif';
        gctx.textAlign = 'center';
        gctx.fillText(`Tumor / (Tumor + Benign)  [${totalEpi.toLocaleString()} total]`, gaugeCx, 22);

        const animRatio = tumorRatio * easeElastic;
        gctx.fillStyle = barColor;
        gctx.font = 'bold 46px sans-serif';
        gctx.fillText(`${animRatio.toFixed(1)}%`, gaugeCx, 100);

        gctx.fillStyle = '#000';
        gctx.font = 'bold 13px sans-serif';
        gctx.fillText('Tumor Ratio', gaugeCx, 118);

        const barX = 20, barY = 140, barW = gaugeW - 40, barH = 28;
        gctx.fillStyle = '#e8e8e8';
        _roundRect(gctx, barX, barY, barW, barH, 6);
        gctx.fill();

        const fillW = barW * animRatio / 100;
        if (fillW > 0) {
            const grad = gctx.createLinearGradient(barX, barY, barX + fillW, barY);
            grad.addColorStop(0, _lightenColor(barColor, 0.15));
            grad.addColorStop(1, barColor);
            gctx.fillStyle = grad;
            _roundRect(gctx, barX, barY, fillW, barH, 6);
            gctx.fill();

            if (fillW > 10) {
                gctx.fillStyle = 'rgba(255,255,255,0.25)';
                _roundRect(gctx, barX, barY, fillW, barH / 2, 6);
                gctx.fill();
            }
        }

        gctx.fillStyle = '#000';
        gctx.font = 'bold 11px sans-serif';
        gctx.textAlign = 'center';
        for (const pct of [0, 25, 50, 75, 100]) {
            const x = barX + barW * pct / 100;
            gctx.fillText(`${pct}%`, x, barY + barH + 16);
            gctx.fillStyle = '#999';
            gctx.fillRect(x, barY + barH, 1, 4);
            gctx.fillStyle = '#000';
        }

        if (t > 0.7) {
            const za = Math.min(1, (t - 0.7) / 0.3);
            gctx.globalAlpha = za;
            const zones = [
                { x0: 0, x1: 20, label: 'Low', color: '#2E7D32' },
                { x0: 20, x1: 50, label: 'Moderate', color: '#E65100' },
                { x0: 50, x1: 100, label: 'High', color: '#C62828' },
            ];
            gctx.font = 'bold 11px sans-serif';
            for (const z of zones) {
                const zx = barX + barW * (z.x0 + z.x1) / 200;
                gctx.fillStyle = z.color;
                gctx.fillText(z.label, zx, barY + barH + 32);
            }
            gctx.globalAlpha = 1;
        }
    }, () => {
        summary.innerHTML = `<strong>Tumor Epithelial:</strong> ${tumor.toLocaleString()} &nbsp;|&nbsp; ` +
            `<strong>Benign Epithelial:</strong> ${benign.toLocaleString()} &nbsp;|&nbsp; ` +
            `<strong>Tumor Ratio:</strong> <span style="color:${barColor};font-weight:700">${tumorRatio.toFixed(1)}%</span>`;
        summary.style.animation = 'fadeIn 0.3s ease';
    });
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
        titleEl.style.cssText = 'font-weight:700; font-size:14px; padding:4px 0; color:#000;';
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
    modeLabel.style.cssText = 'font-size:13px; color:#000; font-weight:600; padding:4px 0 8px;';
    modeLabel.textContent = 'Mode: Segmentation probability heatmap';
    scroll.appendChild(modeLabel);

    const thumbSrc = `data:image/jpeg;base64,${segData.thumbnail}`;
    const dispW = Math.min(760, segData.width);
    const dispH = Math.round(dispW * segData.height / segData.width);

    for (const clsName of Object.keys(segData.overlays)) {
        const titleEl = document.createElement('div');
        titleEl.style.cssText = 'font-weight:700; font-size:14px; padding:6px 0 2px; color:#000;';
        titleEl.textContent = clsName;
        scroll.appendChild(titleEl);

        const canvas = _createHiDPICanvas(dispW, dispH);
        canvas.style.cssText += '; border-radius:4px; border:1px solid #ddd; display:block; margin-bottom:8px;';
        scroll.appendChild(canvas);

        const ctx = canvas.getContext('2d');
        const overlaySrc = `data:image/png;base64,${segData.overlays[clsName]}`;

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

    const chartW = 240, chartH = 180;
    const container = document.createElement('div');
    container.style.cssText = `display:flex; flex-wrap:wrap; gap:12px;`;

    for (const [idStr, confs] of activeClasses) {
        const id = parseInt(idStr);
        const canvas = _createHiDPICanvas(chartW, chartH);
        container.appendChild(canvas);

        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#f8f8f8';
        ctx.fillRect(0, 0, chartW, chartH);

        // Title
        ctx.fillStyle = '#000';
        ctx.font = 'bold 13px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(`${CLASS_NAMES[id]} (n=${confs.length.toLocaleString()})`, chartW / 2, 16);

        // Histogram (20 bins, 0~1)
        const nBins = 20;
        const bins = new Float32Array(nBins);
        for (const v of confs) {
            const idx = Math.min(Math.floor(v * nBins), nBins - 1);
            if (idx >= 0) bins[idx]++;
        }
        const maxBin = Math.max(...bins, 1);
        const color = CLASS_COLORS[id] || '#4488CC';
        const plotLeft = 38, plotRight = chartW - 10, plotTop = 26, plotBottom = chartH - 28;
        const plotW = plotRight - plotLeft, plotH = plotBottom - plotTop;
        const binW = plotW / nBins;

        for (let i = 0; i < nBins; i++) {
            const barH = (bins[i] / maxBin) * plotH;
            ctx.fillStyle = color;
            ctx.globalAlpha = 0.85;
            ctx.fillRect(plotLeft + i * binW, plotBottom - barH, binW - 1, barH);
        }
        ctx.globalAlpha = 1;

        // Mean line
        const mean = confs.reduce((a, b) => a + b, 0) / confs.length;
        const meanX = plotLeft + mean * plotW;
        ctx.strokeStyle = '#000';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 2]);
        ctx.beginPath();
        ctx.moveTo(meanX, plotTop);
        ctx.lineTo(meanX, plotBottom);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = '#000';
        ctx.font = 'bold 11px sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(`avg ${mean.toFixed(2)}`, meanX + 3, plotTop + 12);

        // Axes
        ctx.strokeStyle = '#666';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(plotLeft, plotTop);
        ctx.lineTo(plotLeft, plotBottom);
        ctx.lineTo(plotRight, plotBottom);
        ctx.stroke();

        ctx.fillStyle = '#000';
        ctx.font = 'bold 10px sans-serif';
        ctx.textAlign = 'center';
        for (const v of [0, 0.5, 1]) {
            ctx.fillText(v.toFixed(1), plotLeft + v * plotW, plotBottom + 14);
        }
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

function _lightenColor(hex, amount) {
    let r = parseInt(hex.slice(1, 3), 16);
    let g = parseInt(hex.slice(3, 5), 16);
    let b = parseInt(hex.slice(5, 7), 16);
    r = Math.min(255, Math.round(r + (255 - r) * amount));
    g = Math.min(255, Math.round(g + (255 - g) * amount));
    b = Math.min(255, Math.round(b + (255 - b) * amount));
    return `rgb(${r},${g},${b})`;
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

// ─────────────────────────── PDF EXPORT ───────────────────────────
// 데스크톱 detection_visualization_dialog.py의 PDF 레이아웃을 웹 Canvas로 포팅
// jsPDF는 동적 import (CDN ESM)

const PDF_W = 2100, PDF_H = 1485;  // 논리 좌표 (모든 draw 함수가 사용)
const PDF_SCALE = 2;               // 물리 픽셀 배율 — 출력 선명도 향상
const PDF_COL = {
    bg: '#FFFFFF', panel: '#F3F4F6', panelBorder: '#E5E7EB',
    text: '#111827', subtext: '#6B7280', accent: '#1E3A8A',
    tumor: '#DC2626', benign: '#16A34A',
};

async function _exportPDF(state) {
    const { jsPDF } = await import('https://cdn.jsdelivr.net/npm/jspdf@2.5.2/+esm');

    // 썸네일이 아직 로드 중이면 잠시 대기
    if (state.thumbnailUrl && !state.thumbnailImg) {
        try {
            const img = await _loadImage(state.thumbnailUrl);
            state.thumbnailImg = img;
        } catch (e) { /* 실패 시 흰 배경 fallback */ }
    }

    const pdf = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' });
    const pageW = 297, pageH = 210;

    const pages = [
        _pdfDrawCover(state),
        _pdfDrawClassDist(state),
        _pdfDrawTumorAnalysis(state),
        _pdfDrawSpatialHeatmap(state),
        _pdfDrawConfidence(state),
    ];
    pages.forEach((canvas, i) => {
        if (i > 0) pdf.addPage();
        pdf.addImage(canvas.toDataURL('image/jpeg', 0.92), 'JPEG', 0, 0, pageW, pageH);
    });

    const safeName = (state.slideName || 'slide').replace(/[\\/:*?"<>|]/g, '_');
    const filename = `${safeName}_HE-Fit_${state.tissue || 'Stomach'}_report.pdf`;

    // File System Access API 사용 가능 시 저장 위치 선택창
    const blob = pdf.output('blob');
    if (window.showSaveFilePicker) {
        try {
            const handle = await window.showSaveFilePicker({
                suggestedName: filename,
                types: [{ description: 'PDF Document', accept: { 'application/pdf': ['.pdf'] } }],
            });
            const writable = await handle.createWritable();
            await writable.write(blob);
            await writable.close();
            return;
        } catch (e) {
            if (e.name === 'AbortError') return;  // 사용자 취소
            // 그 외 오류는 다운로드로 fallback
        }
    }
    // Fallback: 브라우저 다운로드
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

function _loadImage(src) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error('image load failed: ' + src));
        img.src = src;
    });
}

function _pdfNewCanvas() {
    const c = document.createElement('canvas');
    c.width = PDF_W * PDF_SCALE;
    c.height = PDF_H * PDF_SCALE;
    const ctx = c.getContext('2d');
    ctx.scale(PDF_SCALE, PDF_SCALE);
    ctx.fillStyle = PDF_COL.bg;
    ctx.fillRect(0, 0, PDF_W, PDF_H);
    return c;
}

function _pdfPanel(ctx, x, y, w, h) {
    ctx.fillStyle = PDF_COL.panel;
    _roundRect(ctx, x, y, w, h, 16);
    ctx.fill();
    ctx.strokeStyle = PDF_COL.panelBorder;
    ctx.lineWidth = 2;
    ctx.stroke();
}

function _pdfHeader(ctx, title) {
    ctx.fillStyle = PDF_COL.accent;
    ctx.fillRect(0, 0, PDF_W, 130);
    ctx.fillStyle = '#FFFFFF';
    ctx.font = 'bold 56px Segoe UI, Arial, sans-serif';
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    ctx.fillText(title, 60, 65);
    ctx.font = '28px Segoe UI, Arial, sans-serif';
    ctx.textAlign = 'right';
    ctx.fillStyle = '#CBD5E1';
    ctx.fillText(new Date().toLocaleString(), PDF_W - 60, 65);
    // footer
    ctx.fillStyle = PDF_COL.subtext;
    ctx.font = '20px Segoe UI, Arial, sans-serif';
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';
    ctx.fillText('MeDICus Studio · AI Detection Report', 60, PDF_H - 35);
    ctx.textAlign = 'right';
    ctx.fillText('Generated by AI Visualization', PDF_W - 60, PDF_H - 35);
}

function _pdfDrawCover(state) {
    const { cells, countsByClass } = state;
    const c = _pdfNewCanvas();
    const ctx = c.getContext('2d');
    _pdfHeader(ctx, 'AI Detection Result Report');

    // Top stat panel
    const px = 100, py = 200, pw = PDF_W - 200, ph = 300;
    _pdfPanel(ctx, px, py, pw, ph);

    ctx.fillStyle = PDF_COL.subtext;
    ctx.font = '32px Segoe UI, Arial, sans-serif';
    ctx.textBaseline = 'top';
    ctx.textAlign = 'left';
    ctx.fillText('Total Detected Cells', px + 60, py + 50);
    ctx.fillStyle = PDF_COL.accent;
    ctx.font = 'bold 140px Segoe UI, Arial, sans-serif';
    ctx.fillText(cells.length.toLocaleString(), px + 60, py + 100);

    const tumor = countsByClass[6] || 0;
    const benign = countsByClass[7] || 0;
    const denom = tumor + benign;
    const ratio = denom > 0 ? (tumor / denom * 100) : 0;
    ctx.fillStyle = PDF_COL.subtext;
    ctx.font = '32px Segoe UI, Arial, sans-serif';
    ctx.fillText('Tumor Proportion (Tumor / Tumor+Benign)', px + 1050, py + 50);
    ctx.fillStyle = denom > 0 ? PDF_COL.tumor : PDF_COL.subtext;
    ctx.font = 'bold 140px Segoe UI, Arial, sans-serif';
    ctx.fillText(denom > 0 ? ratio.toFixed(1) + '%' : 'N/A', px + 1050, py + 100);

    // Class breakdown panel
    const tx = 100, ty = 560, tw = PDF_W - 200, th = 760;
    _pdfPanel(ctx, tx, ty, tw, th);
    ctx.fillStyle = PDF_COL.text;
    ctx.font = 'bold 36px Segoe UI, Arial, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText('Class Breakdown', tx + 40, ty + 30);

    const classIds = Object.keys(countsByClass).map(Number).sort((a, b) => countsByClass[b] - countsByClass[a]);
    const total = cells.length;
    const rowH = Math.min(70, (th - 130) / Math.max(classIds.length, 1));
    let yy = ty + 110;
    for (const id of classIds) {
        const name = CLASS_NAMES[id] || `Class ${id}`;
        const count = countsByClass[id];
        const pct = total > 0 ? (count / total * 100) : 0;

        ctx.fillStyle = CLASS_COLORS[id] || '#888';
        ctx.fillRect(tx + 50, yy + 10, 32, 32);

        ctx.fillStyle = PDF_COL.text;
        ctx.font = '28px Segoe UI, Arial, sans-serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.fillText(name, tx + 100, yy + 12);

        ctx.textAlign = 'right';
        ctx.font = 'bold 28px Segoe UI, Arial, sans-serif';
        ctx.fillText(count.toLocaleString(), tx + tw - 460, yy + 12);

        const barX = tx + tw - 420, barY = yy + 18, barW = 280, barH = 22;
        ctx.fillStyle = '#E5E7EB';
        ctx.fillRect(barX, barY, barW, barH);
        ctx.fillStyle = CLASS_COLORS[id] || '#888';
        ctx.fillRect(barX, barY, barW * (pct / 100), barH);

        ctx.fillStyle = PDF_COL.subtext;
        ctx.font = '24px Segoe UI, Arial, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(pct.toFixed(1) + '%', barX + barW + 12, yy + 14);

        yy += rowH;
        if (yy > ty + th - 50) break;
    }

    return c;
}

function _pdfDrawClassDist(state) {
    const { countsByClass } = state;
    const c = _pdfNewCanvas();
    const ctx = c.getContext('2d');
    _pdfHeader(ctx, 'Class Distribution');

    const ids = Object.keys(countsByClass).map(Number).sort((a, b) => countsByClass[b] - countsByClass[a]);
    const total = ids.reduce((s, i) => s + countsByClass[i], 0);
    if (total === 0) return c;

    // Bar chart left
    const bx = 100, by = 200, bw = 1100, bh = 1170;
    _pdfPanel(ctx, bx, by, bw, bh);
    ctx.fillStyle = PDF_COL.text;
    ctx.font = 'bold 36px Segoe UI, Arial, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText('Cell Counts', bx + 40, by + 30);

    const maxCnt = Math.max(...ids.map(i => countsByClass[i]), 1);
    const chartTop = by + 110;
    const chartH = bh - 160;
    const rowH = chartH / Math.max(ids.length, 1);
    const labelW = 320;
    const barX0 = bx + labelW + 20;
    const barMaxW = bx + bw - barX0 - 220;

    for (let i = 0; i < ids.length; i++) {
        const id = ids[i];
        const cnt = countsByClass[id];
        const yc = chartTop + i * rowH + rowH * 0.5;
        const bH = rowH * 0.6;

        ctx.fillStyle = PDF_COL.text;
        ctx.font = '28px Segoe UI, Arial, sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillText(CLASS_NAMES[id] || `Class ${id}`, barX0 - 15, yc);

        const bW = (cnt / maxCnt) * barMaxW;
        ctx.fillStyle = CLASS_COLORS[id] || '#888';
        ctx.fillRect(barX0, yc - bH / 2, bW, bH);

        ctx.fillStyle = PDF_COL.text;
        ctx.textAlign = 'left';
        ctx.font = 'bold 28px Segoe UI, Arial, sans-serif';
        ctx.fillText(cnt.toLocaleString(), barX0 + bW + 14, yc);
    }

    // Pie chart right
    const px = 1250, py = 200, pw = 750, ph = 1170;
    _pdfPanel(ctx, px, py, pw, ph);
    ctx.fillStyle = PDF_COL.text;
    ctx.font = 'bold 36px Segoe UI, Arial, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText('Proportion', px + 40, py + 30);

    const cx = px + pw / 2, cy = py + 460, R = 300;
    let a0 = -Math.PI / 2;
    for (const id of ids) {
        const frac = countsByClass[id] / total;
        const a1 = a0 + frac * Math.PI * 2;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, R, a0, a1);
        ctx.closePath();
        ctx.fillStyle = CLASS_COLORS[id] || '#888';
        ctx.fill();
        ctx.strokeStyle = '#FFFFFF';
        ctx.lineWidth = 4;
        ctx.stroke();
        a0 = a1;
    }
    // donut hole
    ctx.fillStyle = PDF_COL.panel;
    ctx.beginPath();
    ctx.arc(cx, cy, R * 0.45, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = PDF_COL.text;
    ctx.font = 'bold 40px Segoe UI, Arial, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(total.toLocaleString(), cx, cy - 12);
    ctx.font = '22px Segoe UI, Arial, sans-serif';
    ctx.fillStyle = PDF_COL.subtext;
    ctx.fillText('cells', cx, cy + 24);

    // legend
    let ly = py + 830;
    ctx.font = '24px Segoe UI, Arial, sans-serif';
    ctx.textBaseline = 'middle';
    for (let i = 0; i < ids.length; i++) {
        const id = ids[i];
        const yy2 = ly + i * 38;
        if (yy2 > py + ph - 30) break;
        ctx.fillStyle = CLASS_COLORS[id] || '#888';
        ctx.fillRect(px + 40, yy2 - 12, 26, 26);
        ctx.fillStyle = PDF_COL.text;
        ctx.textAlign = 'left';
        const pct = (countsByClass[id] / total * 100).toFixed(1);
        ctx.fillText(`${CLASS_NAMES[id] || id}`, px + 78, yy2);
        ctx.fillStyle = PDF_COL.subtext;
        ctx.textAlign = 'right';
        ctx.fillText(`${pct}%`, px + pw - 40, yy2);
    }

    return c;
}

function _pdfDrawTumorAnalysis(state) {
    const { countsByClass } = state;
    const c = _pdfNewCanvas();
    const ctx = c.getContext('2d');
    _pdfHeader(ctx, 'Tumor Analysis');

    const tumor = countsByClass[6] || 0;
    const benign = countsByClass[7] || 0;
    const total = tumor + benign;

    // Pie left
    const px = 100, py = 200, pw = 950, ph = 1170;
    _pdfPanel(ctx, px, py, pw, ph);
    ctx.fillStyle = PDF_COL.text;
    ctx.font = 'bold 36px Segoe UI, Arial, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText('Tumor vs Benign Epithelial', px + 40, py + 30);

    if (total === 0) {
        ctx.fillStyle = PDF_COL.subtext;
        ctx.font = '40px Segoe UI, Arial, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('No epithelial cells detected', px + pw / 2, py + ph / 2);
    } else {
        const cx = px + pw / 2, cy = py + 560, R = 360;
        const segs = [
            { name: 'Tumor Epithelial', val: tumor, color: PDF_COL.tumor },
            { name: 'Benign Epithelial', val: benign, color: PDF_COL.benign },
        ];
        let a0 = -Math.PI / 2;
        for (const s of segs) {
            if (s.val === 0) continue;
            const a1 = a0 + (s.val / total) * Math.PI * 2;
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.arc(cx, cy, R, a0, a1);
            ctx.closePath();
            ctx.fillStyle = s.color;
            ctx.fill();
            ctx.strokeStyle = '#FFFFFF';
            ctx.lineWidth = 6;
            ctx.stroke();
            a0 = a1;
        }
        // legend
        let ly = py + 1000;
        ctx.font = '28px Segoe UI, Arial, sans-serif';
        ctx.textBaseline = 'middle';
        for (let i = 0; i < segs.length; i++) {
            const s = segs[i];
            const lx = px + 80 + i * 420;
            ctx.fillStyle = s.color;
            ctx.fillRect(lx, ly - 16, 32, 32);
            ctx.fillStyle = PDF_COL.text;
            ctx.textAlign = 'left';
            ctx.fillText(`${s.name}: ${s.val.toLocaleString()}`, lx + 48, ly);
        }
    }

    // Gauge right
    const gx = 1100, gy = 200, gw = 900, gh = 1170;
    _pdfPanel(ctx, gx, gy, gw, gh);
    ctx.fillStyle = PDF_COL.text;
    ctx.font = 'bold 36px Segoe UI, Arial, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText('Tumor Proportion Score', gx + 40, gy + 30);

    const ratio = total > 0 ? (tumor / total) : 0;
    const pct = ratio * 100;

    // big number
    ctx.fillStyle = PDF_COL.tumor;
    ctx.font = 'bold 220px Segoe UI, Arial, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(total > 0 ? pct.toFixed(1) + '%' : 'N/A', gx + gw / 2, gy + 380);

    // gauge bar
    const barY = gy + 660, barH = 80;
    const barX = gx + 60, barW = gw - 120;
    _roundRect(ctx, barX, barY, barW, barH, 40);
    ctx.fillStyle = '#E5E7EB';
    ctx.fill();
    if (total > 0) {
        ctx.save();
        _roundRect(ctx, barX, barY, barW, barH, 40);
        ctx.clip();
        const grad = ctx.createLinearGradient(barX, 0, barX + barW, 0);
        grad.addColorStop(0, PDF_COL.benign);
        grad.addColorStop(0.5, '#FBBF24');
        grad.addColorStop(1, PDF_COL.tumor);
        ctx.fillStyle = grad;
        ctx.fillRect(barX, barY, barW * ratio, barH);
        ctx.restore();
        // marker line
        const mx = barX + barW * ratio;
        ctx.strokeStyle = PDF_COL.text;
        ctx.lineWidth = 4;
        ctx.beginPath();
        ctx.moveTo(mx, barY - 10);
        ctx.lineTo(mx, barY + barH + 10);
        ctx.stroke();
    }
    ctx.fillStyle = PDF_COL.subtext;
    ctx.font = '24px Segoe UI, Arial, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText('0%', barX, barY + barH + 20);
    ctx.textAlign = 'center';
    ctx.fillText('50%', barX + barW / 2, barY + barH + 20);
    ctx.textAlign = 'right';
    ctx.fillText('100%', barX + barW, barY + barH + 20);

    // counts
    ctx.textAlign = 'left';
    ctx.font = '28px Segoe UI, Arial, sans-serif';
    ctx.fillStyle = PDF_COL.text;
    ctx.fillText(`Tumor:  ${tumor.toLocaleString()}`, gx + 60, gy + 880);
    ctx.fillText(`Benign: ${benign.toLocaleString()}`, gx + 60, gy + 930);
    ctx.fillText(`Total:  ${total.toLocaleString()}`, gx + 60, gy + 980);

    return c;
}

function _pdfDrawSpatialHeatmap(state) {
    const { cells, countsByClass, thumbnailImg, slideDims } = state;
    const c = _pdfNewCanvas();
    const ctx = c.getContext('2d');
    _pdfHeader(ctx, 'Spatial Distribution');

    if (cells.length === 0) return c;

    // 셀 좌표는 WSI level-0 픽셀. 슬라이드 level-0 크기를 좌표계로 사용해
    // 썸네일/프리뷰 위에 정확히 매핑한다.
    let originX = 0, originY = 0, slideW, slideH;
    if (slideDims && slideDims[0] && slideDims[1]) {
        slideW = slideDims[0];
        slideH = slideDims[1];
    } else {
        // 폴백: 셀 bbox
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        for (const cell of cells) {
            if (cell.x < minX) minX = cell.x;
            if (cell.x > maxX) maxX = cell.x;
            if (cell.y < minY) minY = cell.y;
            if (cell.y > maxY) maxY = cell.y;
        }
        originX = minX; originY = minY;
        slideW = Math.max(maxX - minX, 1);
        slideH = Math.max(maxY - minY, 1);
    }

    // plot panel
    const px = 100, py = 200, pw = 1500, ph = 1170;
    _pdfPanel(ctx, px, py, pw, ph);

    const padding = 60;
    const innerW = pw - padding * 2;
    const innerH = ph - padding * 2;
    const scale = Math.min(innerW / slideW, innerH / slideH);
    const drawW = slideW * scale;
    const drawH = slideH * scale;
    const ox = px + (pw - drawW) / 2;
    const oy = py + (ph - drawH) / 2;

    // 썸네일을 배경으로 그리기 (있으면)
    if (thumbnailImg) {
        ctx.drawImage(thumbnailImg, ox, oy, drawW, drawH);
    } else {
        ctx.fillStyle = '#FAFAFA';
        ctx.fillRect(ox, oy, drawW, drawH);
    }
    ctx.strokeStyle = '#374151';
    ctx.lineWidth = 2;
    ctx.strokeRect(ox, oy, drawW, drawH);

    // 옅은 반투명 마스크로 셀 가시성 강화 (썸네일 위에 그릴 때)
    if (thumbnailImg) {
        ctx.fillStyle = 'rgba(255,255,255,0.20)';
        ctx.fillRect(ox, oy, drawW, drawH);
    }

    // 셀 오버레이 (서브샘플링) — 점 크기는 그리는 면적에 비례
    const MAX_PTS = 80000;
    const step = cells.length > MAX_PTS ? Math.ceil(cells.length / MAX_PTS) : 1;
    const dotR = Math.max(1.5, Math.min(drawW, drawH) / 600);
    ctx.globalAlpha = 0.85;
    for (let i = 0; i < cells.length; i += step) {
        const cell = cells[i];
        const sx = ox + ((cell.x - originX) / slideW) * drawW;
        const sy = oy + ((cell.y - originY) / slideH) * drawH;
        ctx.fillStyle = CLASS_COLORS[cell.class_id] || '#888';
        ctx.beginPath();
        ctx.arc(sx, sy, dotR, 0, Math.PI * 2);
        ctx.fill();
    }
    ctx.globalAlpha = 1;

    // legend right
    const lx = 1660, ly = 220, lw = 360, lh = 1150;
    _pdfPanel(ctx, lx, ly, lw, lh);
    ctx.fillStyle = PDF_COL.text;
    ctx.font = 'bold 32px Segoe UI, Arial, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText('Legend', lx + 24, ly + 24);

    let yy = ly + 90;
    ctx.font = '24px Segoe UI, Arial, sans-serif';
    ctx.textBaseline = 'middle';
    const ids = Object.keys(countsByClass).map(Number).sort((a, b) => countsByClass[b] - countsByClass[a]);
    for (const id of ids) {
        ctx.fillStyle = CLASS_COLORS[id] || '#888';
        ctx.fillRect(lx + 24, yy - 12, 26, 26);
        ctx.fillStyle = PDF_COL.text;
        ctx.textAlign = 'left';
        ctx.fillText(`${CLASS_NAMES[id] || id}`, lx + 60, yy);
        ctx.fillStyle = PDF_COL.subtext;
        ctx.textAlign = 'right';
        ctx.fillText(countsByClass[id].toLocaleString(), lx + lw - 24, yy);
        yy += 44;
    }
    ctx.fillStyle = PDF_COL.subtext;
    ctx.font = '20px Segoe UI, Arial, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(`Total: ${cells.length.toLocaleString()}`, lx + 24, yy + 20);
    if (step > 1) {
        ctx.fillText(`(showing 1/${step} for clarity)`, lx + 24, yy + 50);
    }

    return c;
}

function _pdfDrawConfidence(state) {
    const { confsByClass } = state;
    const c = _pdfNewCanvas();
    const ctx = c.getContext('2d');
    _pdfHeader(ctx, 'Confidence Distribution');

    const ids = Object.keys(confsByClass).map(Number).sort((a, b) => a - b);
    if (ids.length === 0) return c;

    const cols = Math.min(ids.length, 3);
    const rows = Math.ceil(ids.length / cols);
    const gridX = 100, gridY = 200;
    const gridW = PDF_W - 200, gridH = 1170;
    const cellW = gridW / cols;
    const cellH = gridH / rows;

    const BINS = 20;

    for (let i = 0; i < ids.length; i++) {
        const id = ids[i];
        const col = i % cols, row = Math.floor(i / cols);
        const x = gridX + col * cellW + 20;
        const y = gridY + row * cellH + 20;
        const w = cellW - 40;
        const h = cellH - 40;
        _pdfPanel(ctx, x, y, w, h);

        ctx.fillStyle = CLASS_COLORS[id] || '#888';
        ctx.fillRect(x + 24, y + 28, 28, 28);
        ctx.fillStyle = PDF_COL.text;
        ctx.font = 'bold 26px Segoe UI, Arial, sans-serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.fillText(`${CLASS_NAMES[id] || id}  (n=${confsByClass[id].length})`, x + 62, y + 28);

        const confs = confsByClass[id];
        const bins = new Array(BINS).fill(0);
        for (const v of confs) {
            const b = Math.min(BINS - 1, Math.max(0, Math.floor(v * BINS)));
            bins[b]++;
        }
        const maxBin = Math.max(...bins, 1);
        const chartX = x + 70, chartY = y + 90;
        const chartW = w - 100, chartH = h - 160;

        // axes
        ctx.strokeStyle = PDF_COL.subtext;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(chartX, chartY);
        ctx.lineTo(chartX, chartY + chartH);
        ctx.lineTo(chartX + chartW, chartY + chartH);
        ctx.stroke();

        const bw = chartW / BINS;
        ctx.fillStyle = CLASS_COLORS[id] || '#888';
        for (let b = 0; b < BINS; b++) {
            const bh = (bins[b] / maxBin) * chartH * 0.92;
            ctx.fillRect(chartX + b * bw + 1, chartY + chartH - bh, bw - 2, bh);
        }

        // x labels
        ctx.fillStyle = PDF_COL.subtext;
        ctx.font = '18px Segoe UI, Arial, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText('0.0', chartX, chartY + chartH + 8);
        ctx.fillText('0.5', chartX + chartW / 2, chartY + chartH + 8);
        ctx.fillText('1.0', chartX + chartW, chartY + chartH + 8);

        // mean line
        const mean = confs.reduce((s, v) => s + v, 0) / confs.length;
        const mx = chartX + mean * chartW;
        ctx.strokeStyle = PDF_COL.tumor;
        ctx.setLineDash([6, 4]);
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(mx, chartY);
        ctx.lineTo(mx, chartY + chartH);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = PDF_COL.tumor;
        ctx.font = 'bold 20px Segoe UI, Arial, sans-serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.fillText(`μ=${mean.toFixed(2)}`, mx + 6, chartY + 4);
    }

    return c;
}
