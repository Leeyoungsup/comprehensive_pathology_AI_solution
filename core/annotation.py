"""
Annotation data model
Structure based on the ASAP Annotation system
"""

from enum import Enum
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass, field
import json
from pathlib import Path
import uuid


class AnnotationType(Enum):
    """Annotation type"""
    POLYGON = "Polygon"
    POINT = "Point"
    RECTANGLE = "Rectangle"
    SPLINE = "Spline"


@dataclass
class Annotation:
    """
    Individual Annotation class
    Based on the ASAP Annotation structure
    """
    name: str
    type: AnnotationType
    coordinates: List[Tuple[float, float]]  # [(x, y), ...]
    color: Tuple[int, int, int] = (0, 255, 0)  # RGB
    group: str = "default"
    visible: bool = True
    selected: bool = False
    properties: Dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))  # Unique ID

    def to_dict(self):
        """Convert to dictionary"""
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
        """Create from dictionary"""
        return cls(
            id=data.get('id', str(uuid.uuid4())),  # Use existing ID or generate new one
            name=data['name'],
            type=AnnotationType(data['type']),
            coordinates=data['coordinates'],
            color=tuple(data.get('color', (0, 255, 0))),
            group=data.get('group', 'default'),
            visible=data.get('visible', True),
            properties=data.get('properties', {})
        )

    def get_bounds(self) -> Tuple[float, float, float, float]:
        """Return annotation bounding box (x_min, y_min, x_max, y_max)"""
        if not self.coordinates:
            return (0, 0, 0, 0)

        xs = [coord[0] for coord in self.coordinates]
        ys = [coord[1] for coord in self.coordinates]

        return (min(xs), min(ys), max(xs), max(ys))

    def contains_point(self, x: float, y: float) -> bool:
        """Check if a point is inside the annotation"""
        if not self.coordinates:
            return False

        # POINT: Check if within a certain distance
        if self.type == AnnotationType.POINT:
            if len(self.coordinates) != 1:
                return False
            px, py = self.coordinates[0]
            distance = ((x - px) ** 2 + (y - py) ** 2) ** 0.5
            return distance < 10  # Within 10 pixels

        # RECTANGLE: Check if inside bounding box
        if self.type == AnnotationType.RECTANGLE:
            bounds = self.get_bounds()
            return (bounds[0] <= x <= bounds[2] and
                    bounds[1] <= y <= bounds[3])

        # POLYGON: Ray Casting Algorithm
        if self.type == AnnotationType.POLYGON:
            if len(self.coordinates) < 3:
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

        return False

    def get_area(self) -> float:
        """Calculate polygon area (Shoelace formula)"""
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
    Annotation collection management
    Based on ASAP AnnotationList
    """

    def __init__(self):
        self.annotations: List[Annotation] = []
        self.groups: Dict[str, List[Annotation]] = {'default': []}
        self.selected_annotation: Optional[Annotation] = None

    def add_annotation(self, annotation: Annotation):
        """Add annotation"""
        self.annotations.append(annotation)

        # Add to group
        if annotation.group not in self.groups:
            self.groups[annotation.group] = []
        self.groups[annotation.group].append(annotation)

    def remove_annotation(self, annotation: Annotation):
        """Remove annotation"""
        if annotation in self.annotations:
            self.annotations.remove(annotation)

            # Remove from group
            if annotation.group in self.groups:
                if annotation in self.groups[annotation.group]:
                    self.groups[annotation.group].remove(annotation)

            # Deselect if it was selected
            if self.selected_annotation == annotation:
                self.selected_annotation = None

    def get_annotations_at_point(self, x: float, y: float) -> List[Annotation]:
        """Return list of annotations containing the specified point"""
        result = []
        for annotation in self.annotations:
            if annotation.visible and annotation.contains_point(x, y):
                result.append(annotation)
        return result

    def get_annotations_in_rect(self, x_min: float, y_min: float,
                                 x_max: float, y_max: float) -> List[Annotation]:
        """Return list of annotations overlapping the specified region"""
        result = []
        for annotation in self.annotations:
            if not annotation.visible:
                continue

            bounds = annotation.get_bounds()
            # Check if bounding boxes overlap
            if not (bounds[2] < x_min or bounds[0] > x_max or
                    bounds[3] < y_min or bounds[1] > y_max):
                result.append(annotation)

        return result

    def select_annotation(self, annotation: Optional[Annotation]):
        """Select annotation"""
        # Deselect previous selection
        if self.selected_annotation:
            self.selected_annotation.selected = False

        # New selection
        self.selected_annotation = annotation
        if annotation:
            annotation.selected = True

    def get_group(self, group_name: str) -> List[Annotation]:
        """Return list of annotations in a specific group"""
        return self.groups.get(group_name, [])

    def clear(self):
        """Remove all annotations"""
        self.annotations.clear()
        self.groups = {'default': []}
        self.selected_annotation = None

    def save_to_json(self, file_path: str):
        """Save to JSON file"""
        data = {
            'annotations': [ann.to_dict() for ann in self.annotations]
        }

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def load_from_json(self, file_path: str):
        """Load from JSON file"""
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
