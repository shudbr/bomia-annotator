# Complete file: src/bomia/annotation/renderer.py
# -*- coding: utf-8 -*-
import cv2
import numpy as np
import logging
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime # <<< Added import

# Import definitions and constants
try:
    from .definitions import CATEGORIES, SUBCATEGORIES
    from .store import ANNOTATION_SOURCE_HUMAN, ANNOTATION_SOURCE_INFERENCE
except ImportError:
    # Define fallbacks if imports fail
    CATEGORIES = {}
    SUBCATEGORIES = {}
    ANNOTATION_SOURCE_HUMAN = "human"
    ANNOTATION_SOURCE_INFERENCE = "inference"
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.warning("Could not import definitions or store constants in renderer. Using fallbacks.")
else:
     logger = logging.getLogger(__name__)

class AnnotationRenderer:
    """
    Handles drawing the annotation UI elements (text, multiple boxes, overlays)
    onto an image frame based on the new data structure.
    - Saved boxes have fixed colors based on category ID.
    - Labels have background matching box color.
    - Label text color (black/white) is chosen for contrast against the background.
    - The last added box has increased thickness for visual cue.
    - Annotation source (Human/Inference) is indicated in the text label.
    - Category ID (key code) is included in the text label.
    - Subcategory name is included in the label if present in the annotation.
    """
    # --- PROFESSIONAL COLOR PALETTE ---
    # Modern dark theme with vibrant accents
    BASE_COLORS = {
        'text': (250, 250, 255),       # Pure white with slight blue tint
        'filename': (255, 220, 0),     # Electric cyan
        'header': (255, 220, 0),       # Electric cyan
        'info': (200, 200, 210),       # Light gray with blue tint
        'success': (100, 255, 150),    # Neon green
        'warning': (0, 215, 255),      # Golden orange
        'error': (100, 100, 255),      # Bright red
        'bg': (25, 25, 30),            # Deep dark background
        'bg_overlay': (15, 15, 20),    # Ultra dark overlay
        'drawing': (150, 255, 100),    # Lime green for drawing
        'label_text_bright_bg': (10, 10, 15), # Almost black for bright backgrounds
        'label_text_dark_bg': (250, 250, 255), # Bright white for dark backgrounds
        'key_border': (100, 100, 110), # Subtle gray border
        'key_bg': (35, 35, 42),        # Dark key background
        'gradient_start': (35, 30, 40), # Gradient start color
        'gradient_end': (20, 20, 25),   # Gradient end color
        'accent': (255, 200, 0),       # Accent cyan
        'accent_secondary': (150, 255, 0), # Secondary accent green
        'shadow': (0, 0, 0),           # Pure black for shadows
        'glow': (255, 255, 255)        # White for glow effects
    }
    # Professional bounding box colors - More vibrant and modern (BGR format)
    CATEGORY_BBOX_COLORS = {
        '0': (255, 100, 50),        # Bright Blue
        '1': (100, 255, 100),       # Neon Green
        '2': (100, 100, 255),       # Bright Red
        '3': (255, 255, 100),       # Bright Cyan
        '4': (255, 100, 255),       # Bright Magenta
        '5': (0, 200, 255),         # Bright Orange
        '6': (255, 220, 0),         # Electric Yellow
        '7': (200, 100, 255),       # Light Purple
        '8': (100, 255, 200),       # Mint Green
        '9': (255, 150, 200),       # Hot Pink
        '10': (100, 200, 200),      # Teal
        '11': (200, 140, 100),      # Bronze
        '12': (180, 200, 100),      # Lime
        '13': (100, 100, 200),      # Navy Blue
        '14': (245, 230, 200),      # Cream
        '15': (240, 240, 180),      # Light Yellow
        None: (150, 150, 160),      # Modern Gray
        'default': (150, 150, 160)  # Modern Gray
    }
    # --- END COLOR MAPPINGS ---

    # Professional drawing constants
    BOX_THICKNESS_DEFAULT = 2      # Thicker for better visibility
    BOX_THICKNESS_ACTIVE = 3       # For the selected box
    BOX_THICKNESS_GLOW = 4         # For glow effect
    LUMINANCE_THRESHOLD = 140      # Threshold to decide between black/white text
    CORNER_RADIUS = 4               # Rounded corners for modern look
    SHADOW_OFFSET = 3               # Shadow offset for depth
    GLOW_INTENSITY = 0.3            # Glow effect intensity

    def __init__(self, state=None, store=None):
        """Initialize the renderer."""
        self.state = state
        self.store = store
        self.font = cv2.FONT_HERSHEY_DUPLEX  # More modern font
        self.font_scale_small = 0.45
        self.font_scale_medium = 0.6
        self.font_scale_large = 0.8
        self.line_type = cv2.LINE_AA  # Anti-aliasing for smooth lines
        self.overlay_alpha = 0.88     # Higher opacity for better contrast
        self.overlay_box_alpha = 0.92 # Even higher for overlays
        # Professional layout with larger UI areas
        self.header_height_percent = 0.08  # 8% for more spacious header
        self.footer_height_percent = 0.06  # 6% for better footer
        # Minimum heights to ensure readability
        self.min_header_height = 50
        self.min_footer_height = 40
        # Get default text colors from base map
        self.text_color = self.BASE_COLORS.get('text')
        self.filename_color = self.BASE_COLORS.get('filename')

    def _calculate_luminance(self, color_bgr: Tuple[int, int, int]) -> float:
        """Calculates the perceived luminance of a BGR color."""
        # Standard formula: L = 0.299*R + 0.587*G + 0.114*B
        # For BGR: L = 0.114*B + 0.587*G + 0.299*R
        # Ensure values are within 0-255 range before calculation
        b = max(0, min(255, color_bgr[0]))
        g = max(0, min(255, color_bgr[1]))
        r = max(0, min(255, color_bgr[2]))
        return 0.114 * b + 0.587 * g + 0.299 * r

    def _get_contrasting_text_color(self, bg_color_bgr: Tuple[int, int, int]) -> Tuple[int, int, int]:
        """Chooses black or white text color based on background luminance."""
        try:
            luminance = self._calculate_luminance(bg_color_bgr)
            if luminance > self.LUMINANCE_THRESHOLD:
                return self.BASE_COLORS.get('label_text_bright_bg', (0, 0, 0)) # Black for bright BG
            else:
                return self.BASE_COLORS.get('label_text_dark_bg', (255, 255, 255)) # White for dark BG
        except Exception as e:
            logger.error(f"Error calculating luminance or getting text color for {bg_color_bgr}: {e}")
            return (255, 255, 255) # Fallback to white


    def draw_frame(
        self,
        img_display: np.ndarray,
        img_original_shape: Optional[Tuple[int, int]],
        file_data: Dict[str, Any],
        filename: str,
        current_index: int,
        total_files: int,
        show_help: bool,
        show_stats: bool,
        quit_confirm: bool,
        stats_data: Optional[Dict[str, Any]] = None,
        model_info: Optional[Dict[str, Any]] = None,
        inference_info: Optional[Dict[str, Any]] = None,
        auto_inference: bool = False,
        auto_fixed_bbox: bool = False,
        auto_skip: int = 0,
        display_mode: int = 0,
        category_filter: Optional[str] = None,
        nested_mode: bool = False
    ) -> np.ndarray:
        """Draws all UI elements onto the display image."""
        # --- Input Validation ---
        if img_display is None or img_display.size == 0:
            # Create a blank image indicating error if input is invalid
            disp_h, disp_w = (480, 640) # Fallback size
            blank_image = np.zeros((disp_h, disp_w, 3), dtype=np.uint8)
            error_color = self.BASE_COLORS.get('error', (0,0,255))
            cv2.putText(blank_image, "Error: Invalid Image", (50, disp_h // 2),
                        self.font, 1, error_color, 2, self.line_type)
            return blank_image

        # Validate original shape if provided (needed for scaling boxes)
        orig_h, orig_w = 0, 0
        if img_original_shape is not None and len(img_original_shape) == 2:
             orig_h, orig_w = img_original_shape
             if orig_h <= 0 or orig_w <= 0:
                 logger.warning(f"Invalid original dimensions ({orig_h}x{orig_w}) passed for {filename}. Skipping saved box drawing.")
                 orig_h, orig_w = 0, 0 # Reset to prevent drawing errors
        elif img_original_shape is not None: # Shape provided but wrong format
            logger.error(f"Invalid original_shape format for {filename}. Expected (h, w). Skipping saved box drawing.")
            orig_h, orig_w = 0, 0

        # Create a copy to draw on
        overlay = img_display.copy()
        disp_h, disp_w = overlay.shape[:2]
        # Check if display image itself is valid
        if disp_h <= 0 or disp_w <= 0:
             logger.error("Display image has invalid dimensions. Cannot draw.")
             return img_display # Return original if overlay is invalid

        # --- Draw UI Elements Based on Display Mode ---
        # Mode 0: Full Display (everything)
        # Mode 1: No Overlays (skip header/footer backgrounds and text)
        # Mode 2: Boxes Only (only bbox rectangles, no labels or overlays)
        
        # Draw backgrounds and text only in full display mode
        if display_mode == 0:
            self._draw_header_footer_backgrounds(overlay)

        # Draw saved bounding boxes (only if original dimensions are valid)
        if orig_h > 0 and orig_w > 0:
             self._draw_all_saved_bboxes(overlay, file_data, orig_h, orig_w, display_mode)
             
        # Draw temporary inference boxes (if any)
        if orig_h > 0 and orig_w > 0 and inference_info:
            self._draw_temporary_inferences(overlay, inference_info, orig_h, orig_w, display_mode)

        # Draw text information only in full display mode
        if display_mode == 0:
            self._draw_header_text(overlay, filename, current_index, total_files, model_info, auto_inference, auto_fixed_bbox, auto_skip, category_filter, nested_mode)
            self._draw_annotation_status(overlay, file_data, inference_info) # <-- MODIFIED internally
            self._draw_footer_text(overlay, filename, current_index, total_files, file_data, inference_info, model_info)

        # Draw large central overlays if active (Help, Stats, Quit Confirm) - only in full display mode
        if display_mode == 0 and (show_help or show_stats or quit_confirm):
            self._draw_center_overlay(overlay, show_help, show_stats, quit_confirm, stats_data, model_info)

        return overlay

    def _draw_all_saved_bboxes(self, overlay: np.ndarray, file_data: Dict[str, Any], orig_h: int, orig_w: int, display_mode: int = 0):
        """Draws all bounding boxes from the 'annotations' list with category colors."""
        # Safely get the annotations list
        annotations_list = file_data.get('annotations', []) if isinstance(file_data, dict) else []
        if not isinstance(annotations_list, list):
            logger.warning(f"Annotations data for {file_data.get('original_path', 'unknown file')} is not a list.")
            return # Cannot process if not a list

        num_annotations = len(annotations_list)
        # Get the selected annotation index from state
        selected_index = self.state.current_annotation_index if hasattr(self.state, 'current_annotation_index') else -1
        
        # Iterate through each annotation entry for the file
        for i, annotation_entry in enumerate(annotations_list):
             if isinstance(annotation_entry, dict):
                 # Determine if this is the last annotation added (for highlighting)
                 is_last = (i == num_annotations - 1)
                 # Determine if this annotation is selected
                 is_selected = (i == selected_index)
                 # Draw the individual box and its label
                 self._draw_single_saved_bbox(overlay, annotation_entry, orig_h, orig_w, is_last=is_last, is_selected=is_selected, display_mode=display_mode)
             else:
                 logger.warning(f"Skipping invalid annotation entry (not a dict): {annotation_entry}")

    # --- MODIFIED: To include subcategory in label ---
    def _draw_single_saved_bbox(self, overlay: np.ndarray, annotation_entry: Dict[str, Any], orig_h: int, orig_w: int, is_last: bool = False, is_selected: bool = False, display_mode: int = 0):
        """
        Draws a single bounding box and its corresponding text label.
        - Box color is determined by category ID.
        - Label background matches box color.
        - Label text color (black/white) contrasts with the background.
        - Last added box (if is_last is True) uses thicker lines.
        - Selected box (if is_selected is True) uses extra thick lines and a highlight.
        - Includes subcategory name in the label if present.
        """
        # Extract bbox data, return if invalid
        bbox = annotation_entry.get('bbox')
        if not (bbox and isinstance(bbox, (list, tuple)) and len(bbox) == 4):
            logger.debug(f"Skipping annotation entry with invalid bbox: {annotation_entry.get('bbox')}")
            return

        # Extract other relevant data
        source = annotation_entry.get('annotation_source', 'unknown')
        category_id = annotation_entry.get('category_id') # Can be None if not classified yet
        category_name = annotation_entry.get('category_name', 'No Cat') # Default name if missing
        subcategory_name = annotation_entry.get('subcategory_name') # <-- Get subcategory name

        # Determine colors based on category
        box_color = self.CATEGORY_BBOX_COLORS.get(str(category_id), self.CATEGORY_BBOX_COLORS['default'])
        label_bg_color = box_color # Label background matches box color
        label_text_color = self._get_contrasting_text_color(label_bg_color)

        # Determine source tag for the label
        if source == ANNOTATION_SOURCE_HUMAN: source_tag = "Human"
        elif source == ANNOTATION_SOURCE_INFERENCE: source_tag = "Inference"
        else: source_tag = "?"

        # Use normal thickness for all boxes, black outline will provide emphasis for selected ones
        thickness = self.BOX_THICKNESS_DEFAULT  # Always use 1px thickness

        # Get display dimensions and calculate scaling factors
        disp_h, disp_w = overlay.shape[:2]
        if disp_h <= 0 or disp_w <= 0 or orig_w <= 0 or orig_h <=0:
             logger.error("Cannot draw bbox, invalid original or display dimensions.")
             return

        scale_x = disp_w / orig_w
        scale_y = disp_h / orig_h

        try:
            # Get original coordinates from bbox data
            x1_orig, y1_orig, x2_orig, y2_orig = map(float, bbox) # Use float for intermediate scaling
            # Scale coordinates to display size, ensuring x1 < x2 and y1 < y2
            x1_disp = int(min(x1_orig, x2_orig) * scale_x)
            y1_disp = int(min(y1_orig, y2_orig) * scale_y)
            x2_disp = int(max(x1_orig, x2_orig) * scale_x)
            y2_disp = int(max(y1_orig, y2_orig) * scale_y)

            # Clamp coordinates to be within display bounds
            x1_disp = max(0, min(x1_disp, disp_w - 1))
            y1_disp = max(0, min(y1_disp, disp_h - 1))
            x2_disp = max(0, min(x2_disp, disp_w - 1))
            y2_disp = max(0, min(y2_disp, disp_h - 1))

            # Only draw if the resulting box has valid dimensions
            if x1_disp < x2_disp and y1_disp < y2_disp:
                # Draw glow effect for selected boxes
                if is_selected:
                    # Create glow effect
                    glow_radius = 8
                    for i in range(glow_radius, 0, -2):
                        alpha = 0.1 * (glow_radius - i) / glow_radius
                        glow_color = tuple(min(255, int(c + (255 - c) * 0.3)) for c in box_color)
                        # Draw progressively smaller rectangles with decreasing opacity
                        temp_overlay = overlay.copy()
                        cv2.rectangle(temp_overlay, (x1_disp - i, y1_disp - i), (x2_disp + i, y2_disp + i),
                                    glow_color, 2, cv2.LINE_AA)
                        cv2.addWeighted(overlay, 1.0 - alpha, temp_overlay, alpha, 0, overlay)

                    # Draw shadow for depth
                    shadow_offset = 2
                    shadow_color = (0, 0, 0)
                    cv2.rectangle(overlay,
                                (x1_disp + shadow_offset, y1_disp + shadow_offset),
                                (x2_disp + shadow_offset, y2_disp + shadow_offset),
                                shadow_color, thickness, cv2.LINE_AA)

                # Draw the main bounding box with thicker lines for better visibility
                cv2.rectangle(overlay, (x1_disp, y1_disp), (x2_disp, y2_disp),
                            box_color, self.BOX_THICKNESS_ACTIVE if is_selected else self.BOX_THICKNESS_DEFAULT,
                            cv2.LINE_AA)

                # --- Draw the Text Label (only in modes 0 and 1, skip in mode 2) ---
                if display_mode != 2:  # Mode 2 is boxes only, no labels
                    # Construct label text
                    label_base = f"{category_id}: {category_name}" if category_id is not None else "No Cat"
                    # Append subcategory if it exists
                    if subcategory_name:
                        label_text = f"{label_base} [{source_tag}] [{subcategory_name}]"
                    else:
                        label_text = f"{label_base} [{source_tag}]"

                    # Setup text parameters
                    label_font_scale = self.font_scale_small
                    label_thickness = 1
                    (tw, th), baseline = cv2.getTextSize(label_text, self.font, label_font_scale, label_thickness)

                    # Calculate position for the label (above the box, adjusting if near top edge)
                    padding = 3 # Small padding around text
                    label_x = x1_disp # Align with left edge of box
                    label_y_base = y1_disp - baseline - padding # Default baseline position above box

                    # If default position is off-screen, move it below the top of the box
                    if label_y_base - th < padding: # Check if top of text goes off screen
                        label_y_base = y1_disp + th + baseline + padding # Position baseline inside box, near top

                    # Calculate final coords for background rectangle
                    label_y_top = label_y_base - th - padding
                    label_y_bottom = label_y_base + baseline + padding
                    label_x_right = label_x + tw + padding * 2

                    # Draw modern rounded badge with shadow
                    shadow_offset = 2

                    # Draw shadow first
                    shadow_pts = np.array([
                        [label_x + shadow_offset + 3, label_y_top + shadow_offset],
                        [label_x_right + shadow_offset - 3, label_y_top + shadow_offset],
                        [label_x_right + shadow_offset, label_y_top + shadow_offset + 3],
                        [label_x_right + shadow_offset, label_y_bottom + shadow_offset - 3],
                        [label_x_right + shadow_offset - 3, label_y_bottom + shadow_offset],
                        [label_x + shadow_offset + 3, label_y_bottom + shadow_offset],
                        [label_x + shadow_offset, label_y_bottom + shadow_offset - 3],
                        [label_x + shadow_offset, label_y_top + shadow_offset + 3]
                    ], np.int32)
                    cv2.fillPoly(overlay, [shadow_pts], (0, 0, 0))

                    # Draw rounded rectangle background
                    badge_pts = np.array([
                        [label_x + 3, label_y_top],
                        [label_x_right - 3, label_y_top],
                        [label_x_right, label_y_top + 3],
                        [label_x_right, label_y_bottom - 3],
                        [label_x_right - 3, label_y_bottom],
                        [label_x + 3, label_y_bottom],
                        [label_x, label_y_bottom - 3],
                        [label_x, label_y_top + 3]
                    ], np.int32)
                    cv2.fillPoly(overlay, [badge_pts], label_bg_color)

                    # Draw subtle border
                    border_color = tuple(min(255, int(c * 1.2)) for c in label_bg_color)
                    cv2.polylines(overlay, [badge_pts], True, border_color, 1, cv2.LINE_AA)

                    # Draw the label text with better anti-aliasing
                    cv2.putText(overlay, label_text,
                                (label_x + padding, label_y_base),
                                self.font, label_font_scale, label_text_color,
                                label_thickness, cv2.LINE_AA)
            else:
                logger.debug(f"Skipping drawing bbox with invalid display coords: ({x1_disp},{y1_disp})->({x2_disp},{y2_disp}) from original {bbox}")

        except Exception as e:
            # Catch potential errors during drawing
            logger.error(f"Error drawing saved bbox {bbox}: {e}", exc_info=True)
    # --- END MODIFICATION ---


    def _draw_header_footer_backgrounds(self, overlay: np.ndarray):
        """Draws modern gradient backgrounds for header and footer with subtle blur."""
        disp_h, disp_w = overlay.shape[:2]
        if disp_h <= 0 or disp_w <= 0: return

        # Calculate dynamic heights
        h_height = max(int(disp_h * self.header_height_percent), self.min_header_height)
        f_height = max(int(disp_h * self.footer_height_percent), self.min_footer_height)
        h_height = min(h_height, disp_h)
        f_height = min(f_height, disp_h - h_height if disp_h > h_height else 0)

        # Get gradient colors
        gradient_start = self.BASE_COLORS.get('gradient_start', (35, 30, 40))
        gradient_end = self.BASE_COLORS.get('gradient_end', (20, 20, 25))

        # Draw header with gradient
        if h_height > 0:
            header_roi = overlay[0:h_height, :]
            # Create gradient
            gradient = np.zeros_like(header_roi)
            for y in range(h_height):
                factor = y / h_height
                color = tuple(int(s + (e - s) * factor) for s, e in zip(gradient_start, gradient_end))
                gradient[y, :] = color

            # Apply with higher opacity for better contrast
            cv2.addWeighted(header_roi, 1.0 - self.overlay_alpha, gradient, self.overlay_alpha, 0, header_roi)

            # Add subtle bottom border line
            border_color = self.BASE_COLORS.get('accent', (255, 200, 0))
            cv2.line(overlay, (0, h_height-1), (disp_w, h_height-1), border_color, 1)

        # Draw footer with gradient (inverted)
        if f_height > 0:
            footer_roi = overlay[disp_h-f_height : disp_h, :]
            gradient = np.zeros_like(footer_roi)
            for y in range(f_height):
                factor = (f_height - y) / f_height
                color = tuple(int(s + (e - s) * factor) for s, e in zip(gradient_start, gradient_end))
                gradient[y, :] = color

            cv2.addWeighted(footer_roi, 1.0 - self.overlay_alpha, gradient, self.overlay_alpha, 0, footer_roi)

            # Add subtle top border line
            border_color = self.BASE_COLORS.get('accent', (255, 200, 0))
            cv2.line(overlay, (0, disp_h-f_height), (disp_w, disp_h-f_height), border_color, 1)

    def _draw_progress_bar(self, overlay: np.ndarray, current: int, total: int, x: int, y: int, width: int, height: int):
        """Draw a modern progress bar"""
        # Background
        cv2.rectangle(overlay, (x, y), (x + width, y + height), (50, 50, 60), -1)
        # Border
        cv2.rectangle(overlay, (x, y), (x + width, y + height), (80, 80, 90), 1)
        # Progress fill
        progress = current / total if total > 0 else 0
        fill_width = int(width * progress)
        if fill_width > 0:
            # Gradient fill effect
            gradient_color1 = self.BASE_COLORS.get('accent', (255, 200, 0))
            gradient_color2 = self.BASE_COLORS.get('accent_secondary', (150, 255, 0))
            cv2.rectangle(overlay, (x + 1, y + 1), (x + fill_width - 1, y + height - 1), gradient_color1, -1)

    def _draw_status_indicator(self, overlay: np.ndarray, text: str, status: bool, x: int, y: int):
        """Draw a modern status indicator with icon"""
        # Draw circle indicator
        color = self.BASE_COLORS.get('success' if status else 'error')
        cv2.circle(overlay, (x, y), 4, color, -1)
        # Draw status text
        cv2.putText(overlay, text, (x + 10, y + 3), self.font, self.font_scale_small,
                   self.BASE_COLORS.get('text'), 1, cv2.LINE_AA)
        return x + cv2.getTextSize(text, self.font, self.font_scale_small, 1)[0][0] + 20

    def _draw_header_text(self, overlay: np.ndarray, filename: str, current_index: int, total_files: int, model_info: Optional[Dict[str, Any]] = None, auto_inference: bool = False, auto_fixed_bbox: bool = False, auto_skip: int = 0, category_filter: Optional[str] = None, nested_mode: bool = False):
        """Draws professional header with progress bar, status indicators and organized layout."""
        disp_h, disp_w = overlay.shape[:2]
        if disp_h <= 0 or disp_w <= 0: return
        
        # Calculate dynamic header height and text position
        header_height = max(int(disp_h * self.header_height_percent), self.min_header_height)
        header_height = min(header_height, disp_h)
        
        # Scale font based on header height
        font_scale = max(0.4, min(0.9, header_height / 120.0))  # Scale between 0.4 and 0.9
        
        # Professional layout positioning
        margin = 15
        section_gap = 30
        center_y = header_height // 2

        # Draw progress bar at the top
        progress_bar_height = 6
        progress_bar_y = 10
        progress_bar_width = 200
        self._draw_progress_bar(overlay, current_index + 1, total_files,
                               margin, progress_bar_y, progress_bar_width, progress_bar_height)

        # Draw frame counter next to progress bar
        frame_text = f"{current_index + 1}/{total_files}"
        frame_color = self.BASE_COLORS.get('text')
        cv2.putText(overlay, frame_text, (margin + progress_bar_width + 10, progress_bar_y + 6),
                   self.font, font_scale * 0.8, frame_color, 1, cv2.LINE_AA)

        # Main text line positioning
        text_y = center_y + 5
        text_y_line2 = text_y + 20  # Second line for additional info
        thickness = 1  # Clean thin text

        
        # Professional status indicators on the right side
        status_x = disp_w - margin
        status_y = center_y

        # Draw status indicators with modern icons
        if model_info and model_info.get('has_model', False):
            project_name = model_info.get('project_name', 'No Model')

            # Model name with icon
            model_text = f"MODEL: {project_name}"
            model_color = self.BASE_COLORS.get('accent')
            (model_w, _), _ = cv2.getTextSize(model_text, self.font, font_scale * 0.7, thickness)
            cv2.putText(overlay, model_text, (status_x - model_w - 200, status_y),
                       self.font, font_scale * 0.7, model_color, thickness, cv2.LINE_AA)

            # Status indicators with dots
            indicators = [
                ("AI", auto_inference),
                ("FIX", auto_fixed_bbox),
                ("SKIP", auto_skip > 0)
            ]

            indicator_x = status_x - 180
            for label, active in indicators:
                # Draw status dot
                dot_color = self.BASE_COLORS.get('success' if active else 'error')
                cv2.circle(overlay, (indicator_x, status_y - 3), 3, dot_color, -1)
                # Draw label
                cv2.putText(overlay, label, (indicator_x + 8, status_y + 2),
                           self.font, font_scale * 0.6, self.BASE_COLORS.get('text'),
                           thickness, cv2.LINE_AA)
                indicator_x += 50

                # Commented out - variables not defined
                # # Draw auto-skip label
                # (auto_skip_label_w, _), _ = cv2.getTextSize(auto_skip_label, self.font, font_scale, thickness)
                # auto_skip_label_x = x_pos - auto_skip_label_w
                # cv2.putText(overlay, auto_skip_label, (auto_skip_label_x, text_y_line1), self.font, font_scale, label_color, thickness, self.line_type)
                # x_pos = auto_skip_label_x
                #
                # # Draw auto-fixed status
                # (auto_fixed_status_w, _), _ = cv2.getTextSize(auto_fixed_status, self.font, font_scale, thickness)
                # auto_fixed_status_x = x_pos - auto_fixed_status_w
                # cv2.putText(overlay, auto_fixed_status, (auto_fixed_status_x, text_y_line1), self.font, font_scale, auto_fixed_color, thickness, self.line_type)
                # x_pos = auto_fixed_status_x
                #
                # # Draw auto-fixed label
                # (auto_fixed_label_w, _), _ = cv2.getTextSize(auto_fixed_label, self.font, font_scale, thickness)
                # auto_fixed_label_x = x_pos - auto_fixed_label_w
                # cv2.putText(overlay, auto_fixed_label, (auto_fixed_label_x, text_y_line1), self.font, font_scale, label_color, thickness, self.line_type)
                # x_pos = auto_fixed_label_x

                # Commented out - variables not defined
                # # Draw auto-inference status
                # (auto_inf_status_w, _), _ = cv2.getTextSize(auto_inf_status, self.font, font_scale, thickness)
                # Commented out - variables not defined
                # auto_inf_status_x = x_pos - auto_inf_status_w
                # cv2.putText(overlay, auto_inf_status, (auto_inf_status_x, text_y_line1), self.font, font_scale, auto_inf_color, thickness, self.line_type)
                # x_pos = auto_inf_status_x
                
                # Draw auto-inference label
                # (auto_inf_label_w, _), _ = cv2.getTextSize(auto_inf_label, self.font, font_scale, thickness)
                # auto_inf_label_x = x_pos - auto_inf_label_w
                # cv2.putText(overlay, auto_inf_label, (auto_inf_label_x, text_y_line1), self.font, font_scale, label_color, thickness, self.line_type)
                # x_pos = auto_inf_label_x
                
                # Draw model name - commented out (variables not defined)
                # (model_name_w, _), _ = cv2.getTextSize(model_name, self.font, font_scale, thickness)
                # model_name_x = x_pos - model_name_w
                # cv2.putText(overlay, model_name, (model_name_x, text_y_line1), self.font, font_scale, model_color, thickness, self.line_type)
                # x_pos = model_name_x
                #
                # # Draw model label (leftmost) - commented out (variables not defined)
                # (model_label_w, _), _ = cv2.getTextSize(model_label, self.font, font_scale, thickness)
                # model_label_x = x_pos - model_label_w
                # cv2.putText(overlay, model_label, (model_label_x, text_y_line1), self.font, font_scale, label_color, thickness, self.line_type)
            else:
                # No model case - show all auto statuses
                auto_inf_label = "Auto-Inf: "
                auto_inf_status = "ON" if auto_inference else "OFF"
                auto_fixed_label = " | Auto-Fixed: "
                auto_fixed_status = "ON" if auto_fixed_bbox else "OFF"
                auto_skip_label = " | Auto-Skip: "
                auto_skip_modes = ["OFF", "Frame", "Annotation"]
                auto_skip_status = auto_skip_modes[auto_skip] if 0 <= auto_skip < len(auto_skip_modes) else "OFF"
                no_model_label = "No model - "
                
                label_color = self.BASE_COLORS.get('info', (200, 200, 200))
                model_color = (100, 100, 100)  # Gray for no model
                auto_inf_color = (0, 255, 100) if auto_inference else (0, 0, 255)
                auto_fixed_color = (0, 255, 100) if auto_fixed_bbox else (0, 0, 255)
                auto_skip_color = (0, 255, 100) if auto_skip > 0 else (0, 0, 255)
                
                # Calculate positions and draw (right to left)
                x_pos = disp_w - 15
                
                # Auto-skip status (rightmost)
                (auto_skip_status_w, _), _ = cv2.getTextSize(auto_skip_status, self.font, font_scale, thickness)
                auto_skip_status_x = x_pos - auto_skip_status_w
                # cv2.putText(overlay, auto_skip_status, (auto_skip_status_x, text_y_line1), self.font, font_scale, auto_skip_color, thickness, self.line_type)
                x_pos = auto_skip_status_x
                
                # Auto-skip label
                (auto_skip_label_w, _), _ = cv2.getTextSize(auto_skip_label, self.font, font_scale, thickness)
                auto_skip_label_x = x_pos - auto_skip_label_w
                # cv2.putText(overlay, auto_skip_label, (auto_skip_label_x, text_y_line1), self.font, font_scale, label_color, thickness, self.line_type)
                x_pos = auto_skip_label_x
                
                # Auto-fixed status
                (auto_fixed_status_w, _), _ = cv2.getTextSize(auto_fixed_status, self.font, font_scale, thickness)
                auto_fixed_status_x = x_pos - auto_fixed_status_w
                # cv2.putText(overlay, auto_fixed_status, (auto_fixed_status_x, text_y_line1), self.font, font_scale, auto_fixed_color, thickness, self.line_type)
                x_pos = auto_fixed_status_x
                
                # Auto-fixed label
                (auto_fixed_label_w, _), _ = cv2.getTextSize(auto_fixed_label, self.font, font_scale, thickness)
                auto_fixed_label_x = x_pos - auto_fixed_label_w
                # cv2.putText(overlay, auto_fixed_label, (auto_fixed_label_x, text_y_line1), self.font, font_scale, label_color, thickness, self.line_type)
                x_pos = auto_fixed_label_x
                
                # Auto-inference status
                (auto_inf_status_w, _), _ = cv2.getTextSize(auto_inf_status, self.font, font_scale, thickness)
                # Commented out - variables not defined
                # auto_inf_status_x = x_pos - auto_inf_status_w
                # cv2.putText(overlay, auto_inf_status, (auto_inf_status_x, text_y_line1), self.font, font_scale, auto_inf_color, thickness, self.line_type)
                # x_pos = auto_inf_status_x
                
                # Auto-inference label
                (auto_inf_label_w, _), _ = cv2.getTextSize(auto_inf_label, self.font, font_scale, thickness)
                auto_inf_label_x = x_pos - auto_inf_label_w
                # cv2.putText(overlay, auto_inf_label, (auto_inf_label_x, text_y_line1), self.font, font_scale, label_color, thickness, self.line_type)
                x_pos = auto_inf_label_x
                
                # No model label (leftmost)
                (no_model_w, _), _ = cv2.getTextSize(no_model_label, self.font, font_scale, thickness)
                no_model_x = x_pos - no_model_w
                # cv2.putText(overlay, no_model_label, (no_model_x, text_y_line1), self.font, font_scale, model_color, thickness, self.line_type)
            
            # Part 4: Category filter (right side, second line)
            if category_filter:
                filter_text = f"Category Filter: {category_filter}"
                filter_color = (255, 255, 0)  # Yellow
                (filter_w, _), _ = cv2.getTextSize(filter_text, self.font, font_scale, thickness)
                filter_x = disp_w - filter_w - 15  # 15px from right edge
                cv2.putText(overlay, filter_text, (filter_x, text_y_line2), self.font, font_scale, filter_color, thickness, self.line_type)

            # Part 5: Nested Mode indicator (center-right, prominent)
            if nested_mode:
                nested_text = "[SHIFT] Nested BBox Mode"
                nested_color = (0, 255, 255)  # Bright yellow/cyan
                (nested_w, _), _ = cv2.getTextSize(nested_text, self.font, font_scale * 1.2, thickness + 1)
                # Position it center-right, or adjust based on category filter
                if category_filter:
                    nested_x = filter_x - nested_w - 30  # To the left of category filter
                else:
                    nested_x = disp_w - nested_w - 15  # Right edge
                cv2.putText(overlay, nested_text, (nested_x, text_y_line2), self.font, font_scale * 1.2, nested_color, thickness + 1, self.line_type)

    # --- MODIFIED: Removed top-level subcategory display ---
    def _draw_annotation_status(self, overlay: np.ndarray, file_data: Dict[str, Any], inference_info: Optional[Dict[str, Any]] = None):
        """Draws the annotation status (count) in the header (Line 2)."""
        disp_h, disp_w = overlay.shape[:2]
        if disp_h <= 0 or disp_w <= 0: return
        
        # Calculate dynamic header height and text position
        header_height = max(int(disp_h * self.header_height_percent), self.min_header_height)
        header_height = min(header_height, disp_h)
        
        # Scale font based on header height
        font_scale = max(0.4, min(0.9, header_height / 120.0))  # Scale between 0.4 and 0.9
        
        text_y_status = int(header_height * 0.75) # 75% down from top of header
        if text_y_status < 40: text_y_status = 40 # Minimum position

        # Safely get annotations list and count
        annotations_list = file_data.get('annotations', []) if isinstance(file_data, dict) else []
        num_annotations = len(annotations_list) if isinstance(annotations_list, list) else 0

        # Determine status text and color based on number of annotations
        status_text: str
        status_color: Tuple[int, int, int] # Type hint for color tuple

        # Color-code the annotation count: red for 0, green for >0
        label_text = "Annotations: "
        number_text = str(num_annotations)
        label_color = self.BASE_COLORS.get('info', (200, 200, 200))  # Gray for label
        if num_annotations == 0:
            number_color = self.BASE_COLORS.get('error', (0, 0, 255))  # Red for zero
        else:
            number_color = self.BASE_COLORS.get('success', (0, 255, 0))  # Green for positive

        # Draw the status text with separate colors
        thickness = 2 if font_scale > 0.6 else 1  # Thicker text for larger fonts
        # Draw "Annotations: " part
        cv2.putText(overlay, label_text, (15, text_y_status), self.font, font_scale, label_color, thickness, self.line_type)
        # Calculate position for the number part
        (label_w, _), _ = cv2.getTextSize(label_text, self.font, font_scale, thickness)
        number_x = 15 + label_w
        # Draw the number part with color coding
        cv2.putText(overlay, number_text, (number_x, text_y_status), self.font, font_scale, number_color, thickness, self.line_type)
    # --- END MODIFICATION ---
    
    def _draw_temporary_inferences(self, overlay: np.ndarray, inference_info: Dict[str, Any], orig_h: int, orig_w: int, display_mode: int = 0):
        """Draws temporary inference bounding boxes with dashed lines and highlights selected one."""
        temp_inferences = inference_info.get('temporary_inferences', [])
        current_idx = inference_info.get('current_index', -1)
        
        if not temp_inferences:
            return
            
        disp_h, disp_w = overlay.shape[:2]
        scale_x = disp_w / orig_w
        scale_y = disp_h / orig_h
        
        for i, inference in enumerate(temp_inferences):
            is_selected = (i == current_idx)
            
            # Get bbox and scale to display size
            bbox = inference.get('bbox')
            if not bbox or len(bbox) != 4:
                continue
                
            x1, y1, x2, y2 = bbox
            x1_disp = int(x1 * scale_x)
            y1_disp = int(y1 * scale_y)
            x2_disp = int(x2 * scale_x)
            y2_disp = int(y2 * scale_y)
            
            # Clamp to display bounds
            x1_disp = max(0, min(x1_disp, disp_w - 1))
            y1_disp = max(0, min(y1_disp, disp_h - 1))
            x2_disp = max(0, min(x2_disp, disp_w - 1))
            y2_disp = max(0, min(y2_disp, disp_h - 1))
            
            # Skip invalid boxes
            if x2_disp <= x1_disp or y2_disp <= y1_disp:
                continue
                
            # Get color for category
            category_id = inference.get('category_id', '0')
            base_color = self.CATEGORY_BBOX_COLORS.get(
                category_id, 
                self.CATEGORY_BBOX_COLORS.get('default', (128, 128, 128))
            )
            
            # Draw dashed rectangle for temporary inference
            thickness = 1  # Keep consistent thickness
            
            # Draw dashed lines by drawing segments
            dash_length = 3
            gap_length = 3
            
            # If selected, draw black outline first (thicker), then colored line on top
            if is_selected:
                black_thickness = 3
                
                # Draw black outline - Top edge
                x = x1_disp
                while x < x2_disp:
                    x_end = min(x + dash_length, x2_disp)
                    cv2.line(overlay, (x, y1_disp), (x_end, y1_disp), (0, 0, 0), black_thickness)
                    x += dash_length + gap_length
                    
                # Draw black outline - Bottom edge
                x = x1_disp
                while x < x2_disp:
                    x_end = min(x + dash_length, x2_disp)
                    cv2.line(overlay, (x, y2_disp), (x_end, y2_disp), (0, 0, 0), black_thickness)
                    x += dash_length + gap_length
                    
                # Draw black outline - Left edge
                y = y1_disp
                while y < y2_disp:
                    y_end = min(y + dash_length, y2_disp)
                    cv2.line(overlay, (x1_disp, y), (x1_disp, y_end), (0, 0, 0), black_thickness)
                    y += dash_length + gap_length
                    
                # Draw black outline - Right edge
                y = y1_disp
                while y < y2_disp:
                    y_end = min(y + dash_length, y2_disp)
                    cv2.line(overlay, (x2_disp, y), (x2_disp, y_end), (0, 0, 0), black_thickness)
                    y += dash_length + gap_length
            
            # Draw colored dashed lines on top
            # Top edge
            x = x1_disp
            while x < x2_disp:
                x_end = min(x + dash_length, x2_disp)
                cv2.line(overlay, (x, y1_disp), (x_end, y1_disp), base_color, thickness)
                x += dash_length + gap_length
                
            # Bottom edge
            x = x1_disp
            while x < x2_disp:
                x_end = min(x + dash_length, x2_disp)
                cv2.line(overlay, (x, y2_disp), (x_end, y2_disp), base_color, thickness)
                x += dash_length + gap_length
                
            # Left edge
            y = y1_disp
            while y < y2_disp:
                y_end = min(y + dash_length, y2_disp)
                cv2.line(overlay, (x1_disp, y), (x1_disp, y_end), base_color, thickness)
                y += dash_length + gap_length
                
            # Right edge
            y = y1_disp
            while y < y2_disp:
                y_end = min(y + dash_length, y2_disp)
                cv2.line(overlay, (x2_disp, y), (x2_disp, y_end), base_color, thickness)
                y += dash_length + gap_length
                
            # Draw label with confidence (only in modes 0 and 1, skip in mode 2)
            if display_mode != 2:  # Mode 2 is boxes only, no labels
                category_name = inference.get('category_name', 'Unknown')
                confidence = inference.get('confidence', 0.0)
                
                # Use "(f)" for fixed bboxes (confidence = 1.0) and normal confidence for inference
                if confidence == 1.0:
                    label_text = f"{category_name} (f)"
                else:
                    label_text = f"{category_name} ({confidence:.2f})"
                
                if is_selected:
                    label_text = f"[{i+1}/{len(temp_inferences)}] {label_text}"
                    
                # Label styling
                label_font_scale = self.font_scale_small + (0.1 if is_selected else 0)  # Slightly larger when selected
                label_thickness = 2 if is_selected else 1
                (tw, th), baseline = cv2.getTextSize(label_text, self.font, label_font_scale, label_thickness)
                
                # Position label
                padding = 3
                label_x = x1_disp
                label_y_base = y1_disp - baseline - padding
                
                if label_y_base - th < padding:
                    label_y_base = y1_disp + th + baseline + padding
                    
                # Draw background for label
                label_bg_color = (50, 50, 50) if not is_selected else (30, 30, 80)  # Darker blue-ish bg when selected
                label_text_color = (255, 255, 255) if not is_selected else (0, 0, 255)  # Red text when selected
                
                cv2.rectangle(overlay,
                             (label_x, label_y_base - th - padding),
                             (label_x + tw + padding * 2, label_y_base + baseline + padding),
                             label_bg_color, -1)
                             
                # Draw label text
                cv2.putText(overlay, label_text,
                           (label_x + padding, label_y_base),
                           self.font, label_font_scale, label_text_color,
                           label_thickness, self.line_type)

    def _draw_key(self, overlay: np.ndarray, text: str, x: int, y: int, padding: int = 5, font_scale: float = None) -> int:
        """Helper function to draw a single key hint (text with background/border)."""
        # Get colors and parameters
        text_color = self.BASE_COLORS.get('info', (200,200,200))
        bg_color = self.BASE_COLORS.get('key_bg', (70,70,70))
        border_color = self.BASE_COLORS.get('key_border', (100,100,100))
        scale = font_scale if font_scale is not None else self.font_scale_small
        thickness = 1

        # Calculate text size
        (tw, th), baseline = cv2.getTextSize(text, self.font, scale, thickness)

        # Calculate bounding box for the key background/border
        box_x1 = x
        box_y1 = y - th - padding # y is baseline, go up by text height and padding
        box_x2 = x + tw + 2 * padding
        box_y2 = y + baseline + padding

        # Draw filled background rectangle
        cv2.rectangle(overlay, (box_x1, box_y1), (box_x2, box_y2), bg_color, -1)
        # Draw border rectangle
        cv2.rectangle(overlay, (box_x1, box_y1), (box_x2, box_y2), border_color, 1)
        # Draw the key text itself
        text_x = x + padding # Position text inside the padding
        cv2.putText(overlay, text, (text_x, y), self.font, scale, text_color, thickness, self.line_type)

        # Return the X coordinate of the right edge of the drawn key
        return box_x2

    def _draw_footer_text(self, overlay: np.ndarray, filename: str, current_index: int, total_files: int, file_data: Dict[str, Any], inference_info: Optional[Dict[str, Any]] = None, 
                          model_info: Optional[Dict[str, Any]] = None):
        """Draws the hotkey hints text in the footer area."""
        disp_h, disp_w = overlay.shape[:2]
        if disp_h <= 0 or disp_w <= 0: return
        
        # Calculate dynamic footer height
        footer_height = max(int(disp_h * self.footer_height_percent), self.min_footer_height)
        footer_height = min(footer_height, disp_h)

        # Define key hints to display - simplified to show only essential hotkeys
        key_hints = [
            ("H", "Help"), ("P", "Stats"), ("Q", "Quit")
        ]

        # Get annotation count for status display
        annotations_list = file_data.get('annotations', []) if isinstance(file_data, dict) else []
        num_annotations = len(annotations_list) if isinstance(annotations_list, list) else 0
        
        # Create frame and filename status text (no annotation count)
        frame_text = f"Frame: {current_index + 1} / {total_files} "
        filename_text = filename

        # Setup initial position and parameters for drawing
        x = 15 # Start 15px from the left edge
        # Calculate vertical baseline for text, centered in the footer
        footer_center_y = disp_h - (footer_height // 2)
        # Scale font based on footer height
        font_scale = max(0.35, min(0.6, footer_height / 80.0))  # Scale between 0.35 and 0.6
        # Estimate text height for baseline calculation (using a capital letter)
        (_, th), baseline = cv2.getTextSize("H", self.font, font_scale, 1)
        footer_baseline_y = footer_center_y + (th // 2) # Adjust centering slightly

        key_padding = max(3, int(5 * font_scale / 0.5))  # Scale padding with font
        inter_key_space = max(5, int(8 * font_scale / 0.5))  # Scale spacing with font
        text_color = self.BASE_COLORS.get('info', (200,200,200)) # Color for ":Description" text
        thickness = 1 # Text thickness

        # Loop through hints and draw them
        for key, desc in key_hints:
            try:
                # Draw the key visualization (e.g., "[H]") and get its right edge X coordinate
                next_x = self._draw_key(overlay, key, x, footer_baseline_y, padding=key_padding, font_scale=font_scale)
                # Position the description text slightly after the key
                desc_x = next_x + 3
                # Draw the description text (e.g., ":Help")
                cv2.putText(overlay, f":{desc}", (desc_x, footer_baseline_y), self.font, font_scale, text_color, thickness, self.line_type)
                # Calculate the width of the description text to find the end X coordinate
                (desc_tw, _), _ = cv2.getTextSize(f":{desc}", self.font, font_scale, thickness)
                # Update the starting X for the next key hint element
                x = desc_x + desc_tw + inter_key_space

                # Optional: Check if the next element would go off-screen and break early
                (next_key_tw, _), _ = cv2.getTextSize("Ctrl+", self.font, font_scale, thickness) # Use a sample wide key text
                if x + next_key_tw + 2 * key_padding > disp_w - 15: # Check against right edge margin
                    break
            except Exception as e:
                # Log error if drawing a specific hint fails
                logger.error(f"Error drawing footer key hint '{key}:{desc}': {e}")
                break # Stop drawing hints if one fails
        
        # Draw frame count and filename on the right side of footer
        try:
            # Calculate positions for frame text and filename
            (filename_w, _), _ = cv2.getTextSize(filename_text, self.font, font_scale, thickness)
            (frame_w, _), _ = cv2.getTextSize(frame_text, self.font, font_scale, thickness)
            
            # Position filename at the far right
            filename_x = disp_w - filename_w - 15  # 15px from right edge
            filename_color = self.filename_color  # Yellow color for filename
            
            # Position frame text just before filename
            frame_x = filename_x - frame_w - 5  # 5px gap between frame and filename
            frame_color = text_color  # Standard text color for frame count
            
            # Draw both texts
            cv2.putText(overlay, frame_text, (frame_x, footer_baseline_y), self.font, font_scale, frame_color, thickness, self.line_type)
            cv2.putText(overlay, filename_text, (filename_x, footer_baseline_y), self.font, font_scale, filename_color, thickness, self.line_type)
        except Exception as e:
            logger.error(f"Error drawing footer frame/filename text: {e}")

    def _draw_center_overlay(self, overlay: np.ndarray, show_help: bool, show_stats: bool, quit_confirm: bool, stats_data: Optional[Dict[str, Any]], model_info: Optional[Dict[str, Any]] = None):
        """Draws the large central overlay box for Help, Stats, or Quit Confirmation."""
        disp_h, disp_w = overlay.shape[:2]
        if disp_h <= 0 or disp_w <= 0: return # Cannot draw if dimensions are invalid

        # Calculate dynamic header and footer heights
        header_height = max(int(disp_h * self.header_height_percent), self.min_header_height)
        header_height = min(header_height, disp_h)
        footer_height = max(int(disp_h * self.footer_height_percent), self.min_footer_height)
        footer_height = min(footer_height, disp_h)

        # Define margins for the overlay box
        box_margin_x = 50
        box_margin_y_top = header_height + 10 # Below header
        box_margin_y_bottom = footer_height + 10 # Above footer

        # Calculate box dimensions
        box_y = box_margin_y_top
        box_h = disp_h - box_margin_y_top - box_margin_y_bottom
        if box_h <= 20: logger.warning("Not enough space to draw center overlay."); return # Not enough vertical space

        box_x = box_margin_x
        box_w = disp_w - 2 * box_margin_x
        if box_w <= 0: logger.warning("Not enough horizontal space to draw center overlay."); return

        # --- Draw Overlay Background ---
        try:
            overlay_box_roi = overlay[box_y : box_y + box_h, box_x : box_x + box_w]
            bg_box_color = self.BASE_COLORS.get('bg_overlay', (30,30,30)) # Darker background
            bg_box = np.full_like(overlay_box_roi, bg_box_color)
            blended_box = cv2.addWeighted(overlay_box_roi, 1.0 - self.overlay_box_alpha, bg_box, self.overlay_box_alpha, 0)
            overlay[box_y : box_y + box_h, box_x : box_x + box_w] = blended_box
        except Exception as e:
            logger.error(f"Error creating overlay background: {e}", exc_info=True)
            return # Stop if background fails

        # --- Draw Overlay Content ---
        line_y = box_y + 40 # Start drawing text below the top edge of the box
        line_height = 25 # Vertical space between lines
        text_start_x = box_x + 20 # Indent text from the left edge of the box
        text_max_y = box_y + box_h - line_height # Maximum Y to prevent text overflow

        # Draw specific content based on active flag
        if quit_confirm:
            self._draw_quit_confirm_text(overlay, box_x, box_y, box_w, box_h)
        elif show_help:
            self._draw_help_text(overlay, text_start_x, line_y, line_height, text_max_y, model_info)
        elif show_stats:
            self._draw_stats_text(overlay, text_start_x, line_y, line_height, text_max_y, stats_data)


    def _draw_quit_confirm_text(self, overlay: np.ndarray, box_x: int, box_y: int, box_w: int, box_h: int):
        """Draws the 'Press Q again to confirm quit' message, centered."""
        quit_text = "Press Q again to confirm quit"
        text_scale = 1.0
        text_thickness = 2
        color = self.BASE_COLORS.get('warning', (0,165,255)) # Orange color

        # Calculate text size to center it
        (qt_w, qt_h), baseline = cv2.getTextSize(quit_text, self.font, text_scale, text_thickness)

        # Calculate centered position (adjusting for text height/baseline)
        qt_x = box_x + (box_w - qt_w) // 2
        qt_y = box_y + (box_h + qt_h) // 2 # Center vertically based on text height

        # Ensure text stays within bounds (add small margin)
        qt_x = max(box_x + 5, qt_x)
        qt_y = max(box_y + qt_h + 5, qt_y) # Ensure baseline is within box
        qt_y = min(box_y + box_h - baseline - 5, qt_y) # Ensure baseline doesn't go below box

        # Draw the text
        cv2.putText(overlay, quit_text, (qt_x, qt_y), self.font, text_scale, color, text_thickness, self.line_type)


    def _draw_help_text(self, overlay: np.ndarray, x: int, y_start: int, line_height: int, y_max: int, model_info: Optional[Dict[str, Any]] = None):
        """Draws the help text content lines within the overlay box."""
        line_y = y_start # Current Y position for drawing
        help_font_scale = self.font_scale_small + 0.05 # Slightly larger small font

        # Helper function to draw a line and increment Y position
        def draw_text(text, scale_modifier=0.0, color=self.BASE_COLORS.get('text'), indent=0):
            nonlocal line_y # Allow modification of outer scope variable
            if line_y > y_max: # Stop if exceeding max Y
                 return True # Indicate overflow
            # Draw the text line
            current_scale = help_font_scale + scale_modifier
            cv2.putText(overlay, text, (x + indent, line_y), self.font, current_scale, color, 1, self.line_type)
            # Move Y position down for the next line
            line_y += line_height
            return False # Indicate success

        # Draw title
        header_color = self.BASE_COLORS.get('header', (255, 255, 0))
        if draw_text("--- HELP ---", 0.1, header_color): return # Stop if overflow
        line_y += 5 # Add extra space after title

        # Define control descriptions
        controls = [
            ("Mouse Drag", "Draw Bounding Box (adds to list)"),
            ("Shift+Click", "Draw Nested BBox (inside existing)"),
            ("[Left]/[Right] / [A]/[D]", "Prev/Next Frame"),
            ("[Up]/[Down] / [W]/[S]", "Jump +/- 10 Frames"),
            ("[PgUp]/[PgDown]", "Jump +/- 100 Frames"),
            ("[Home]/[End]", "First/Last Frame"),
            ('"[", "]"', "Prev/Next ANNOTATED Frame"),
            ("[0]-[9]", "Set Category for LAST Added Annotation"),
            ("[X]", "Delete Selected Annotation"),
            ("[Del]/[Backspace]", "Delete ALL Annotations for Current Frame"),
            ("[B]", "Create Temporary Fixed Bboxes"), # Updated Desc
        ]
        
        # Add inference option if model is available
        if model_info and model_info.get('has_model', False):
            controls.append(("[R]", "Toggle Inference Mode"))
            controls.append(("[T]", "Auto-Inference: ON/OFF"))
            controls.append(("--- In Inference Mode ---", ""))
            controls.append(("[Tab]/[Shift+Tab]", "Navigate Through Inferences"))
            controls.append(("[0]-[9]", "Change Category of Current"))
            controls.append(("[Space]", "Confirm Current Inference"))
            controls.append(("[C]", "Confirm ALL Inferences"))
            controls.append(("[R]", "Cancel/Exit Inference Mode"))
        else:
            # Show T key even without model for consistency
            controls.append(("[T]", "Auto-Inference: ON/OFF (No Model)"))
            
        controls.extend([
            ("[K]", "Auto-Fixed BBOX: ON/OFF"),
            ("[L]", "Auto-Skip: OFF/Frame/Annotation"),
            ("[U]", "Display Mode: Full/No Overlays/Boxes Only"),
            ("[H]", "Toggle Help"),
            ("[P]", "Toggle Stats"),
            ("[Q]", "Quit (twice)"),
            ("[ESC]", "Quit immediately")
        ])

        # Draw each control description line
        for key_desc, action_desc in controls:
             # Format with padding for alignment
             if draw_text(f"{key_desc:<25} {action_desc}"):
                 break # Stop if overflow

    def _draw_stats_text(self, overlay: np.ndarray, x: int, y_start: int, line_height: int, y_max: int, stats_data: Optional[Dict[str, Any]]):
        """Draws the statistics text content within the overlay box."""
        line_y = y_start # Current Y position
        stats_font_scale = self.font_scale_small + 0.05 # Slightly larger small font

        # Helper function similar to help text drawing
        def draw_text(text, scale_modifier=0.0, color=self.BASE_COLORS.get('text'), indent=0):
            nonlocal line_y
            if line_y > y_max: return True
            current_scale = stats_font_scale + scale_modifier
            cv2.putText(overlay, text, (x + indent, line_y), self.font, current_scale, color, 1, self.line_type)
            line_y += line_height
            return False

        # Draw title
        header_color = self.BASE_COLORS.get('header', (255, 255, 0))
        if draw_text("--- STATISTICS ---", 0.1, header_color): return
        line_y += 5

        # Handle case where stats data might be unavailable
        if stats_data is None:
            error_color = self.BASE_COLORS.get('error', (0, 0, 255))
            draw_text("Stats data unavailable.", color=error_color)
            return

        # Extract stats safely using .get() with defaults
        total_files_store = stats_data.get('total_files_in_store', 0)
        total_annotated_files = stats_data.get('total_files_with_any_annotation', 0)
        total_annotations = stats_data.get('total_annotations', 0)
        total_files_bbox = stats_data.get('total_files_with_bbox', 0)
        category_counts = stats_data.get('category_counts', {})
        # Get subcategory counts (which should now be from within annotations)
        subcategory_counts = stats_data.get('subcategory_counts', {})

        # Prepare lines for display
        stat_lines = [
            f"Total Files Found (in dir): {stats_data.get('total_files_actual', 'N/A')}", # Use actual count from state if available
            f"Files in JSON Store: {total_files_store}",
            f"Files w/ Any Annotation: {total_annotated_files}",
            f"Total Annotations (all files): {total_annotations}",
            f"Files w/ BBox: {total_files_bbox}",
            "", # Blank line separator
            "--- Category Counts (All Annotations) ---"
        ]
        # Add category counts, sorted by name
        stat_lines.extend([f"  {key}: {count}" for key, count in sorted(category_counts.items())])

        stat_lines.append("") # Blank line separator
        stat_lines.append("--- Subcategory Counts (Within Annotations) ---") # Updated title
        # Add subcategory counts, sorted by name
        if subcategory_counts:
             stat_lines.extend([f"  {key}: {count}" for key, count in sorted(subcategory_counts.items())])
        else:
            stat_lines.append("  (None Found)")


        # Draw each stat line
        for stat_line in stat_lines:
             if draw_text(stat_line): # Stop if overflowing
                 break