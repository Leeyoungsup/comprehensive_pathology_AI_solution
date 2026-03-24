"""
Annotation management service
Business logic for ROI annotation save/load operations
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional


class AnnotationService:
    """Service handling annotation management business logic"""

    @staticmethod
    def save_annotations(annotations: List, file_path: str) -> Tuple[bool, str]:
        """
        Save annotations to a JSON file

        Args:
            annotations: List of Annotation objects
            file_path: File path to save to

        Returns:
            (success, message)
        """
        try:
            # Convert Annotation objects to dictionaries
            data = []
            for ann in annotations:
                ann_dict = {
                    'name': ann.name,
                    'color': ann.color,
                    'points': [(p.x(), p.y()) for p in ann.points]
                }
                data.append(ann_dict)

            # Save as JSON
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            file_name = Path(file_path).name
            return True, f"ROI saved: {file_name} ({len(annotations)} items)"

        except Exception as e:
            return False, f"Failed to save ROI: {str(e)}"

    @staticmethod
    def load_annotations(file_path: str) -> Tuple[Optional[List[Dict]], str]:
        """
        Load annotations from a JSON file

        Args:
            file_path: File path to load from

        Returns:
            (annotation data list or None, message)
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if not isinstance(data, list):
                return None, "Invalid file format."

            file_name = Path(file_path).name
            return data, f"ROI loaded: {file_name} ({len(data)} items)"

        except FileNotFoundError:
            return None, f"File not found: {file_path}"
        except json.JSONDecodeError:
            return None, "Failed to parse JSON file"
        except Exception as e:
            return None, f"Failed to load ROI: {str(e)}"

    @staticmethod
    def validate_annotation_data(data: List[Dict]) -> Tuple[bool, str]:
        """
        Validate annotation data

        Args:
            data: Annotation data list

        Returns:
            (is_valid, message)
        """
        if not data:
            return False, "Annotation data is empty."

        for i, ann in enumerate(data):
            if not isinstance(ann, dict):
                return False, f"Annotation {i}: Not a dictionary format."

            if 'points' not in ann:
                return False, f"Annotation {i}: Missing 'points' field."

            if not isinstance(ann['points'], list):
                return False, f"Annotation {i}: 'points' is not a list."

            if len(ann['points']) < 3:
                return False, f"Annotation {i}: At least 3 points are required."

        return True, "Valid annotation data"

    @staticmethod
    def export_to_asap_xml(annotations: List, output_path: str) -> Tuple[bool, str]:
        """
        Export annotations in ASAP XML format

        Args:
            annotations: List of Annotation objects
            output_path: Output file path

        Returns:
            (success, message)
        """
        try:
            import xml.etree.ElementTree as ET
            from xml.dom import minidom

            root = ET.Element("ASAP_Annotations")
            annotations_elem = ET.SubElement(root, "Annotations")

            for i, ann in enumerate(annotations):
                annotation = ET.SubElement(annotations_elem, "Annotation")
                annotation.set("Name", ann.name)
                annotation.set("Type", "Polygon")
                annotation.set("PartOfGroup", "ROI")
                annotation.set("Color", ann.color)

                coordinates = ET.SubElement(annotation, "Coordinates")
                for order, point in enumerate(ann.points):
                    coordinate = ET.SubElement(coordinates, "Coordinate")
                    coordinate.set("Order", str(order))
                    coordinate.set("X", str(float(point.x())))
                    coordinate.set("Y", str(float(point.y())))

            # AnnotationGroups
            annotation_groups = ET.SubElement(root, "AnnotationGroups")
            group = ET.SubElement(annotation_groups, "Group")
            group.set("Name", "ROI")
            group.set("PartOfGroup", "None")
            group.set("Color", "#00FF00")
            ET.SubElement(group, "Attributes")

            # Pretty print
            rough_string = ET.tostring(root, 'unicode')
            reparsed = minidom.parseString(rough_string)
            pretty_xml = reparsed.toprettyxml(indent="\t")

            # Write file
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(pretty_xml)

            file_name = Path(output_path).name
            return True, f"ASAP XML saved: {file_name}"

        except Exception as e:
            return False, f"Failed to save XML: {str(e)}"

    @staticmethod
    def get_annotation_statistics(annotations: List) -> Dict[str, Any]:
        """
        Annotation statistics

        Args:
            annotations: List of Annotation objects

        Returns:
            Statistics dictionary
        """
        if not annotations:
            return {
                'count': 0,
                'total_points': 0,
                'avg_points': 0
            }

        total_points = sum(len(ann.points) for ann in annotations)

        return {
            'count': len(annotations),
            'total_points': total_points,
            'avg_points': total_points / len(annotations) if annotations else 0
        }
