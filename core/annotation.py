"""
Annotation 데이터 모델
ASAP Annotation 시스템을 참고한 구조
"""

from enum import Enum
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass, field
import json
from pathlib import Path
import uuid


class AnnotationType(Enum):
    """Annotation 타입"""
    POLYGON = "Polygon"
    POINT = "Point"
    RECTANGLE = "Rectangle"
    SPLINE = "Spline"


@dataclass
class Annotation:
    """
    개별 Annotation 클래스
    ASAP의 Annotation 구조를 참고
    """
    name: str
    type: AnnotationType
    coordinates: List[Tuple[float, float]]  # [(x, y), ...]
    color: Tuple[int, int, int] = (0, 255, 0)  # RGB
    group: str = "default"
    visible: bool = True
    selected: bool = False
    properties: Dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))  # 고유 ID
    
    def to_dict(self):
        """딕셔너리로 변환"""
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type.value,
            'coordinates': self.coordinates,
            'color': self.color,
            'group': self.group,
            'visible': self.visible,
            'properties': self.properties
        }
    
    @classmethod
    def from_dict(cls, data):
        """딕셔너리에서 생성"""
        return cls(
            id=data.get('id', str(uuid.uuid4())),  # 기존 ID 사용 또는 새로 생성
            name=data['name'],
            type=AnnotationType(data['type']),
            coordinates=data['coordinates'],
            color=tuple(data.get('color', (0, 255, 0))),
            group=data.get('group', 'default'),
            visible=data.get('visible', True),
            properties=data.get('properties', {})
        )
    
    def get_bounds(self) -> Tuple[float, float, float, float]:
        """Annotation의 경계 박스 반환 (x_min, y_min, x_max, y_max)"""
        if not self.coordinates:
            return (0, 0, 0, 0)
        
        xs = [coord[0] for coord in self.coordinates]
        ys = [coord[1] for coord in self.coordinates]
        
        return (min(xs), min(ys), max(xs), max(ys))
    
    def contains_point(self, x: float, y: float) -> bool:
        """점이 Polygon 내부에 있는지 확인 (Ray Casting Algorithm)"""
        if self.type != AnnotationType.POLYGON or len(self.coordinates) < 3:
            return False
        
        n = len(self.coordinates)
        inside = False
        
        p1x, p1y = self.coordinates[0]
        for i in range(1, n + 1):
            p2x, p2y = self.coordinates[i % n]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
        
        return inside
    
    def get_area(self) -> float:
        """Polygon 면적 계산 (Shoelace formula)"""
        if self.type != AnnotationType.POLYGON or len(self.coordinates) < 3:
            return 0.0
        
        n = len(self.coordinates)
        area = 0.0
        
        for i in range(n):
            j = (i + 1) % n
            area += self.coordinates[i][0] * self.coordinates[j][1]
            area -= self.coordinates[j][0] * self.coordinates[i][1]
        
        return abs(area) / 2.0


class AnnotationList:
    """
    Annotation 컬렉션 관리
    ASAP AnnotationList 참고
    """
    
    def __init__(self):
        self.annotations: List[Annotation] = []
        self.groups: Dict[str, List[Annotation]] = {'default': []}
        self.selected_annotation: Optional[Annotation] = None
    
    def add_annotation(self, annotation: Annotation):
        """Annotation 추가"""
        self.annotations.append(annotation)
        
        # 그룹에 추가
        if annotation.group not in self.groups:
            self.groups[annotation.group] = []
        self.groups[annotation.group].append(annotation)
    
    def remove_annotation(self, annotation: Annotation):
        """Annotation 제거"""
        if annotation in self.annotations:
            self.annotations.remove(annotation)
            
            # 그룹에서 제거
            if annotation.group in self.groups:
                if annotation in self.groups[annotation.group]:
                    self.groups[annotation.group].remove(annotation)
            
            # 선택된 annotation이면 해제
            if self.selected_annotation == annotation:
                self.selected_annotation = None
    
    def get_annotations_at_point(self, x: float, y: float) -> List[Annotation]:
        """특정 점을 포함하는 Annotation 목록 반환"""
        result = []
        for annotation in self.annotations:
            if annotation.visible and annotation.contains_point(x, y):
                result.append(annotation)
        return result
    
    def get_annotations_in_rect(self, x_min: float, y_min: float, 
                                 x_max: float, y_max: float) -> List[Annotation]:
        """특정 영역과 겹치는 Annotation 목록 반환"""
        result = []
        for annotation in self.annotations:
            if not annotation.visible:
                continue
            
            bounds = annotation.get_bounds()
            # 경계 박스가 겹치는지 확인
            if not (bounds[2] < x_min or bounds[0] > x_max or 
                    bounds[3] < y_min or bounds[1] > y_max):
                result.append(annotation)
        
        return result
    
    def select_annotation(self, annotation: Optional[Annotation]):
        """Annotation 선택"""
        # 이전 선택 해제
        if self.selected_annotation:
            self.selected_annotation.selected = False
        
        # 새로운 선택
        self.selected_annotation = annotation
        if annotation:
            annotation.selected = True
    
    def get_group(self, group_name: str) -> List[Annotation]:
        """특정 그룹의 Annotation 목록 반환"""
        return self.groups.get(group_name, [])
    
    def clear(self):
        """모든 Annotation 제거"""
        self.annotations.clear()
        self.groups = {'default': []}
        self.selected_annotation = None
    
    def save_to_json(self, file_path: str):
        """JSON 파일로 저장"""
        data = {
            'annotations': [ann.to_dict() for ann in self.annotations]
        }
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    
    def load_from_json(self, file_path: str):
        """JSON 파일에서 로드"""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self.clear()
        for ann_data in data['annotations']:
            annotation = Annotation.from_dict(ann_data)
            self.add_annotation(annotation)
    
    def __len__(self):
        return len(self.annotations)
    
    def __iter__(self):
        return iter(self.annotations)
