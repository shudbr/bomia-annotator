"""Project category management for multi-project support."""

from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class ProjectCategoryManager:
    """Manages categories based on the active project."""
    
    def __init__(self, config_manager=None):
        """Initialize the category manager."""
        self._config = config_manager
        self.project_name = None
        self.categories = {}
        self.subcategories = {}
        self.visualization_config = {}
        self.annotation_config = {}
        
        if self._config:
            self.reload_categories()
    
    def reload_categories(self):
        """Load categories for the current project."""
        if not self._config:
            logger.warning("No config manager available, cannot reload categories")
            return
            
        project_name = self._config.get("project.name")
        self.project_name = project_name
        
        # Get project-specific configuration
        project_config = self._config.get(f"projects.{project_name}", {})
        
        if not project_config:
            logger.warning(f"No configuration found for project '{project_name}'")
            # Fallback to empty categories
            self.categories = {}
            self.subcategories = {}
            self.visualization_config = {}
            self.annotation_config = {}
        else:
            self.categories = project_config.get("categories", {})
            self.subcategories = project_config.get("subcategories", {})
            self.visualization_config = project_config.get("visualization", {})
            self.annotation_config = project_config.get("annotation", {})
            
            logger.info(f"Loaded categories for project '{project_name}': {list(self.categories.values())}")
    
    def get_categories(self) -> Dict[str, str]:
        """Get categories for the current project."""
        return self.categories
    
    def get_subcategories(self) -> Dict[str, str]:
        """Get subcategories for the current project."""
        return self.subcategories
    
    def get_visualization_config(self) -> Dict[str, Any]:
        """Get visualization configuration for the current project."""
        return self.visualization_config
    
    def get_annotation_config(self) -> Dict[str, Any]:
        """Get annotation configuration for the current project."""
        return self.annotation_config
    
    def get_category_colors(self) -> Dict[int, tuple]:
        """Get category colors in BGR format for OpenCV."""
        colors = {}
        color_config = self.visualization_config.get("colors", {})
        
        for cls_id, rgb in color_config.items():
            # Convert string ID to int and RGB to BGR
            colors[int(cls_id)] = (rgb[2], rgb[1], rgb[0])
            
        return colors
    
    def get_label_mapping(self) -> Dict[str, str]:
        """Get label mapping for display names."""
        return self.visualization_config.get("label_mapping", {})
    
    def get_fixed_bboxes(self, round_key: str = None) -> list:
        """Get fixed bounding boxes for the current project."""
        fixed_bboxes = self.annotation_config.get("fixed_bboxes", [])
        
        if round_key:
            # Legacy compatibility - if round_key provided, issue warning but return all bboxes
            logger.warning(f"Round-specific bboxes deprecated. Returning all fixed bboxes (requested: {round_key})")
        
        # Handle both old format (list of lists) and new format (list of dicts)
        result = []
        for bbox_config in fixed_bboxes:
            if isinstance(bbox_config, list):
                # Old format: just bbox coordinates
                result.append(bbox_config)
            elif isinstance(bbox_config, dict) and "bbox" in bbox_config:
                # New format: dict with bbox and optional category
                result.append(bbox_config["bbox"])
            else:
                logger.warning(f"Invalid bbox configuration: {bbox_config}")
        
        return result
    
    def get_fixed_bboxes_with_categories(self, round_key: str = None) -> list:
        """Get fixed bounding boxes with category information for the current project."""
        fixed_bboxes = self.annotation_config.get("fixed_bboxes", [])
        
        if round_key:
            # Legacy compatibility - if round_key provided, issue warning but return all bboxes
            logger.warning(f"Round-specific bboxes deprecated. Returning all fixed bboxes (requested: {round_key})")
        
        # Return list of dicts with bbox and category info
        result = []
        for bbox_config in fixed_bboxes:
            if isinstance(bbox_config, list):
                # Old format: just bbox coordinates, no category
                result.append({
                    "bbox": bbox_config,
                    "category_id": None,
                    "category_name": None
                })
            elif isinstance(bbox_config, dict) and "bbox" in bbox_config:
                # New format: dict with bbox and optional category
                category_id = bbox_config.get("category")
                category_name = None
                
                # Look up category name if category_id is provided
                if category_id and category_id in self.categories:
                    category_name = self.categories[category_id]
                
                result.append({
                    "bbox": bbox_config["bbox"],
                    "category_id": category_id,
                    "category_name": category_name
                })
            else:
                logger.warning(f"Invalid bbox configuration: {bbox_config}")
        
        return result
    
    def switch_project(self, project_name: str):
        """Switch to a different project and reload categories."""
        if not self._config:
            logger.warning("No config manager available, cannot switch project")
            return
            
        if project_name != self.project_name:
            # Update config
            self._config._data["project"]["name"] = project_name
            # Reload categories
            self.reload_categories()
            logger.info(f"Switched to project '{project_name}'")