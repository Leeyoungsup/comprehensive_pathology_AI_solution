"""
Annotation 관리 서비스
ROI annotation 저장/로드 관련 비즈니스 로직
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional


class AnnotationService:
    """Annotation 관리 관련 비즈니스 로직을 처리하는 서비스"""
    
    @staticmethod
    def save_annotations(annotations: List, file_path: str) -> Tuple[bool, str]:
        """
        Annotation을 JSON 파일로 저장
        
        Args:
            annotations: Annotation 객체 리스트
            file_path: 저장할 파일 경로
            
        Returns:
            (성공 여부, 메시지)
        """
        try:
            # Annotation 객체를 딕셔너리로 변환
            data = []
            for ann in annotations:
                ann_dict = {
                    'name': ann.name,
                    'color': ann.color,
                    'points': [(p.x(), p.y()) for p in ann.points]
                }
                data.append(ann_dict)
            
            # JSON으로 저장
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            file_name = Path(file_path).name
            return True, f"ROI 저장 완료: {file_name} ({len(annotations)}개)"
            
        except Exception as e:
            return False, f"ROI 저장 실패: {str(e)}"
    
    @staticmethod
    def load_annotations(file_path: str) -> Tuple[Optional[List[Dict]], str]:
        """
        JSON 파일에서 Annotation 로드
        
        Args:
            file_path: 로드할 파일 경로
            
        Returns:
            (Annotation 데이터 리스트 또는 None, 메시지)
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not isinstance(data, list):
                return None, "잘못된 파일 형식입니다."
            
            file_name = Path(file_path).name
            return data, f"ROI 로드 완료: {file_name} ({len(data)}개)"
            
        except FileNotFoundError:
            return None, f"파일을 찾을 수 없습니다: {file_path}"
        except json.JSONDecodeError:
            return None, "JSON 파일 파싱 실패"
        except Exception as e:
            return None, f"ROI 로드 실패: {str(e)}"
    
    @staticmethod
    def validate_annotation_data(data: List[Dict]) -> Tuple[bool, str]:
        """
        Annotation 데이터 유효성 검사
        
        Args:
            data: Annotation 데이터 리스트
            
        Returns:
            (유효 여부, 메시지)
        """
        if not data:
            return False, "Annotation 데이터가 비어있습니다."
        
        for i, ann in enumerate(data):
            if not isinstance(ann, dict):
                return False, f"Annotation {i}: 딕셔너리 형식이 아닙니다."
            
            if 'points' not in ann:
                return False, f"Annotation {i}: 'points' 필드가 없습니다."
            
            if not isinstance(ann['points'], list):
                return False, f"Annotation {i}: 'points'가 리스트가 아닙니다."
            
            if len(ann['points']) < 3:
                return False, f"Annotation {i}: 최소 3개의 점이 필요합니다."
        
        return True, "유효한 Annotation 데이터"
    
    @staticmethod
    def export_to_asap_xml(annotations: List, output_path: str) -> Tuple[bool, str]:
        """
        ASAP XML 형식으로 Annotation 내보내기
        
        Args:
            annotations: Annotation 객체 리스트
            output_path: 출력 파일 경로
            
        Returns:
            (성공 여부, 메시지)
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
            return True, f"ASAP XML 저장 완료: {file_name}"
            
        except Exception as e:
            return False, f"XML 저장 실패: {str(e)}"
    
    @staticmethod
    def get_annotation_statistics(annotations: List) -> Dict[str, Any]:
        """
        Annotation 통계 정보
        
        Args:
            annotations: Annotation 객체 리스트
            
        Returns:
            통계 정보 딕셔너리
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
