"""Helper for project-specific fixed annotations."""

from typing import List, Optional, Tuple, Dict
from config import config
import logging

logger = logging.getLogger(__name__)


class FixedAnnotationHelper:
    """Helper for project-specific fixed annotations."""
    
    def __init__(self, project_name: str = None):
        """Initialize with project name, defaulting to current project."""
        self.project_name = project_name or config.get("project.name")
        self._load_fixed_boxes()
    
    def _load_fixed_boxes(self):
        """Load fixed bbox configurations from config."""
        # Load fixed bboxes directly from config for any project
        fixed_bboxes_config = config.get(f"projects.{self.project_name}.annotation.fixed_bboxes", [])
        self.fixed_bboxes = fixed_bboxes_config
            
        logger.debug(f"Loaded {len(self.fixed_bboxes)} fixed bboxes for project '{self.project_name}'")
    
    def detect_round_from_filename(self, filename: str) -> int:
        """Deprecated: Round detection no longer needed with simplified fixed_bboxes."""
        # This method is kept for backward compatibility but is no longer used
        logger.debug(f"Round detection deprecated - using simplified fixed_bboxes (filename: '{filename}')")
        return 1
    
    def get_next_bbox(self, filename: str, existing_annotations: List[Dict]) -> Optional[Tuple]:
        """Get next fixed bbox to add, with optional random variation."""
        if not self.fixed_bboxes:
            logger.warning(f"No fixed bboxes defined for project {self.project_name}")
            return None
        
        # Find first bbox not already in existing annotations
        existing_bboxes = set()
        for ann in existing_annotations:
            bbox = ann.get('bbox', [])
            if bbox and len(bbox) == 4:
                existing_bboxes.add(tuple(bbox))
        
        logger.debug(f"Existing annotations: {len(existing_annotations)}, existing bboxes: {len(existing_bboxes)}")
        logger.debug(f"Fixed boxes available: {len(self.fixed_bboxes)}")
        
        for bbox in self.fixed_bboxes:
            base_bbox = tuple(bbox)
            
            # Check if we should add random variation
            add_random = config.get(f"projects.{self.project_name}.annotation.add_random_coords", False)
            
            if add_random:
                # Apply random variation to the bbox
                variation = config.get(f"projects.{self.project_name}.annotation.random_variation", 4)
                randomized_bbox = self._add_random_variation(base_bbox, variation)
                
                # Check if this randomized bbox is already used (unlikely but possible)
                if randomized_bbox not in existing_bboxes:
                    logger.debug(f"Found unused fixed bbox with random variation: {randomized_bbox}")
                    return randomized_bbox
            else:
                # Use exact bbox
                if base_bbox not in existing_bboxes:
                    logger.debug(f"Found unused fixed bbox: {base_bbox}")
                    return base_bbox
        
        logger.debug(f"All {len(self.fixed_bboxes)} fixed bboxes already used")
        return None
    
    def _add_random_variation(self, bbox: Tuple, variation: int) -> Tuple[int, int, int, int]:
        """Add random variation to a bbox."""
        import random
        
        x1, y1, x2, y2 = bbox
        
        # Add random variation
        x1_new = x1 + random.randint(-variation, variation)
        y1_new = y1 + random.randint(-variation, variation)
        x2_new = x2 + random.randint(-variation, variation)
        y2_new = y2 + random.randint(-variation, variation)
        
        # Ensure x1 < x2 and y1 < y2
        x1_final, x2_final = min(x1_new, x2_new), max(x1_new, x2_new)
        y1_final, y2_final = min(y1_new, y2_new), max(y1_new, y2_new)
        
        return (x1_final, y1_final, x2_final, y2_final)
    
    def get_all_fixed_bboxes_for_round(self, filename: str) -> List[Tuple]:
        """Get all fixed bboxes for the project (simplified - no rounds)."""
        return [tuple(bbox) for bbox in self.fixed_bboxes]