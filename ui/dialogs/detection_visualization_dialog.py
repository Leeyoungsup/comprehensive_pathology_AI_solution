"""
AI Detection Result Visualization Dialog
Displays class distribution, tumor ratio, spatial heatmap, and confidence distribution in tabs
"""

import numpy as np
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                              QWidget, QPushButton, QLabel, QSizePolicy)
from PyQt5.QtCore import Qt

import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.font_manager as fm

# Font setup (Windows: Malgun Gothic, fallback: system font)
def _setup_korean_font():
    korean_fonts = ['Malgun Gothic', 'NanumGothic', 'NanumBarunGothic', 'AppleGothic', 'UnDotum']
    available = {f.name for f in fm.fontManager.ttflist}
    for font in korean_fonts:
        if font in available:
            matplotlib.rcParams['font.family'] = font
            break
    matplotlib.rcParams['axes.unicode_minus'] = False

_setup_korean_font()

# Class info (same as detection.py)
CLASS_NAMES = {
    0: "Neutrophil",
    1: "Epithelial",
    2: "Lymphocyte",
    3: "Plasma",
    4: "Eosinophil",
    5: "Connective tissue",
    6: "Tumor Epithelial",
    7: "Benign Epithelial",
}

CLASS_COLORS_HEX = {
    0: "#FF4500",
    1: "#00FF00",
    2: "#0000FF",
    3: "#FFFF00",
    4: "#8A2BE2",
    5: "#808080",
    6: "#FF0000",
    7: "#00FF00",
}

BG      = 'white'
PANEL   = '#f7f7f7'
SPINE   = '#cccccc'
TEXT    = '#222222'
SUBTEXT = '#666666'

A4_LANDSCAPE = (11.69, 8.27)  # inches


class DetectionVisualizationDialog(QDialog):
    """AI detection result visualization dialog"""

    def __init__(self, cells, slide_dimensions=None, thumbnail=None, roi_bounds=None,
                 seg_prob_map=None, seg_class_names=None, roi_polygons=None,
                 slide_path=None, parent=None, plot_arrays=None):
        """
        Args:
            cells: Detected cell list [{'x', 'y', 'cls_id', 'confidence'}, ...]
            slide_dimensions: (width, height) WSI original size
            thumbnail: numpy RGB array (slide thumbnail, cropped if ROI)
            roi_bounds: (x0, y0, x1, y1) ROI area (None for entire slide)
            seg_prob_map: numpy (num_classes, H, W) class probability map (None uses cell density)
            seg_class_names: Class name list ['Background','Stroma','Non_Tumor','Tumor']
            slide_path: WSI file path (used for PDF default filename)
            parent: Parent widget
            plot_arrays: Pre-computed numpy array dict from DetectionWorker (computed from cells if None)
        """
        super().__init__(parent)
        self.cells = cells
        self.slide_dimensions = slide_dimensions
        self.thumbnail = thumbnail
        self.roi_bounds = roi_bounds
        self.seg_prob_map = None  # Large arrays not stored in instance; use _resized_prob_map
        self._has_prob_map = seg_prob_map is not None
        self.seg_class_names = seg_class_names or ['Background', 'Stroma', 'Non_Tumor', 'Tumor']
        self.roi_polygons = roi_polygons or []
        self.slide_path = slide_path
        self.setWindowTitle("AI Detection Result Visualization")
        self.setMinimumSize(950, 680)
        self.setWindowModality(Qt.NonModal)
        self.setStyleSheet("background-color: white; color: #222222;")

        # Initialize plot arrays: use pre-computed from worker if available, otherwise compute here
        if plot_arrays is not None and 'counts_by_id' in plot_arrays:
            self._pa = plot_arrays
        else:
            self._pa = self._compute_plot_arrays(cells)
            # thumbnail 등 기존 캐시 보존
            if plot_arrays is not None:
                for k, v in plot_arrays.items():
                    if k not in self._pa:
                        self._pa[k] = v

        # Pre-resize seg_prob_map to thumbnail size and release original large array
        # (saves hundreds of MB: only thumbnail-sized reduced version is kept in instance)
        self._resized_prob_map = None
        if seg_prob_map is not None and self.thumbnail is not None:
            import cv2
            th, tw = self.thumbnail.shape[:2]
            self._resized_prob_map = [
                cv2.resize(seg_prob_map[i], (tw, th), interpolation=cv2.INTER_LINEAR)
                for i in range(seg_prob_map.shape[0])
            ]
            # seg_prob_map exists only as local parameter -> GC releases after this block

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #cccccc; background: white; }
            QTabBar::tab { background: #f0f0f0; color: #444444; padding: 6px 16px;
                           border: 1px solid #cccccc; border-bottom: none; margin-right: 2px; }
            QTabBar::tab:selected { background: white; color: #111111; font-weight: bold; }
            QTabBar::tab:hover { background: #e0e8ff; }
        """)
        layout.addWidget(self.tab_widget)

        self._class_dist_tab = self._create_class_distribution_tab()
        self._tumor_tab = self._create_tumor_analysis_tab()
        self.tab_widget.addTab(self._class_dist_tab, "Class Distribution")
        self.tab_widget.addTab(self._tumor_tab, "Tumor Analysis")
        if self._has_prob_map:
            self.tab_widget.addTab(self._create_spatial_heatmap_tab(), "Spatial Heatmap")
        self.tab_widget.addTab(self._create_confidence_tab(), "Confidence Distribution")

        btn_layout = QHBoxLayout()

        pdf_btn = QPushButton("Export PDF")
        pdf_btn.setFixedHeight(32)
        pdf_btn.setStyleSheet(
            "background:#1a56a0; color:white; border:none; border-radius:4px;"
            "padding: 0 18px; font-weight:bold;"
        )
        pdf_btn.clicked.connect(self._export_pdf)
        btn_layout.addWidget(pdf_btn)
        btn_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(32)
        close_btn.setStyleSheet(
            "background:#e8e8e8; color:#222; border:1px solid #bbb; border-radius:4px;"
            "padding: 0 16px;"
        )
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _compute_plot_arrays(self, cells):
        """plot_arrays fallback: compute directly from cells list (when no worker result)"""
        n = len(cells)
        if n == 0:
            empty = np.empty(0, dtype=np.float32)
            return {'all_x': empty, 'all_y': empty,
                    'xs_by_class': {}, 'ys_by_class': {}, 'confs_by_class': {},
                    'counts_by_id': {}}
        all_x    = np.fromiter((c['x']                   for c in cells), dtype=np.float32, count=n)
        all_y    = np.fromiter((c['y']                   for c in cells), dtype=np.float32, count=n)
        all_cls  = np.fromiter((c.get('cls_id', 0)       for c in cells), dtype=np.int32,   count=n)
        all_conf = np.fromiter((c.get('confidence', 0.0) for c in cells), dtype=np.float32, count=n)
        xs_by_class = {}; ys_by_class = {}; confs_by_class = {}; counts_by_id = {}
        for cls_id in np.unique(all_cls).tolist():
            mask = all_cls == cls_id
            xs_by_class[cls_id]    = all_x[mask]
            ys_by_class[cls_id]    = all_y[mask]
            confs_by_class[cls_id] = all_conf[mask]
            counts_by_id[cls_id]   = int(mask.sum())
        return {'all_x': all_x, 'all_y': all_y,
                'xs_by_class': xs_by_class, 'ys_by_class': ys_by_class,
                'confs_by_class': confs_by_class, 'counts_by_id': counts_by_id}

    def update_cells(self, cells):
        """셀 편집 후 Class Distribution / Tumor Analysis 탭 내용만 갱신 (다른 탭 영향 없음)"""
        self.cells = cells
        self._pa = self._compute_plot_arrays(cells)

        # 기존 탭 위젯 내부 레이아웃을 비우고 새로 채움
        for tab_widget, creator in [
            (self._class_dist_tab, self._create_class_distribution_tab),
            (self._tumor_tab, self._create_tumor_analysis_tab),
        ]:
            # 기존 레이아웃의 위젯 모두 제거
            layout = tab_widget.layout()
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()

            # 새 탭 생성 후 위젯만 옮겨옴
            new_tab = creator()
            new_layout = new_tab.layout()
            while new_layout.count():
                item = new_layout.takeAt(0)
                w = item.widget()
                if w:
                    layout.addWidget(w)

    def _get_class_counts(self):
        """Return cell count per class (pre-computed, O(1))"""
        counts = {cls_id: 0 for cls_id in CLASS_NAMES}
        for cls_id, cnt in self._pa['counts_by_id'].items():
            if cls_id in counts:
                counts[cls_id] = cnt
        return counts

    def _styled_ax(self, ax):
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=TEXT, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(SPINE)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

    def _create_class_distribution_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        counts = self._get_class_counts()
        active = {k: v for k, v in counts.items() if v > 0}

        fig = Figure(facecolor=BG, tight_layout=True)
        canvas = FigureCanvas(fig)
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        if not active:
            ax = fig.add_subplot(111)
            ax.set_facecolor(PANEL)
            ax.text(0.5, 0.5, 'No detection data', ha='center', va='center', color=TEXT, fontsize=14)
            layout.addWidget(canvas)
            return widget

        names = [CLASS_NAMES[k] for k in active]
        values = list(active.values())
        colors = [CLASS_COLORS_HEX[k] for k in active]
        max_v = max(values)

        ax1 = fig.add_subplot(1, 2, 1)
        self._styled_ax(ax1)
        bars = ax1.barh(names, values, color=colors, height=0.6, edgecolor='#cccccc', linewidth=0.5)
        ax1.set_xlabel('Cell Count', color=SUBTEXT, fontsize=9)
        ax1.set_title('Cell Count by Class', color=TEXT, fontsize=11, pad=8)
        ax1.spines['left'].set_visible(True)
        ax1.spines['bottom'].set_visible(True)
        for bar, val in zip(bars, values):
            ax1.text(val + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                     f'{val:,}', va='center', color=TEXT, fontsize=8)

        ax2 = fig.add_subplot(1, 2, 2)
        ax2.set_facecolor(BG)
        wedges, _, autotexts = ax2.pie(
            values, labels=None, colors=colors,
            autopct=lambda p: f'{p:.1f}%' if p > 3 else '',
            pctdistance=0.72, startangle=90,
            wedgeprops={'linewidth': 0.8, 'edgecolor': 'white'}
        )
        for t in autotexts:
            t.set_color('#111')
            t.set_fontsize(8)
            t.set_fontweight('bold')
        ax2.set_title(f'Proportion  (Total {len(self.cells):,})', color=TEXT, fontsize=11, pad=8)
        ax2.legend(wedges, [f'{n}  ({v:,})' for n, v in zip(names, values)],
                   loc='lower center', bbox_to_anchor=(0.5, -0.22),
                   ncol=2, fontsize=8, labelcolor=TEXT,
                   facecolor='white', edgecolor=SPINE)

        layout.addWidget(canvas)
        return widget

    def _create_tumor_analysis_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        counts = self._get_class_counts()
        tumor = counts.get(6, 0)
        benign = counts.get(7, 0)
        total_epi = tumor + benign
        tumor_ratio = (tumor / total_epi * 100) if total_epi > 0 else 0

        fig = Figure(facecolor=BG, tight_layout=True)
        canvas = FigureCanvas(fig)
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        ax1 = fig.add_subplot(1, 2, 1)
        ax1.set_facecolor(BG)

        if total_epi > 0:
            pie_data = [tumor, benign]
            pie_colors = ['#E84040', '#2196F3']
            pie_labels = [f'Tumor Epithelial\n({tumor:,})', f'Benign Epithelial\n({benign:,})']
            _, _, autotexts = ax1.pie(
                pie_data, labels=pie_labels, colors=pie_colors,
                autopct='%1.1f%%', startangle=90,
                textprops={'color': TEXT, 'fontsize': 10},
                wedgeprops={'linewidth': 1.2, 'edgecolor': 'white'}
            )
            for t in autotexts:
                t.set_fontsize(12)
                t.set_fontweight('bold')
                t.set_color('white')
        else:
            ax1.text(0.5, 0.5, 'No Epithelial cells', ha='center', va='center',
                     color=SUBTEXT, fontsize=13, transform=ax1.transAxes)
        ax1.set_title('Tumor vs Benign Epithelial', color=TEXT, fontsize=11, pad=8)

        # Gauge bar
        ax2 = fig.add_subplot(1, 2, 2)
        self._styled_ax(ax2)
        ax2.set_xlim(0, 100)
        ax2.set_ylim(0, 1)
        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)
        ax2.spines['left'].set_visible(False)

        ax2.barh(0.5, 100, height=0.25, color='#e0e0e0', left=0)
        bar_color = '#E84040' if tumor_ratio >= 50 else '#FF8C00' if tumor_ratio >= 20 else '#FFB347'
        ax2.barh(0.5, tumor_ratio, height=0.25, color=bar_color, left=0)

        ax2.text(50, 0.82, 'Tumor Ratio', ha='center', color=SUBTEXT, fontsize=11)
        ax2.text(50, 0.22, f'{tumor_ratio:.1f}%', ha='center', color=bar_color,
                 fontsize=28, fontweight='bold')
        ax2.set_xticks([0, 25, 50, 75, 100])
        ax2.set_xticklabels(['0%', '25%', '50%', '75%', '100%'], color=SUBTEXT)
        ax2.set_yticks([])
        ax2.set_title(f'Tumor / (Tumor + Benign)  [{total_epi:,} total]',
                      color=TEXT, fontsize=10, pad=8)

        layout.addWidget(canvas)

        summary = QLabel(
            f"  Tumor Epithelial: {tumor:,}   |   "
            f"Benign Epithelial: {benign:,}   |   "
            f"Tumor Ratio: {tumor_ratio:.1f}%"
        )
        summary.setStyleSheet(
            f"color: {TEXT}; background: #f0f0f0; padding: 6px 10px;"
            "border-radius: 4px; border: 1px solid #ddd;"
        )
        layout.addWidget(summary)
        return widget

    def _create_spatial_heatmap_tab(self):
        from PyQt5.QtWidgets import QScrollArea
        import matplotlib.colors as mcolors
        import cv2

        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(4, 4, 4, 4)

        if not self.slide_dimensions:
            label = QLabel('No slide dimension info')
            label.setStyleSheet(f'color: {SUBTEXT}; font-size: 13px;')
            outer_layout.addWidget(label)
            return outer

        use_prob = self._resized_prob_map is not None

        panel_h, panel_w = 3.2, 5.0
        cols = 1

        if use_prob:
            # Thumbnail size
            if self.thumbnail is not None:
                th, tw = self.thumbnail.shape[:2]
            else:
                tw = 300
                th = int(300 * self.slide_dimensions[1] / self.slide_dimensions[0])

            # Class list excluding Background(0)
            active_panels = [
                (cls_id, cls_name)
                for cls_id, cls_name in enumerate(self.seg_class_names)
                if cls_id != 0
            ]

            rows = len(active_panels)
            fig = Figure(figsize=(panel_w * cols, panel_h * rows), facecolor=BG)
            fig.subplots_adjust(hspace=0.35, wspace=0.0, left=0.02, right=0.98,
                                top=0.97, bottom=0.01)
            canvas = FigureCanvas(fig)
            canvas.setMinimumHeight(int(panel_h * rows * 96))
            canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

            for i, (cls_id, cls_name) in enumerate(active_panels):
                ax = fig.add_subplot(rows, cols, i + 1)
                ax.set_facecolor('#e8e8e8')
                ax.set_title(cls_name, color=TEXT, fontsize=9, pad=5, fontweight='bold')
                ax.set_xticks([])
                ax.set_yticks([])
                for sp in ax.spines.values():
                    sp.set_color(SPINE)

                if self.thumbnail is not None:
                    ax.imshow(self.thumbnail, aspect='auto', origin='upper', zorder=0)

                if cls_id < len(self._resized_prob_map):
                    prob_resized = self._resized_prob_map[cls_id]
                    ax.imshow(prob_resized, aspect='auto', origin='upper',
                              cmap='jet', alpha=0.75, zorder=1,
                              vmin=0, vmax=1, interpolation='bilinear')
                    max_val = float(prob_resized.max())
                    mean_val = float(prob_resized[prob_resized > 0.05].mean()) if np.any(prob_resized > 0.05) else 0.0
                    ax.text(0.02, 0.03,
                            f'max={max_val:.2f}  avg={mean_val:.2f}',
                            transform=ax.transAxes,
                            color='white', fontsize=8, va='bottom', fontweight='bold',
                            bbox=dict(boxstyle='round,pad=0.3', facecolor='#333', alpha=0.65))

        else:
            # No segmentation -> cell density heatmap (Other type or not run)
            if not self.cells:
                label = QLabel('No cell data')
                label.setStyleSheet(f'color: {SUBTEXT}; font-size: 13px;')
                outer_layout.addWidget(label)
                return outer

            if self.roi_bounds:
                x0, y0, x1, y1 = self.roi_bounds
                range_x = [x0, x1]
                range_y = [y0, y1]
                region_w, region_h = x1 - x0, y1 - y0
            else:
                wf, hf = self.slide_dimensions
                range_x, range_y = [0, wf], [0, hf]
                region_w, region_h = wf, hf

            bins_x = 100
            bins_y = max(10, int(bins_x * region_h / region_w))
            thumb_extent = [range_x[0], range_x[1], range_y[1], range_y[0]]

            counts = self._get_class_counts()
            active_classes = [k for k, v in counts.items() if v > 0]
            panels = [('All Cells', None)] + [(CLASS_NAMES[k], k) for k in active_classes]
            rows = len(panels)

            fig = Figure(figsize=(panel_w * cols, panel_h * rows), facecolor=BG)
            fig.subplots_adjust(hspace=0.35, wspace=0.0, left=0.03, right=0.97,
                                top=0.97, bottom=0.01)
            canvas = FigureCanvas(fig)
            canvas.setMinimumHeight(int(panel_h * rows * 96))
            canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

            def _draw_density_panel(ax, title, cls_id):
                ax.set_facecolor('#e8e8e8')
                ax.set_title(title, color=TEXT, fontsize=9, pad=5, fontweight='bold')
                ax.set_xticks([])
                ax.set_yticks([])
                ax.set_xlim(range_x)
                ax.set_ylim([range_y[1], range_y[0]])
                for sp in ax.spines.values():
                    sp.set_color(SPINE)

                if self.thumbnail is not None:
                    ax.imshow(self.thumbnail, aspect='auto',
                              extent=thumb_extent, origin='upper', zorder=0)

                if cls_id is None:
                    xs   = self._pa['all_x']
                    ys   = self._pa['all_y']
                    cmap = 'jet'
                else:
                    xs = self._pa['xs_by_class'].get(cls_id, np.empty(0, dtype=np.float32))
                    ys = self._pa['ys_by_class'].get(cls_id, np.empty(0, dtype=np.float32))
                    rgb = mcolors.to_rgb(CLASS_COLORS_HEX.get(cls_id, '#333333'))
                    cmap = mcolors.LinearSegmentedColormap.from_list(
                        f'cls_{cls_id}', [(0, 0, 0, 0), (*rgb, 1.0)])

                if len(xs) == 0:
                    ax.text(0.5, 0.5, 'No cells', ha='center', va='center',
                            color=SUBTEXT, fontsize=9, transform=ax.transAxes)
                    return

                h2d, _, _ = np.histogram2d(xs, ys, bins=(bins_x, bins_y),
                                            range=[range_x, range_y])
                from scipy.ndimage import gaussian_filter
                h2d_smooth = gaussian_filter(h2d.T, sigma=1.5)
                ax.imshow(h2d_smooth, origin='upper', aspect='auto',
                          extent=[range_x[0], range_x[1], range_y[1], range_y[0]],
                          cmap=cmap, alpha=0.75, zorder=1, interpolation='bilinear',
                          vmin=0, vmax=max(h2d_smooth.max(), 1))
                ax.text(0.02, 0.03, f'n={len(xs):,}', transform=ax.transAxes,
                        color='white', fontsize=8, va='bottom',
                        bbox=dict(boxstyle='round,pad=0.3', facecolor='#333', alpha=0.65))

            for i, (title, cls_id) in enumerate(panels):
                ax = fig.add_subplot(rows, 1, i + 1)
                _draw_density_panel(ax, title, cls_id)

        scroll = QScrollArea()
        scroll.setWidget(canvas)
        scroll.setWidgetResizable(False)
        scroll.setStyleSheet('background: white; border: none;')
        outer_layout.addWidget(scroll)

        mode_label = QLabel(
            "  Mode: Segmentation probability heatmap" if use_prob else
            "  Mode: Cell density heatmap (Segmentation not run)"
        )
        mode_label.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px; padding: 4px;")
        outer_layout.addWidget(mode_label)
        return outer

    def _create_confidence_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        counts = self._get_class_counts()
        active_classes = [k for k, v in counts.items() if v > 0]

        if not active_classes:
            label = QLabel("No data")
            label.setStyleSheet(f"color: {TEXT};")
            layout.addWidget(label)
            return widget

        n = len(active_classes)
        cols = min(3, n)
        rows = (n + cols - 1) // cols

        fig = Figure(facecolor=BG)
        fig.subplots_adjust(hspace=0.55, wspace=0.4, left=0.08, right=0.97,
                            top=0.93, bottom=0.08)
        canvas = FigureCanvas(fig)
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        for i, cls_id in enumerate(active_classes):
            ax = fig.add_subplot(rows, cols, i + 1)
            self._styled_ax(ax)
            ax.spines['left'].set_visible(True)
            ax.spines['bottom'].set_visible(True)

            confs = self._pa['confs_by_class'].get(cls_id, np.empty(0, dtype=np.float32))
            color = CLASS_COLORS_HEX.get(cls_id, '#4488CC')

            ax.hist(confs, bins=20, color=color, alpha=0.80, edgecolor='white',
                    linewidth=0.4, range=(0, 1))
            ax.set_title(f'{CLASS_NAMES[cls_id]}\n(n={len(confs):,})',
                         color=TEXT, fontsize=8, pad=4)
            ax.set_xlabel('Confidence', color=SUBTEXT, fontsize=7)
            ax.set_ylabel('Count', color=SUBTEXT, fontsize=7)

            mean_conf = np.mean(confs)
            ax.axvline(mean_conf, color='#555', linestyle='--', linewidth=1, alpha=0.9)
            ylim = ax.get_ylim()
            ax.text(mean_conf + 0.02, ylim[1] * 0.88,
                    f'avg {mean_conf:.2f}', color=TEXT, fontsize=7)

        layout.addWidget(canvas)
        return widget


    # ──────────────────────────────────────────────
    # PDF Export
    # ──────────────────────────────────────────────

    def _export_pdf(self):
        from PyQt5.QtWidgets import QFileDialog, QMessageBox, QProgressDialog
        from PyQt5.QtCore import Qt as QtCore_Qt
        import gc

        import os
        if self.slide_path:
            base = os.path.splitext(os.path.basename(self.slide_path))[0]
            default_name = f"{base}_ai_report.pdf"
        else:
            default_name = "ai_report.pdf"

        path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF", default_name, "PDF Files (*.pdf)")
        if not path:
            return
        if not path.lower().endswith('.pdf'):
            path += '.pdf'

        prog = QProgressDialog("Generating PDF...", None, 0, 0, self)
        prog.setWindowModality(QtCore_Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.show()

        try:
            from matplotlib.backends.backend_pdf import PdfPages
            with PdfPages(path) as pdf:
                for make_fn in [
                    self._make_pdf_cover,
                    self._make_pdf_class_distribution,
                    self._make_pdf_tumor_analysis,
                ]:
                    fig = make_fn()
                    pdf.savefig(fig, bbox_inches='tight')
                    fig.clear(); del fig; gc.collect()

                if self._has_prob_map:
                    for fig in self._make_pdf_spatial_heatmap():
                        pdf.savefig(fig, bbox_inches='tight')
                        fig.clear(); del fig; gc.collect()

                fig = self._make_pdf_confidence()
                pdf.savefig(fig, bbox_inches='tight')
                fig.clear(); del fig; gc.collect()

            prog.close()
            QMessageBox.information(self, "Complete", f"PDF saved successfully\n{path}")
        except Exception as e:
            prog.close()
            import traceback
            QMessageBox.warning(self, "Error",
                                f"PDF generation failed:\n{str(e)}\n\n{traceback.format_exc()[:600]}")

    # -- Cover Page ──────────────────────────────
    def _make_pdf_cover(self):
        import datetime
        from matplotlib.figure import Figure as MplFig

        fig = MplFig(figsize=A4_LANDSCAPE, facecolor='white')

        # Header band
        hax = fig.add_axes([0, 0.91, 1, 0.09])
        hax.set_facecolor('#1a56a0')
        hax.set_xticks([]); hax.set_yticks([])
        for sp in hax.spines.values(): sp.set_visible(False)
        hax.text(0.02, 0.5, 'AI Detection Result Report',
                 transform=hax.transAxes, color='white',
                 fontsize=18, fontweight='bold', va='center')
        hax.text(0.98, 0.5, datetime.datetime.now().strftime('%Y-%m-%d'),
                 transform=hax.transAxes, color='white',
                 fontsize=10, va='center', ha='right')

        # Thumbnail + polygon (left 60%)
        img_ax = fig.add_axes([0.02, 0.10, 0.57, 0.78])
        img_ax.set_xticks([]); img_ax.set_yticks([])
        for sp in img_ax.spines.values(): sp.set_color(SPINE)

        if self.thumbnail is not None:
            th, tw = self.thumbnail.shape[:2]
            img_ax.imshow(self.thumbnail, origin='upper', aspect='equal')

            # Polygon overlay
            if self.roi_polygons and self.roi_bounds:
                rx0, ry0, rx1, ry1 = self.roi_bounds
                rw, rh = rx1 - rx0, ry1 - ry0
                for poly in self.roi_polygons:
                    pts = np.array(poly)
                    if pts.ndim == 2 and pts.shape[1] >= 2:
                        px = (pts[:, 0] - rx0) * tw / rw
                        py = (pts[:, 1] - ry0) * th / rh
                        img_ax.plot(np.append(px, px[0]), np.append(py, py[0]),
                                    color='#2196F3', linewidth=2.5, alpha=0.9, zorder=2)
                        img_ax.fill(px, py, alpha=0.10, color='#2196F3', zorder=1)
        else:
            img_ax.set_facecolor('#f0f0f0')
            img_ax.text(0.5, 0.5, 'No thumbnail', ha='center', va='center',
                        color=SUBTEXT, fontsize=12, transform=img_ax.transAxes)

        img_ax.set_title('Tissue Image' + (' (ROI)' if self.roi_bounds else ''),
                         color=TEXT, fontsize=11, pad=6)

        # Statistics panel (right 38%)
        counts = self._get_class_counts()
        tumor = counts.get(6, 0)
        benign = counts.get(7, 0)
        total_epi = tumor + benign
        tumor_ratio = (tumor / total_epi * 100) if total_epi > 0 else 0
        n_total = len(self.cells)

        stat_ax = fig.add_axes([0.62, 0.10, 0.36, 0.78])
        stat_ax.set_facecolor('#f8f8f8')
        stat_ax.set_xticks([]); stat_ax.set_yticks([])
        for sp in stat_ax.spines.values(): sp.set_color(SPINE)
        stat_ax.set_title('Detection Summary', color=TEXT, fontsize=11, pad=8)

        rows = [('Total Detected Cells', f'{n_total:,}', TEXT)]
        for cls_id, name in CLASS_NAMES.items():
            cnt = counts.get(cls_id, 0)
            if cnt > 0:
                rows.append((f'  {name}', f'{cnt:,}', CLASS_COLORS_HEX.get(cls_id, TEXT)))
        rows.append(None)  # divider
        tc = '#E84040' if tumor_ratio >= 50 else ('#FF8C00' if tumor_ratio >= 20 else TEXT)
        rows.append(('Tumor Ratio', f'{tumor_ratio:.1f}%', tc))

        y = 0.90; dy = min(0.09, 0.85 / max(len(rows), 1))
        for row in rows:
            if row is None:
                stat_ax.axhline(y=y + dy * 0.4, xmin=0.04, xmax=0.96,
                                color=SPINE, linewidth=0.8)
                y -= dy * 0.5; continue
            label, value, color = row
            stat_ax.text(0.05, y, label, transform=stat_ax.transAxes,
                         fontsize=9, color=SUBTEXT, va='top')
            stat_ax.text(0.95, y, value, transform=stat_ax.transAxes,
                         fontsize=10, color=color, va='top', ha='right', fontweight='bold')
            y -= dy

        # Footer
        fig.text(0.5, 0.01,
                 f'Generated: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}  |  '
                 'MeDICus Studio',
                 ha='center', va='bottom', fontsize=8, color=SUBTEXT)
        return fig

    # -- Class Distribution ──────────────────────────────
    def _make_pdf_class_distribution(self):
        from matplotlib.figure import Figure as MplFig

        counts = self._get_class_counts()
        active = {k: v for k, v in counts.items() if v > 0}
        fig = MplFig(figsize=A4_LANDSCAPE, facecolor='white')
        fig.suptitle('Cell Distribution by Class', fontsize=16, fontweight='bold', color=TEXT, y=0.97)

        if not active:
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, 'No detection data', ha='center', va='center',
                    color=TEXT, fontsize=14)
            return fig

        names = [CLASS_NAMES[k] for k in active]
        values = list(active.values())
        colors = [CLASS_COLORS_HEX[k] for k in active]
        max_v = max(values)

        fig.subplots_adjust(left=0.10, right=0.95, top=0.88, bottom=0.12, wspace=0.35)

        ax1 = fig.add_subplot(1, 2, 1)
        ax1.set_facecolor(PANEL)
        ax1.tick_params(colors=TEXT, labelsize=9)
        for sp in ax1.spines.values(): sp.set_color(SPINE)
        ax1.spines['top'].set_visible(False); ax1.spines['right'].set_visible(False)
        bars = ax1.barh(names, values, color=colors, height=0.6,
                        edgecolor='white', linewidth=0.5)
        ax1.set_xlabel('Cell Count', color=SUBTEXT, fontsize=10)
        ax1.set_title('Cell Count by Class', color=TEXT, fontsize=13, pad=8)
        for bar, val in zip(bars, values):
            ax1.text(val + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                     f'{val:,}', va='center', color=TEXT, fontsize=9)

        ax2 = fig.add_subplot(1, 2, 2)
        ax2.set_facecolor('white')
        wedges, _, autotexts = ax2.pie(
            values, labels=None, colors=colors,
            autopct=lambda p: f'{p:.1f}%' if p > 3 else '',
            pctdistance=0.72, startangle=90,
            wedgeprops={'linewidth': 0.8, 'edgecolor': 'white'}
        )
        for t in autotexts:
            t.set_color('#111'); t.set_fontsize(9); t.set_fontweight('bold')
        ax2.set_title(f'Proportion  (Total {len(self.cells):,})', color=TEXT, fontsize=13, pad=8)
        ax2.legend(wedges, [f'{n}  ({v:,})' for n, v in zip(names, values)],
                   loc='lower center', bbox_to_anchor=(0.5, -0.16),
                   ncol=2, fontsize=9, labelcolor=TEXT,
                   facecolor='white', edgecolor=SPINE)
        return fig

    # -- Tumor Analysis ───────────────────────────────
    def _make_pdf_tumor_analysis(self):
        from matplotlib.figure import Figure as MplFig

        counts = self._get_class_counts()
        tumor = counts.get(6, 0); benign = counts.get(7, 0)
        total_epi = tumor + benign
        tumor_ratio = (tumor / total_epi * 100) if total_epi > 0 else 0

        fig = MplFig(figsize=A4_LANDSCAPE, facecolor='white')
        fig.suptitle('Tumor Analysis', fontsize=16, fontweight='bold', color=TEXT, y=0.97)
        fig.subplots_adjust(left=0.08, right=0.95, top=0.88, bottom=0.10, wspace=0.35)

        ax1 = fig.add_subplot(1, 2, 1)
        ax1.set_facecolor('white')
        if total_epi > 0:
            _, _, autotexts = ax1.pie(
                [tumor, benign],
                labels=[f'Tumor Epithelial\n({tumor:,})', f'Benign Epithelial\n({benign:,})'],
                colors=['#E84040', '#2196F3'],
                autopct='%1.1f%%', startangle=90,
                textprops={'color': TEXT, 'fontsize': 11},
                wedgeprops={'linewidth': 1.2, 'edgecolor': 'white'}
            )
            for t in autotexts:
                t.set_fontsize(13); t.set_fontweight('bold'); t.set_color('white')
        else:
            ax1.text(0.5, 0.5, 'No Epithelial cells', ha='center', va='center',
                     color=SUBTEXT, fontsize=13, transform=ax1.transAxes)
        ax1.set_title('Tumor vs Benign Epithelial', color=TEXT, fontsize=13, pad=8)

        ax2 = fig.add_subplot(1, 2, 2)
        ax2.set_facecolor(PANEL)
        for sp in ax2.spines.values(): sp.set_color(SPINE)
        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)
        ax2.spines['left'].set_visible(False)
        ax2.set_xlim(0, 100); ax2.set_ylim(0, 1)
        ax2.barh(0.5, 100, height=0.25, color='#e0e0e0', left=0)
        bar_color = '#E84040' if tumor_ratio >= 50 else ('#FF8C00' if tumor_ratio >= 20 else '#FFB347')
        ax2.barh(0.5, tumor_ratio, height=0.25, color=bar_color, left=0)
        ax2.text(50, 0.82, 'Tumor Ratio', ha='center', color=SUBTEXT, fontsize=12)
        ax2.text(50, 0.22, f'{tumor_ratio:.1f}%', ha='center', color=bar_color,
                 fontsize=34, fontweight='bold')
        ax2.set_xticks([0, 25, 50, 75, 100])
        ax2.set_xticklabels(['0%', '25%', '50%', '75%', '100%'], color=SUBTEXT, fontsize=9)
        ax2.set_yticks([])
        ax2.set_title(f'Tumor / (Tumor + Benign)  [{total_epi:,} total]',
                      color=TEXT, fontsize=11, pad=8)
        return fig

    # -- Spatial Heatmap ───────────────────────────────
    def _make_pdf_spatial_heatmap(self):
        """Return a list of Figures, one per heatmap class."""
        import cv2
        from matplotlib.figure import Figure as MplFig

        if self._resized_prob_map is None or self.thumbnail is None:
            fig = MplFig(figsize=A4_LANDSCAPE, facecolor='white')
            fig.text(0.5, 0.5, 'No spatial heatmap data', ha='center', va='center',
                     color=SUBTEXT, fontsize=14)
            return [fig]

        active_panels = [(cid, cn) for cid, cn in enumerate(self.seg_class_names) if cid != 0]
        figs = []
        total = len(active_panels)
        for i, (cls_id, cls_name) in enumerate(active_panels):
            fig = MplFig(figsize=A4_LANDSCAPE, facecolor='white')
            fig.suptitle(f'Spatial Probability Heatmap (Segmentation)  -  {cls_name}  [{i+1}/{total}]',
                         fontsize=14, fontweight='bold', color=TEXT, y=0.97)
            fig.subplots_adjust(left=0.04, right=0.96, top=0.91, bottom=0.04)

            ax = fig.add_subplot(1, 1, 1)
            ax.set_facecolor('#e8e8e8')
            ax.set_title(cls_name, color=TEXT, fontsize=13, pad=6, fontweight='bold')
            ax.set_xticks([]); ax.set_yticks([])
            for sp in ax.spines.values(): sp.set_color(SPINE)
            ax.imshow(self.thumbnail, aspect='auto', origin='upper', zorder=0)
            if cls_id < len(self._resized_prob_map):
                prob_r = self._resized_prob_map[cls_id]
                ax.imshow(prob_r, aspect='auto', origin='upper',
                          cmap='jet', alpha=0.75, zorder=1, vmin=0, vmax=1)
                max_v = float(prob_r.max())
                mean_v = float(prob_r[prob_r > 0.05].mean()) if np.any(prob_r > 0.05) else 0.0
                ax.text(0.02, 0.03, f'max={max_v:.2f}  avg={mean_v:.2f}',
                        transform=ax.transAxes, color='white', fontsize=10,
                        va='bottom', fontweight='bold',
                        bbox=dict(boxstyle='round,pad=0.3', facecolor='#333', alpha=0.65))
            figs.append(fig)
        return figs

    # -- Confidence Distribution ───────────────────────────
    def _make_pdf_confidence(self):
        from matplotlib.figure import Figure as MplFig

        counts = self._get_class_counts()
        active_classes = [k for k, v in counts.items() if v > 0]
        fig = MplFig(figsize=A4_LANDSCAPE, facecolor='white')
        fig.suptitle('Confidence Distribution', fontsize=16, fontweight='bold', color=TEXT, y=0.97)

        if not active_classes:
            fig.text(0.5, 0.5, 'No data', ha='center', va='center',
                     color=TEXT, fontsize=14)
            return fig

        cols = min(3, len(active_classes))
        rows = (len(active_classes) + cols - 1) // cols
        fig.subplots_adjust(hspace=0.55, wspace=0.40,
                            left=0.07, right=0.97, top=0.88, bottom=0.08)

        for i, cls_id in enumerate(active_classes):
            ax = fig.add_subplot(rows, cols, i + 1)
            ax.set_facecolor(PANEL)
            ax.tick_params(colors=TEXT, labelsize=8)
            for sp in ax.spines.values(): sp.set_color(SPINE)
            ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)

            confs = self._pa['confs_by_class'].get(cls_id, np.empty(0, dtype=np.float32))
            color = CLASS_COLORS_HEX.get(cls_id, '#4488CC')
            ax.hist(confs, bins=20, color=color, alpha=0.80,
                    edgecolor='white', linewidth=0.4, range=(0, 1))
            ax.set_title(f'{CLASS_NAMES[cls_id]}\n(n={len(confs):,})',
                         color=TEXT, fontsize=9, pad=4)
            ax.set_xlabel('Confidence', color=SUBTEXT, fontsize=8)
            ax.set_ylabel('Count', color=SUBTEXT, fontsize=8)
            mean_conf = np.mean(confs)
            ax.axvline(mean_conf, color='#555', linestyle='--', linewidth=1, alpha=0.9)
            ylim = ax.get_ylim()
            ax.text(mean_conf + 0.02, ylim[1] * 0.88,
                    f'avg {mean_conf:.2f}', color=TEXT, fontsize=8)
        return fig


def show_detection_visualization(cells, slide_dimensions=None, thumbnail=None,
                                  roi_bounds=None, seg_prob_map=None, seg_class_names=None,
                                  roi_polygons=None, slide_path=None, parent=None,
                                  plot_arrays=None):
    """Helper function to display visualization dialog"""
    dialog = DetectionVisualizationDialog(
        cells, slide_dimensions, thumbnail, roi_bounds,
        seg_prob_map, seg_class_names, roi_polygons, slide_path, parent,
        plot_arrays=plot_arrays
    )
    dialog.show()
    return dialog
