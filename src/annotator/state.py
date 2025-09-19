# src/bomia/annotation/state.py

from dataclasses import dataclass, field
from typing import Optional, Tuple

@dataclass
class AnnotationState:
    """
    Holds the mutable state of the annotation tool UI and process.
    """
    # File navigation and context
    current_index: int = 0
    total_files: int = 0
    current_filename: Optional[str] = None

    # UI display toggles
    show_help: bool = False
    show_stats: bool = False
    quit_confirm: bool = False

    # Mouse drawing state
    drawing: bool = False
    start_point: Optional[Tuple[int, int]] = None # Start point in *display* coordinates
    current_mouse_pos: Optional[Tuple[int, int]] = None # Current mouse pos in *display* coordinates

    # Image information (updated when image changes)
    img_original_shape: Optional[Tuple[int, int]] = None # (height, width)
    img_display_shape: Optional[Tuple[int, int]] = None # (height, width)

    # Statistics data (calculated when needed)
    stats_data: Optional[dict] = field(default_factory=dict) # Store calculated stats
    
    # Annotation selection state (for Tab navigation)
    current_annotation_index: int = -1  # -1 means no selection
    
    # Auto-inference mode state
    auto_inference: bool = False
    
    # Auto-fixed bbox mode state
    auto_fixed_bbox: bool = False
    
    # Auto-skip mode state (0: OFF, 1: Frame, 2: Annotation)
    auto_skip: int = 0
    
    # Auto-skip timing
    auto_skip_triggered: bool = False
    auto_skip_delay_seconds: float = 0.3  # Brief delay to see the bbox was created
    
    # Display mode state (0: full, 1: no overlays, 2: boxes only)
    display_mode: int = 0
    
    # Last drawn bbox tracking for repeat functionality
    last_drawn_bbox: Optional[Tuple[int, int, int, int]] = None  # (x1, y1, x2, y2) in original image coordinates
    last_drawn_category_id: Optional[int] = None  # Category ID of the last drawn bbox
    last_drawn_category_name: Optional[str] = None  # Category name of the last drawn bbox
    
    # Last pressed category key tracking (for J key behavior)
    last_pressed_category_id: Optional[str] = None  # Category ID from last 0-9 key press
    last_pressed_category_name: Optional[str] = None  # Category name from last 0-9 key press

    def reset_drawing(self):
        """Resets the drawing-related state."""
        self.drawing = False
        self.start_point = None
        # Keep current_mouse_pos, it's updated continuously by callback

    def reset_overlays(self, except_help: bool = False, except_stats: bool = False):
         """Turns off overlays, optionally keeping one active."""
         if not except_help:
             self.show_help = False
         if not except_stats:
             self.show_stats = False
         # Always reset quit confirm when toggling help/stats
         self.quit_confirm = False

    def update_image_info(self,
                          original_shape: Optional[Tuple[int, int]],
                          display_shape: Optional[Tuple[int, int]],
                          filename: Optional[str],
                          index: int,
                          total: int):
         """Updates state related to the currently loaded image."""
         self.img_original_shape = original_shape
         self.img_display_shape = display_shape
         self.current_filename = filename
         self.current_index = index
         self.total_files = total
         # Reset drawing state when image changes
         self.reset_drawing()
         # Reset annotation selection when image changes
         self.current_annotation_index = -1