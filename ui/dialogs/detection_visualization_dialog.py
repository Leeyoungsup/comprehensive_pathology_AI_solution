"""
AI 검출 결과 시각화 다이얼로그
클래스 분포, Tumor 비율, 공간 히트맵, Confidence 분포를 탭으로 표시
"""

import numpy as np
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QTabWidget,
                              QWidget, QPushButton, QLabel, QSizePolicy)
from PyQt5.QtCore import Qt

import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# 클래스 정보 (detection.py와 동일)
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
    7: "#00BFFF",
}

BG = '#2b2b2b'
PANEL = '#1e1e1e'
SPINE = '#555555'


class DetectionVisualizationDialog(QDialog):
    """AI 검출 결과 시각화 다이얼로그"""

    def __init__(self, cells, slide_dimensions=None, parent=None):
        """
        Args:
            cells: 검출 세포 리스트 [{'x', 'y', 'cls_id', 'confidence'}, ...]
            slide_dimensions: (width, height) WSI 원본 크기
            parent: 부모 위젯
        """
        super().__init__(parent)
        self.cells = cells
        self.slide_dimensions = slide_dimensions
        self.setWindowTitle("AI 검출 결과 시각화")
        self.setMinimumSize(950, 680)
        self.setWindowModality(Qt.NonModal)
        self.setStyleSheet("background-color: #2b2b2b; color: white;")
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #555; }
            QTabBar::tab { background: #3b3b3b; color: white; padding: 6px 14px; }
            QTabBar::tab:selected { background: #555; }
        """)
        layout.addWidget(self.tab_widget)

        self.tab_widget.addTab(self._create_class_distribution_tab(), "클래스 분포")
        self.tab_widget.addTab(self._create_tumor_analysis_tab(), "Tumor 분석")
        self.tab_widget.addTab(self._create_spatial_heatmap_tab(), "공간 히트맵")
        self.tab_widget.addTab(self._create_confidence_tab(), "Confidence 분포")

        close_btn = QPushButton("닫기")
        close_btn.setFixedHeight(32)
        close_btn.setStyleSheet("background:#444; color:white; border-radius:4px;")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def _get_class_counts(self):
        counts = {cls_id: 0 for cls_id in CLASS_NAMES}
        for cell in self.cells:
            cls_id = cell.get('cls_id', 0)
            if cls_id in counts:
                counts[cls_id] += 1
        return counts

    def _styled_ax(self, ax):
        ax.set_facecolor(PANEL)
        ax.tick_params(colors='#cccccc', labelsize=8)
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
            ax.text(0.5, 0.5, '검출 데이터 없음', ha='center', va='center', color='white', fontsize=14)
            layout.addWidget(canvas)
            return widget

        names = [CLASS_NAMES[k] for k in active]
        values = list(active.values())
        colors = [CLASS_COLORS_HEX[k] for k in active]
        max_v = max(values)

        ax1 = fig.add_subplot(1, 2, 1)
        self._styled_ax(ax1)
        bars = ax1.barh(names, values, color=colors, height=0.6)
        ax1.set_xlabel('세포 수', color='#cccccc', fontsize=9)
        ax1.set_title('클래스별 세포 수', color='white', fontsize=11, pad=8)
        ax1.spines['left'].set_visible(True)
        ax1.spines['bottom'].set_visible(True)
        for bar, val in zip(bars, values):
            ax1.text(val + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                     f'{val:,}', va='center', color='white', fontsize=8)

        ax2 = fig.add_subplot(1, 2, 2)
        ax2.set_facecolor(BG)
        wedges, _, autotexts = ax2.pie(
            values, labels=None, colors=colors,
            autopct=lambda p: f'{p:.1f}%' if p > 3 else '',
            pctdistance=0.72, startangle=90,
            wedgeprops={'linewidth': 0.5, 'edgecolor': '#444'}
        )
        for t in autotexts:
            t.set_color('white')
            t.set_fontsize(8)
        ax2.set_title(f'비율  (총 {len(self.cells):,}개)', color='white', fontsize=11, pad=8)
        ax2.legend(wedges, [f'{n}  ({v:,})' for n, v in zip(names, values)],
                   loc='lower center', bbox_to_anchor=(0.5, -0.22),
                   ncol=2, fontsize=8, labelcolor='white',
                   facecolor='#3b3b3b', edgecolor=SPINE)

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
            pie_colors = ['#FF3333', '#00BFFF']
            pie_labels = [f'Tumor Epithelial\n({tumor:,}개)', f'Benign Epithelial\n({benign:,}개)']
            wedges, texts, autotexts = ax1.pie(
                pie_data, labels=pie_labels, colors=pie_colors,
                autopct='%1.1f%%', startangle=90,
                textprops={'color': 'white', 'fontsize': 10},
                wedgeprops={'linewidth': 0.8, 'edgecolor': '#444'}
            )
            for t in autotexts:
                t.set_fontsize(12)
                t.set_fontweight('bold')
        else:
            ax1.text(0.5, 0.5, 'Epithelial 세포 없음', ha='center', va='center',
                     color='#aaa', fontsize=13, transform=ax1.transAxes)
        ax1.set_title('Tumor vs Benign Epithelial', color='white', fontsize=11, pad=8)

        # Gauge bar
        ax2 = fig.add_subplot(1, 2, 2)
        self._styled_ax(ax2)
        ax2.set_xlim(0, 100)
        ax2.set_ylim(0, 1)
        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)
        ax2.spines['left'].set_visible(False)

        ax2.barh(0.5, 100, height=0.25, color='#444', left=0)
        bar_color = '#FF3333' if tumor_ratio >= 50 else '#FF8C00' if tumor_ratio >= 20 else '#FFA07A'
        ax2.barh(0.5, tumor_ratio, height=0.25, color=bar_color, left=0)

        ax2.text(50, 0.82, 'Tumor 비율', ha='center', color='#cccccc', fontsize=11)
        ax2.text(50, 0.22, f'{tumor_ratio:.1f}%', ha='center', color='white',
                 fontsize=28, fontweight='bold')
        ax2.set_xticks([0, 25, 50, 75, 100])
        ax2.set_xticklabels(['0%', '25%', '50%', '75%', '100%'], color='#cccccc')
        ax2.set_yticks([])
        ax2.set_title(f'Tumor / (Tumor + Benign)  [{total_epi:,}개 기준]',
                      color='white', fontsize=10, pad=8)

        layout.addWidget(canvas)

        summary = QLabel(
            f"  Tumor Epithelial: {tumor:,}개   |   "
            f"Benign Epithelial: {benign:,}개   |   "
            f"Tumor 비율: {tumor_ratio:.1f}%"
        )
        summary.setStyleSheet(
            "color: white; background: #3b3b3b; padding: 6px 10px; border-radius: 4px;"
        )
        layout.addWidget(summary)
        return widget

    def _create_spatial_heatmap_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        fig = Figure(facecolor=BG, tight_layout=True)
        canvas = FigureCanvas(fig)
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        if not self.cells or not self.slide_dimensions:
            ax = fig.add_subplot(111)
            ax.set_facecolor(PANEL)
            ax.text(0.5, 0.5, '슬라이드 크기 정보 없음', ha='center', va='center',
                    color='white', fontsize=13)
            layout.addWidget(canvas)
            return widget

        w, h = self.slide_dimensions
        bins_x = 80
        bins_y = max(10, int(bins_x * h / w))

        all_x = np.array([c['x'] for c in self.cells])
        all_y = np.array([c['y'] for c in self.cells])
        tumor_cells = [c for c in self.cells if c.get('cls_id') == 6]
        tumor_x = np.array([c['x'] for c in tumor_cells])
        tumor_y = np.array([c['y'] for c in tumor_cells])

        ax1 = fig.add_subplot(1, 2, 1)
        ax1.set_facecolor('#111')
        ax1.set_title('전체 세포 밀도', color='white', fontsize=11, pad=8)
        if len(all_x) > 0:
            h2d, xedges, yedges = np.histogram2d(all_x, all_y, bins=(bins_x, bins_y),
                                                   range=[[0, w], [0, h]])
            im1 = ax1.imshow(h2d.T, origin='upper', aspect='auto',
                             extent=[0, w, h, 0], cmap='hot', interpolation='gaussian')
            fig.colorbar(im1, ax=ax1, label='밀도', fraction=0.046, pad=0.04)
        ax1.set_xticks([])
        ax1.set_yticks([])

        ax2 = fig.add_subplot(1, 2, 2)
        ax2.set_facecolor('#111')
        ax2.set_title('Tumor Epithelial 밀도', color='white', fontsize=11, pad=8)
        if len(tumor_x) > 0:
            h2d_t, _, _ = np.histogram2d(tumor_x, tumor_y, bins=(bins_x, bins_y),
                                          range=[[0, w], [0, h]])
            im2 = ax2.imshow(h2d_t.T, origin='upper', aspect='auto',
                             extent=[0, w, h, 0], cmap='Reds', interpolation='gaussian')
            fig.colorbar(im2, ax=ax2, label='밀도', fraction=0.046, pad=0.04)
        else:
            ax2.text(0.5, 0.5, 'Tumor Epithelial 없음', ha='center', va='center',
                     color='#aaa', fontsize=13, transform=ax2.transAxes)
        ax2.set_xticks([])
        ax2.set_yticks([])

        # colorbar label color
        for ax in [ax1, ax2]:
            if ax.images:
                cb = fig.axes[-1] if fig.axes else None

        layout.addWidget(canvas)
        return widget

    def _create_confidence_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        counts = self._get_class_counts()
        active_classes = [k for k, v in counts.items() if v > 0]

        if not active_classes:
            label = QLabel("데이터 없음")
            label.setStyleSheet("color: white;")
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

            confs = [c['confidence'] for c in self.cells if c.get('cls_id') == cls_id]
            color = CLASS_COLORS_HEX.get(cls_id, '#FFFFFF')

            ax.hist(confs, bins=20, color=color, alpha=0.85, edgecolor='#333',
                    range=(0, 1))
            ax.set_title(f'{CLASS_NAMES[cls_id]}\n(n={len(confs):,})',
                         color='white', fontsize=8, pad=4)
            ax.set_xlabel('Confidence', color='#aaa', fontsize=7)
            ax.set_ylabel('Count', color='#aaa', fontsize=7)

            mean_conf = np.mean(confs)
            ax.axvline(mean_conf, color='white', linestyle='--', linewidth=1, alpha=0.8)
            ylim = ax.get_ylim()
            ax.text(mean_conf + 0.02, ylim[1] * 0.88,
                    f'avg {mean_conf:.2f}', color='white', fontsize=7)

        layout.addWidget(canvas)
        return widget


def show_detection_visualization(cells, slide_dimensions=None, parent=None):
    """시각화 다이얼로그 표시 헬퍼 함수"""
    dialog = DetectionVisualizationDialog(cells, slide_dimensions, parent)
    dialog.show()
    return dialog
