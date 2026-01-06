"""
Comprehensive Pathology AI Solution - Main Entry Point
병리 이미지 뷰어 및 AI 분석 통합 프로그램
"""

import sys
from PyQt5.QtWidgets import QApplication
from viewer import PathologyViewer


def main():
    """메인 애플리케이션 실행"""
    app = QApplication(sys.argv)
    app.setApplicationName("Pathology AI Viewer")
    
    # 메인 뷰어 윈도우 생성
    viewer = PathologyViewer()
    viewer.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
