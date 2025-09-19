# Complete file: src/bomia/annotation/annotator.py
# Refatorado para padrões Python e com correção para 'Q' duas vezes.

import cv2
import numpy as np
import logging
import re
import os
import time
from typing import Dict, Any, Optional, Tuple, List
from pathlib import Path

# Import refactored components and settings
try:
    from config import config # Use global config instance
    from .definitions import CATEGORIES, SUBCATEGORIES
    from .state import AnnotationState
    # Import store constants directly if needed
    from .store import AnnotationStore, ANNOTATION_SOURCE_HUMAN, ANNOTATION_SOURCE_INFERENCE
    # Import Renderer para acessar cores de classe
    from .renderer import AnnotationRenderer # <<< IMPORTANTE: Precisa importar a classe
    from .key_handler import AnnotatorKeyHandler
except ImportError as e:
    # Fallbacks (mantidos para robustez)
    print(f"Error importing annotation components: {e}")
    # Define dummy classes for type hinting if imports fail temporarily
    class AnnotationState: pass
    class AnnotationStore: pass
    class AnnotationRenderer:
        BASE_COLORS = {'drawing': (0, 255, 0)} # Dummy fallback
    class AnnotatorKeyHandler: pass
    # Define dummy fallbacks for constants/config
    config = None
    CATEGORIES = {}
    SUBCATEGORIES = {}
    ANNOTATION_SOURCE_HUMAN = "human"
    ANNOTATION_SOURCE_INFERENCE = "inference"
    # Basic logging config if main one failed
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.error("Failed to import dependencies in annotator.")
else:
     # Logger obtained successfully from imports
     logger = logging.getLogger(__name__)


class UnifiedAnnotator:
    """
    Orchestrates the annotation process including image loading, state management,
    user interactions (mouse, keyboard), data persistence via AnnotationStore (new format),
    and UI rendering via AnnotationRenderer. Handles multiple annotations per frame.
    """
    FILENAME_PATTERN = re.compile(r"(\d+)\.(jpg|jpeg|png)$", re.IGNORECASE)

    def __init__(
        self,
        state: AnnotationState,
        store: AnnotationStore,
        renderer: AnnotationRenderer, # Instance passed in
        key_handler: AnnotatorKeyHandler,
        images_dir: Path,
        window_name: str = 'Annotator',
        model_path: Optional[str] = None,
        confidence_threshold: float = 0.35,
        category_filter: Optional[str] = None,
        category_filter_id: Optional[int] = None
    ):
        """ Initializes the annotator with injected dependencies. """
        if not config:
            # This should ideally not happen if config.py handles errors, but check again.
            raise RuntimeError("Application settings could not be loaded.")

        self.state = state
        self.store = store
        self.renderer = renderer # Store the renderer instance
        self.key_handler = key_handler
        self.images_dir = images_dir
        self.window_name = window_name
        
        # Category filter
        self.category_filter = category_filter
        self.category_filter_id = category_filter_id
        
        # Update window name if filter is active
        if self.category_filter:
            self.window_name = f"{self.window_name} [Filter: {self.category_filter}]"
        
        # Inference setup
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self.model = None
        self.has_model = False
        
        # Temporary inference annotations
        self.temporary_inferences: List[Dict[str, Any]] = []
        self.current_inference_index = -1  # -1 means no selection
        self.last_loaded_index = -1  # Track last loaded frame index
        
        # Auto-skip timing
        self.auto_skip_start_time = None
        
        # Try to load model if provided
        if model_path:
            self._load_model()

        # Image cache - store original and base display image for current index
        self.img_original: Optional[np.ndarray] = None
        self.img_display_base: Optional[np.ndarray] = None

        # Load and sort image files
        self.image_files: List[str] = self._load_and_sort_filenames()
        self.state.total_files = len(self.image_files)

        # Ensure the key_handler instance receives the filenames list if it needs it
        if hasattr(self.key_handler, 'all_filenames'):
             self.key_handler.all_filenames = self.image_files
        else:
             # This might be normal if the KeyHandler implementation doesn't need the full list
             logger.debug("KeyHandler instance does not have 'all_filenames' attribute to set.")
             
        # Set category filter in key handler
        if hasattr(self.key_handler, 'set_category_filter'):
            self.key_handler.set_category_filter(self.category_filter, self.category_filter_id)
             
        # Set annotator reference in key handler for inference
        if hasattr(self.key_handler, 'set_annotator'):
            self.key_handler.set_annotator(self)
            
        # Enable inference handler if model is loaded
        if self.has_model and hasattr(self.key_handler, 'set_model_available'):
            self.key_handler.set_model_available(True)

        logger.info(f"Annotator initialized. Found {self.state.total_files} images in {self.images_dir}")
        if self.has_model:
            project_name = config.get("project.name", "unknown")
            logger.info(f"Model loaded: {self.model_path} (Project: {project_name})")
        else:
            logger.info("No model loaded - inference not available")

    def _load_and_sort_filenames(self) -> List[str]:
        """
        Loads and sorts image filenames from the specified directory.
        Sorting is done purely by timestamp, ensuring chronological order
        regardless of round number.
        """
        if not self.images_dir.is_dir():
            logger.error(f"Images directory not found or is not a directory: {self.images_dir}")
            return []

        try:
            # Filter for common image extensions, case-insensitive
            extensions = {'.png', '.jpg', '.jpeg'}
            all_files = [f.name for f in self.images_dir.iterdir() if f.is_file() and f.suffix.lower() in extensions]
        except OSError as e:
             logger.error(f"Error reading image directory {self.images_dir}: {e}")
             return []

        def sort_key(filename):
            match = self.FILENAME_PATTERN.match(filename)
            if match:
                try:
                    # Sort solely by timestamp (1st group)
                    timestamp = int(match.group(1))
                    return timestamp
                except (ValueError, IndexError):
                    # Fallback for filenames that match but have invalid numbers
                    logger.warning(f"Could not parse timestamp in filename for sorting: {filename}")
                    return float('inf') # Fallback sorting puts them at the end
            else:
                # Fallback for filenames that don't match the pattern
                # logger.debug(f"Filename did not match pattern for sorting: {filename}")
                return float('inf') # Fallback sorting puts them at the end

        sorted_files = sorted(all_files, key=sort_key)

        if not sorted_files:
            logger.warning(f"No valid image files (.png, .jpg, .jpeg) found in {self.images_dir}")
        else:
            logger.debug(f"Found and sorted {len(sorted_files)} image files by timestamp.")
        return sorted_files

    def _load_and_prepare_image(self) -> bool:
        """
        Loads the original image for the current index, creates the base display image (resized),
        and updates the AnnotationState.

        Returns:
            bool: True if image loaded and prepared successfully, False otherwise.
        """
        # Check if we're actually on a different frame
        is_frame_change = self.state.current_index != self.last_loaded_index
        
        # Clear temporary inferences only when actually changing frames
        if is_frame_change and self.temporary_inferences:
            self.clear_temporary_inferences()
        
        # Skip loading if we're on the same frame and already have the image
        if not is_frame_change and self.img_original is not None:
            logger.debug(f"Skipping reload of frame {self.state.current_index} - already loaded")
            return True
            
        if not (0 <= self.state.current_index < self.state.total_files):
            logger.error(f"Cannot load image: index {self.state.current_index} out of bounds (Total: {self.state.total_files}).")
            self.img_original = None
            self.img_display_base = None
            self.state.update_image_info(None, None, None, self.state.current_index, self.state.total_files)
            return False

        filename = self.image_files[self.state.current_index]
        image_path = self.images_dir / filename
        logger.debug(f"Loading image: {image_path}")

        # Load the original image using OpenCV
        self.img_original = cv2.imread(str(image_path)) # cv2.imread needs string path

        if self.img_original is None:
            logger.error(f"Failed to load image: {image_path}. Skipping.")
            self.img_display_base = None
            self.state.update_image_info(None, None, filename, self.state.current_index, self.state.total_files)
            return False # Indicate failure

        # Prepare display image (resized)
        orig_h, orig_w = self.img_original.shape[:2]
        if orig_h <= 0 or orig_w <= 0: # Check dimensions *after* loading seems safer
            logger.error(f"Image {filename} has invalid dimensions ({orig_w}x{orig_h}). Skipping.")
            self.img_original = None
            self.img_display_base = None
            self.state.update_image_info(None, None, filename, self.state.current_index, self.state.total_files)
            return False

        # --- Determine display size ---
        # Using target size based on config or sensible defaults
        target_w = 1280 # Default target width
        target_h = 720  # Default target height
        if config: # Safely get from config if available
             try:
                 # Example: use percentage of a common large screen size
                 # Use larger window for better image quality display
                 w_pct = config.get_float("annotation.window_width_percent", 0.9)
                 h_pct = config.get_float("annotation.window_height_percent", 0.9)
                 target_w = int(w_pct * 1600) if 0.1 < w_pct <= 1.0 else 1280
                 target_h = int(h_pct * 900) if 0.1 < h_pct <= 1.0 else 720
             except Exception as e:
                 logger.warning(f"Could not read window size percentages from config: {e}. Using defaults.")
                 target_w = 1280
                 target_h = 720

        # Calculate scale to fit within target, without upscaling (max scale = 1.0)
        scale = min(target_w / orig_w, target_h / orig_h, 1.0)
        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)

        if new_w <= 0 or new_h <= 0:
            logger.error(f"Calculated invalid display dimensions ({new_w}x{new_h}) for {filename}. Skipping resize.")
            # Option: Use original image directly? Might be too large.
            # Let's stick to failing the load for this frame for safety.
            self.img_original = None
            self.img_display_base = None
            self.state.update_image_info((orig_h, orig_w), None, filename, self.state.current_index, self.state.total_files)
            return False

        try:
            # Resize image for display with best quality without artifacts
            if scale < 1.0:
                # Downscaling - use INTER_AREA for best quality
                interpolation = cv2.INTER_AREA
            else:
                # Upscaling - use INTER_LINEAR for balanced quality/performance
                interpolation = cv2.INTER_LINEAR

            self.img_display_base = cv2.resize(self.img_original, (new_w, new_h), interpolation=interpolation)
            # Update state with new image info
            self.state.update_image_info((orig_h, orig_w), (new_h, new_w), filename, self.state.current_index, self.state.total_files)
            logger.debug(f"Image {filename} loaded. Original: {orig_w}x{orig_h}, Display: {new_w}x{new_h}")
            # Update last loaded index
            self.last_loaded_index = self.state.current_index
            
            # Auto-select first annotation when navigating to a frame with existing annotations
            if is_frame_change:
                file_data = self.store.get_annotation_data_for_file(filename)
                if file_data and file_data.get('annotations') and len(file_data['annotations']) > 0:
                    # Reset selection to first annotation when changing frames
                    self.state.current_annotation_index = 0
                    logger.debug(f"Auto-selected first annotation in frame {filename}")
                else:
                    # No annotations in this frame, reset selection
                    self.state.current_annotation_index = -1
            
            # Auto-inference: Run inference automatically if enabled and model available
            if is_frame_change and self.state.auto_inference and self.has_model:
                logger.debug(f"Auto-inference: Running inference on {filename}")
                try:
                    success = self.run_inference_on_current_frame()
                    # Enable inference navigation if inferences were found
                    if success and self.temporary_inferences and hasattr(self.key_handler, 'enable_inference_navigation'):
                        self.key_handler.enable_inference_navigation(True)
                        logger.debug("Auto-inference: Enabled inference navigation handlers")
                except Exception as e:
                    logger.error(f"Auto-inference failed on {filename}: {e}", exc_info=True)
            
            # Auto-fixed bbox: Create fixed bboxes automatically if enabled
            elif is_frame_change and self.state.auto_fixed_bbox:
                logger.debug(f"Auto-fixed bbox: Creating fixed bboxes for {filename}")
                try:
                    success = self.create_fixed_bboxes_as_temporary()
                    if success:
                        logger.debug("Auto-fixed bbox: Created temporary fixed bboxes")
                except Exception as e:
                    logger.error(f"Auto-fixed bbox failed on {filename}: {e}", exc_info=True)
            
            return True # Indicate success
        except Exception as e:
            logger.error(f"Error resizing image {filename}: {e}", exc_info=True)
            self.img_original = None
            self.img_display_base = None
            self.state.update_image_info((orig_h, orig_w), None, filename, self.state.current_index, self.state.total_files)
            return False

    def _mouse_callback(self, event, x, y, flags, param):
        """Handles mouse events for drawing bounding boxes."""
        # Ignore events if display image or its shape isn't ready
        if self.img_display_base is None or self.state.img_display_shape is None:
            # logger.debug("Mouse callback ignored: Display base image/shape not ready.")
            return

        disp_h, disp_w = self.state.img_display_shape
        if disp_h <= 0 or disp_w <= 0:
             logger.warning("Mouse callback ignored: Invalid display shape.")
             return

        # Clamp coordinates to be within display bounds
        x = max(0, min(x, disp_w - 1))
        y = max(0, min(y, disp_h - 1))
        self.state.current_mouse_pos = (x, y) # Store current position in state

        # --- Left Mouse Button Down: Check for bbox selection first, then start drawing ---
        if event == cv2.EVENT_LBUTTONDOWN:
            # Disable interaction if an overlay (Help, Stats, Quit) is active
            if self.state.show_help or self.state.show_stats or self.state.quit_confirm:
                logger.debug("Mouse interaction disabled while overlay is active.")
                return
            
            # First, check if click is on an existing bbox for selection
            clicked_bbox_index = self._find_clicked_bbox(x, y)
            if clicked_bbox_index >= 0:
                # Click hit a permanent annotation - select it
                self.state.current_annotation_index = clicked_bbox_index
                logger.debug(f"Selected permanent annotation {clicked_bbox_index} at click ({x}, {y})")
                return  # Don't start drawing
            elif clicked_bbox_index == -2:
                # Click hit a temporary inference bbox - already handled in _find_clicked_bbox
                logger.debug(f"Selected temporary inference at click ({x}, {y})")
                return  # Don't start drawing
            
            # No bbox clicked - start drawing a new one
            self.state.drawing = True
            self.state.start_point = (x, y)
            logger.debug(f"Mouse down at ({x}, {y}). Drawing started.")

        # --- Mouse Move: Draw Temporary Box Preview ---
        elif event == cv2.EVENT_MOUSEMOVE:
            if self.state.drawing and self.state.start_point:
                # Ensure base image exists before copying
                if self.img_display_base is None:
                    return # Should not happen if drawing is true, but safety check
                img_preview = self.img_display_base.copy()

                # Get current data for rendering existing boxes on the preview
                current_file_data = {}
                if self.state.current_filename:
                    current_file_data = self.store.get_annotation_data_for_file(self.state.current_filename)

                # Prepare model info for rendering
                model_info = {
                    'has_model': self.has_model,
                    'project_name': config.get("project.name", "unknown") if self.has_model else None
                }
                
                # Render existing elements onto preview base *first*
                # This ensures header/footer/saved boxes are behind the drag rectangle
                rendered_preview_base = self.renderer.draw_frame(
                     img_preview, # Pass the clean base image copy
                     self.state.img_original_shape if self.state.img_original_shape else (0,0),
                     current_file_data, # Pass data with existing annotations
                     self.state.current_filename if self.state.current_filename else "N/A",
                     self.state.current_index, self.state.total_files,
                     self.state.show_help, self.state.show_stats, self.state.quit_confirm,
                     None, # No need for full stats calculation in mouse move preview
                     model_info, # Model status information
                     None, # No inference info for preview
                     self.state.auto_inference, # Auto-inference state
                     self.state.auto_fixed_bbox, # Auto-fixed bbox state
                     self.state.auto_skip, # Auto-skip state
                     self.state.display_mode if hasattr(self.state, 'display_mode') else 0 # Display mode
                 )

                # Draw the temporary rectangle being dragged *on top*
                # Access BASE_COLORS via the imported AnnotationRenderer class
                draw_color = AnnotationRenderer.BASE_COLORS.get('drawing', (0, 255, 0)) # Green default
                cv2.rectangle(rendered_preview_base, self.state.start_point, self.state.current_mouse_pos, draw_color, 2)

                # Show the combined preview immediately
                cv2.imshow(self.window_name, rendered_preview_base)

        # --- Left Mouse Button Up: Finalize Drawing - Add Annotation ---
        elif event == cv2.EVENT_LBUTTONUP:
            if not self.state.drawing or not self.state.start_point:
                # Ensure drawing flag is reset even if something went wrong
                if self.state.drawing:
                    self.state.reset_drawing()
                return

            self.state.drawing = False # Finish drawing state
            end_point = (x, y)
            logger.debug(f"Mouse up at ({x}, {y}). Drawing finished.")

            # Prevent saving zero-size box (single click)
            if self.state.start_point == end_point:
                logger.info("Box has zero size (single click?), annotation not added.")
                self.state.reset_drawing()
                return # No redraw needed here, main loop will handle it shortly

            # --- Validate required info for scaling and saving ---
            if self.img_original is None or self.state.img_original_shape is None or self.state.img_display_shape is None:
                logger.error("Cannot add annotation: Original image or shape info missing.")
                self.state.reset_drawing()
                return

            orig_h, orig_w = self.state.img_original_shape
            disp_h, disp_w = self.state.img_display_shape

            if orig_h <= 0 or orig_w <= 0 or disp_h <= 0 or disp_w <= 0:
                logger.error("Cannot add annotation: Invalid image dimensions in state.")
                self.state.reset_drawing()
                return

            # --- Scale coordinates back to original image size ---
            try:
                scale_x = orig_w / disp_w
                scale_y = orig_h / disp_h

                # Calculate original coordinates, ensuring x1 < x2 and y1 < y2
                x1_orig = int(min(self.state.start_point[0], end_point[0]) * scale_x)
                y1_orig = int(min(self.state.start_point[1], end_point[1]) * scale_y)
                x2_orig = int(max(self.state.start_point[0], end_point[0]) * scale_x)
                y2_orig = int(max(self.state.start_point[1], end_point[1]) * scale_y)

                # Clamp coordinates to be within original image bounds
                x1_orig = max(0, min(x1_orig, orig_w - 1))
                y1_orig = max(0, min(y1_orig, orig_h - 1))
                x2_orig = max(0, min(x2_orig, orig_w - 1))
                y2_orig = max(0, min(y2_orig, orig_h - 1))

            except ZeroDivisionError:
                 logger.error("Cannot scale bbox: Display dimensions are zero.")
                 self.state.reset_drawing()
                 return
            except Exception as e:
                 logger.error(f"Error scaling bbox coordinates: {e}")
                 self.state.reset_drawing()
                 return

            # --- Bounding Box Size Validation ---
            bbox_width = x2_orig - x1_orig
            bbox_height = y2_orig - y1_orig
            min_dimension = 10 # Minimum required width OR height in pixels (Consider making configurable)

            if bbox_width < min_dimension or bbox_height < min_dimension:
                size_info=f"Size ({bbox_width}x{bbox_height})"
                warning_msg=f"BBox rejected: {size_info} <= {min_dimension}px."
                logger.warning(warning_msg)
                print(f"Info: BBox too small ({bbox_width}x{bbox_height} px). Min >{min_dimension}px. Not saved.")
                self.state.reset_drawing()
                return # Stop processing, do not save

            # --- Add the annotation using the AnnotationStore ---
            current_filename = self.state.current_filename
            if current_filename:
                try:
                    bbox_to_save = (x1_orig, y1_orig, x2_orig, y2_orig)
                    # Resolve path to ensure it's absolute before passing to store
                    # Store will handle making it relative if possible
                    original_path = str((self.images_dir / current_filename).resolve())

                    # Get category from last annotation in list (or None) to pre-fill
                    current_file_data = self.store.get_annotation_data_for_file(current_filename)
                    last_category_id = None
                    last_category_name = None
                    if current_file_data and isinstance(current_file_data.get("annotations"), list):
                        existing_annotations = current_file_data["annotations"]
                        if existing_annotations: # Check if list is not empty
                            last_ann = existing_annotations[-1]
                            last_category_id = last_ann.get('category_id')
                            last_category_name = last_ann.get('category_name')

                    # If category filter is active, use the filter category
                    if self.category_filter_id is not None:
                        category_id = self.category_filter_id
                        category_name = self.category_filter
                    else:
                        category_id = last_category_id
                        category_name = last_category_name

                    # Inform user
                    log_msg = f"Adding BBox {bbox_to_save} for {current_filename}."
                    if self.category_filter:
                        user_msg_suffix = f" Category: {category_name} (filter active)"
                    else:
                        user_msg_suffix = " Category needs to be set (0-5)." if category_id is None else f" Initial category: {category_name}"
                    print(f"Info: Adding BBox for {current_filename}.{user_msg_suffix}")
                    logger.info(log_msg + user_msg_suffix)

                    # Call store to add the new annotation entry to the list
                    self.store.add_annotation(
                        filename=current_filename,
                        bbox=bbox_to_save,
                        category_id=category_id,
                        category_name=category_name,
                        original_path=original_path,
                        annotation_source=ANNOTATION_SOURCE_HUMAN # Drawn by human
                    )
                    
                    # Store the bbox and category in state for repeat functionality
                    self.state.last_drawn_bbox = bbox_to_save
                    self.state.last_drawn_category_id = category_id
                    self.state.last_drawn_category_name = category_name
                    logger.debug(f"Stored last drawn annotation: bbox={bbox_to_save}, category_id={category_id}, category_name={category_name}")
                    
                    # Auto-select the newly created annotation
                    file_data = self.store.get_annotation_data_for_file(current_filename)
                    if file_data and file_data.get('annotations'):
                        # Set selection to the last annotation (which is the one we just added)
                        self.state.current_annotation_index = len(file_data['annotations']) - 1
                        logger.debug(f"Auto-selected newly created annotation at index {self.state.current_annotation_index}")
                    
                    logger.info(f"Added annotation entry to store for {current_filename}")
                    
                    # Trigger auto-skip after successful bbox creation
                    logger.info("About to call _trigger_auto_skip()")
                    self._trigger_auto_skip()

                except Exception as e:
                    logger.error(f"Error adding annotation via store for {current_filename}: {e}", exc_info=True)
                    print(f"Error adding annotation for {current_filename}. Check logs.")
            else:
                logger.warning("Cannot add annotation: Current filename is not set in state.")

            # Reset start point and drawing flag after processing
            self.state.reset_drawing()
            # No redraw needed here, main loop will redraw the final state

    def _find_clicked_bbox(self, click_x: int, click_y: int) -> int:
        """
        Find which bbox (if any) contains the click point.
        Returns the index of the clicked bbox, or -1 if no bbox was clicked.
        For temporary inferences, updates current_inference_index and enables navigation.
        Click coordinates are in display space.
        """
        # Get coordinate conversion factors
        if not self.state.img_original_shape or not self.state.img_display_shape:
            return -1
            
        orig_h, orig_w = self.state.img_original_shape
        disp_h, disp_w = self.state.img_display_shape
        
        if orig_h <= 0 or orig_w <= 0 or disp_h <= 0 or disp_w <= 0:
            return -1
            
        scale_x = disp_w / orig_w
        scale_y = disp_h / orig_h
        
        # First, check temporary inference bboxes (highest priority)
        if self.temporary_inferences:
            for i in reversed(range(len(self.temporary_inferences))):
                temp_inference = self.temporary_inferences[i]
                if not isinstance(temp_inference, dict):
                    continue
                    
                bbox = temp_inference.get('bbox')
                if not bbox or len(bbox) != 4:
                    continue
                    
                try:
                    # Get original coordinates
                    x1_orig, y1_orig, x2_orig, y2_orig = map(float, bbox)
                    
                    # Convert to display coordinates
                    x1_disp = int(min(x1_orig, x2_orig) * scale_x)
                    y1_disp = int(min(y1_orig, y2_orig) * scale_y)
                    x2_disp = int(max(x1_orig, x2_orig) * scale_x)
                    y2_disp = int(max(y1_orig, y2_orig) * scale_y)
                    
                    # Check if click point is inside this temporary bbox
                    if x1_disp <= click_x <= x2_disp and y1_disp <= click_y <= y2_disp:
                        logger.debug(f"Click ({click_x}, {click_y}) hit temporary inference {i}: [{x1_disp}, {y1_disp}, {x2_disp}, {y2_disp}]")
                        # Update current inference index to select this temporary bbox
                        self.current_inference_index = i
                        # Clear permanent bbox selection when selecting temporary
                        self.state.current_annotation_index = -1
                        # Enable navigation handlers if not already enabled
                        if hasattr(self.key_handler, 'enable_inference_navigation'):
                            self.key_handler.enable_inference_navigation(True)
                        print(f"Selected temporary bbox {i + 1}/{len(self.temporary_inferences)}: {temp_inference.get('category_name', 'Unknown')}")
                        return -2  # Special return value to indicate temporary bbox was selected
                        
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid temporary inference bbox coordinates at {i}: {bbox}")
                    continue
        
        # Then check permanent annotations from store
        if not self.state.current_filename:
            return -1
            
        file_data = self.store.get_annotation_data_for_file(self.state.current_filename)
        if not file_data or not file_data.get('annotations'):
            return -1
            
        annotations_list = file_data.get('annotations', [])
        if not isinstance(annotations_list, list) or len(annotations_list) == 0:
            return -1
        
        # Check each permanent bbox from last to first (top-to-bottom in drawing order)
        # This way, if bboxes overlap, we select the most recently drawn one
        for i in reversed(range(len(annotations_list))):
            annotation = annotations_list[i]
            if not isinstance(annotation, dict):
                continue
                
            bbox = annotation.get('bbox')
            if not bbox or len(bbox) != 4:
                continue
                
            try:
                # Get original coordinates
                x1_orig, y1_orig, x2_orig, y2_orig = map(float, bbox)
                
                # Convert to display coordinates
                x1_disp = int(min(x1_orig, x2_orig) * scale_x)
                y1_disp = int(min(y1_orig, y2_orig) * scale_y)
                x2_disp = int(max(x1_orig, x2_orig) * scale_x)
                y2_disp = int(max(y1_orig, y2_orig) * scale_y)
                
                # Check if click point is inside this bbox
                if x1_disp <= click_x <= x2_disp and y1_disp <= click_y <= y2_disp:
                    logger.debug(f"Click ({click_x}, {click_y}) hit permanent annotation {i}: [{x1_disp}, {y1_disp}, {x2_disp}, {y2_disp}]")
                    # Clear temporary bbox selection when selecting permanent
                    if self.temporary_inferences:
                        self.current_inference_index = -1
                        # Disable inference navigation when switching to permanent
                        if hasattr(self.key_handler, 'enable_inference_navigation'):
                            self.key_handler.enable_inference_navigation(False)
                        print(f"Selected permanent annotation {i + 1}")
                    return i
                    
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid bbox coordinates in annotation {i}: {bbox}")
                continue
                
        # No bbox was clicked
        return -1

    def _load_model(self):
        """Load YOLO model for inference."""
        try:
            from ultralytics import YOLO
            logger.info(f"Loading model from: {self.model_path}")
            self.model = YOLO(self.model_path)
            self.has_model = True
            logger.info(f"Model loaded successfully. Classes: {list(self.model.names.values())}")
            
            # Notify key handler that model is available
            if hasattr(self.key_handler, 'set_model_available'):
                self.key_handler.set_model_available(True)
                
        except Exception as e:
            logger.error(f"Failed to load model {self.model_path}: {e}")
            self.model = None
            self.has_model = False

    def run_inference_on_current_frame(self):
        """Run inference on the current frame and store results as temporary annotations."""
        if not self.has_model or self.model is None:
            logger.warning("Cannot run inference: No model loaded")
            print("No model available for inference")
            return False
            
        if self.img_original is None or not self.state.current_filename:
            logger.warning("Cannot run inference: No image loaded")
            print("No image loaded for inference")
            return False
            
        try:
            logger.info(f"Running inference on {self.state.current_filename}")
            
            # Clear previous temporary inferences
            self.temporary_inferences.clear()
            self.current_inference_index = -1
            
            # Run inference
            results = self.model(self.img_original, conf=self.confidence_threshold, verbose=False)
            
            if not results or len(results) == 0:
                print("No detections found")
                return True
                
            result = results[0]  # Single image inference
            
            if result.boxes is None or len(result.boxes) == 0:
                print("No detections found")
                return True
                
            # Get existing annotations for overlap checking
            existing_annotations = self.store.get_annotation_data_for_file(self.state.current_filename).get('annotations', [])
            existing_boxes = []
            for ann in existing_annotations:
                bbox = ann.get('bbox')
                if bbox and len(bbox) == 4:
                    existing_boxes.append(tuple(bbox))
                    
            # Map model results to temporary annotations
            from .definitions import get_categories
            project_categories = get_categories()
            
            skipped_overlaps = 0
            
            for box in result.boxes:
                # Get prediction info
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                # Convert to Python int to avoid JSON serialization issues
                x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy())
                
                # Get class name from model
                pred_class_name = self.model.names.get(cls_id, f"Class_{cls_id}")
                
                # Map to project category
                category_id = None
                category_name = None
                
                # Smart mapping for unknown_X classes from broken training
                if pred_class_name.startswith("unknown_"):
                    # Extract the number and use it as category ID
                    try:
                        extracted_id = pred_class_name.split("_")[1]
                        if extracted_id in project_categories:
                            category_id = extracted_id
                            category_name = project_categories[extracted_id]
                    except (IndexError, KeyError):
                        pass
                elif pred_class_name.lower() == "maquina":
                    # Map "maquina" to "trator" for carbonizacao
                    for cat_id, cat_name in project_categories.items():
                        if cat_name.lower() == "trator":
                            category_id = cat_id
                            category_name = cat_name
                            break
                else:
                    # Direct mapping
                    for cat_id, cat_name in project_categories.items():
                        if cat_name.lower() == pred_class_name.lower():
                            category_id = cat_id
                            category_name = cat_name
                            break
                        
                if category_id is None:
                    logger.warning(f"Could not map predicted class '{pred_class_name}' to project category")
                    continue
                    
                # If category filter is active, skip detections that don't match
                if self.category_filter_id is not None and category_id != self.category_filter_id:
                    logger.debug(f"Skipping detection '{category_name}' - doesn't match filter '{self.category_filter}'")
                    continue
                    
                # Check if this box overlaps with existing annotations
                inference_box = (x1, y1, x2, y2)
                is_duplicate = False
                for existing_box in existing_boxes:
                    if self._boxes_overlap(inference_box, existing_box):
                        is_duplicate = True
                        skipped_overlaps += 1
                        logger.debug(f"Skipping inference box {inference_box} - overlaps with existing {existing_box}")
                        break
                        
                if is_duplicate:
                    continue
                    
                # Store as temporary inference annotation
                temp_annotation = {
                    'bbox': inference_box,
                    'category_id': category_id,
                    'category_name': category_name,
                    'confidence': conf,
                    'annotation_source': ANNOTATION_SOURCE_INFERENCE
                }
                self.temporary_inferences.append(temp_annotation)
                
            # Sort inferences by spatial position (top-left to bottom-right)
            if self.temporary_inferences:
                # Sort by y1 first, then x1 (top to bottom, left to right)
                self.temporary_inferences.sort(key=lambda inf: (inf['bbox'][1], inf['bbox'][0]))
                self.current_inference_index = 0
                msg = f"Found {len(self.temporary_inferences)} new detections"
                if self.category_filter:
                    msg += f" ({self.category_filter} only)"
                if skipped_overlaps > 0:
                    msg += f" (skipped {skipped_overlaps} overlapping)"
                msg += ". Tab: navigate, Space: confirm current, C: confirm all, R: cancel"
                print(msg)
            else:
                if self.category_filter:
                    print(f"No {self.category_filter} detections found")
                elif skipped_overlaps > 0:
                    print(f"No new detections found (all {skipped_overlaps} overlapped with existing)")
                else:
                    print("No valid detections found")
                
            logger.info(f"Found {len(self.temporary_inferences)} temporary inference annotations for {self.state.current_filename}")
            return True
            
        except Exception as e:
            logger.error(f"Error during inference: {e}", exc_info=True)
            print(f"Inference failed: {e}")
            return False
            
    def _boxes_overlap(self, box1: tuple, box2: tuple, iou_threshold: float = 0.5) -> bool:
        """Check if two boxes overlap significantly using IoU."""
        x1_1, y1_1, x2_1, y2_1 = box1
        x1_2, y1_2, x2_2, y2_2 = box2
        
        # Calculate intersection
        x1_i = max(x1_1, x1_2)
        y1_i = max(y1_1, y1_2)
        x2_i = min(x2_1, x2_2)
        y2_i = min(y2_1, y2_2)
        
        if x2_i < x1_i or y2_i < y1_i:
            return False  # No intersection
            
        # Calculate areas
        intersection = (x2_i - x1_i) * (y2_i - y1_i)
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        union = area1 + area2 - intersection
        
        # Calculate IoU
        iou = intersection / union if union > 0 else 0
        return iou > iou_threshold
            
    def navigate_inference(self, direction: int):
        """Navigate through temporary inference annotations. direction: 1 for next, -1 for previous."""
        if not self.temporary_inferences:
            return
            
        num_inferences = len(self.temporary_inferences)
        if direction > 0:  # Next
            self.current_inference_index = (self.current_inference_index + 1) % num_inferences
        else:  # Previous
            self.current_inference_index = (self.current_inference_index - 1) % num_inferences
            
        print(f"Inference {self.current_inference_index + 1}/{num_inferences} selected")
        
    def confirm_current_inference(self):
        """Confirm and save the currently selected inference annotation."""
        if not self.temporary_inferences or self.current_inference_index < 0:
            print("No inference selected")
            return False
            
        if self.current_inference_index >= len(self.temporary_inferences):
            print("Invalid inference index")
            return False
            
        # Get the selected inference
        inference = self.temporary_inferences[self.current_inference_index]
        
        # Save it using the store
        image_path = self.images_dir / self.state.current_filename
        self.store.add_annotation(
            filename=self.state.current_filename,
            bbox=inference['bbox'],
            category_id=inference['category_id'],
            category_name=inference['category_name'],
            original_path=str(image_path.resolve()),
            annotation_source=inference['annotation_source']
        )
        
        # Remove from temporary list
        self.temporary_inferences.pop(self.current_inference_index)
        
        # Adjust index if needed
        if self.temporary_inferences:
            self.current_inference_index = min(self.current_inference_index, len(self.temporary_inferences) - 1)
        else:
            self.current_inference_index = -1
            
        print(f"Confirmed inference: {inference['category_name']} (conf: {inference['confidence']:.2f})")
        
        # Trigger auto-skip after successful bbox creation
        self._trigger_auto_skip()
            
        return True
        
    def confirm_all_inferences(self):
        """Confirm and save all temporary inference annotations."""
        if not self.temporary_inferences:
            print("No inferences to confirm")
            return False
            
        image_path = self.images_dir / self.state.current_filename
        confirmed_count = 0
        
        for inference in self.temporary_inferences:
            self.store.add_annotation(
                filename=self.state.current_filename,
                bbox=inference['bbox'],
                category_id=inference['category_id'],
                category_name=inference['category_name'],
                original_path=str(image_path.resolve()),
                annotation_source=inference['annotation_source']
            )
            confirmed_count += 1
            
        # Clear temporary inferences
        self.temporary_inferences.clear()
        self.current_inference_index = -1
        
        print(f"Confirmed all {confirmed_count} inferences")
        
        # Trigger auto-skip after successful bbox creation (only if we confirmed at least one)
        if confirmed_count > 0:
            self._trigger_auto_skip()
        
        return True
        
    def clear_temporary_inferences(self):
        """Clear all temporary inference annotations without saving."""
        if self.temporary_inferences:
            count = len(self.temporary_inferences)
            self.temporary_inferences.clear()
            self.current_inference_index = -1
            print(f"Cleared {count} temporary inferences")
            # Disable navigation handlers
            if hasattr(self.key_handler, 'enable_inference_navigation'):
                self.key_handler.enable_inference_navigation(False)
        else:
            print("No temporary inferences to clear")
            
    def update_current_inference_category(self, category_id: str, category_name: str) -> bool:
        """Update the category of the currently selected inference."""
        if not self.temporary_inferences or self.current_inference_index < 0:
            return False
            
        if self.current_inference_index >= len(self.temporary_inferences):
            return False
            
        # Update the category
        self.temporary_inferences[self.current_inference_index]['category_id'] = category_id
        self.temporary_inferences[self.current_inference_index]['category_name'] = category_name
        
        print(f"Updated inference category to: {category_name}")
        return True

    def create_fixed_bboxes_as_temporary(self):
        """Create all available fixed bboxes as temporary annotations that can be confirmed."""
        if not self.state.current_filename:
            logger.warning("Cannot create fixed bboxes: current filename is not set")
            print("Cannot create fixed bboxes: No file loaded")
            return False
            
        # Check if we're already in temporary bbox mode
        if self.temporary_inferences:
            # Clear existing temporary annotations
            logger.info(f"Clearing existing temporary annotations for {self.state.current_filename}")
            self.clear_temporary_inferences()
            print("Cleared existing temporary annotations")
            return True
            
        try:
            # Get project configuration
            from config import config
            project_name = config.get("project.name", "sinterizacao-1")
            
            # Get default category based on project
            if project_name == "carbonizacao-1":
                default_category_id = "1"
                default_category_name = "com_fumaca"
            elif project_name == "sinterizacao-1": 
                default_category_id = "4"
                default_category_name = "estado_indefinido"
            else:
                # Fallback for other projects
                default_category_id = None
                default_category_name = None
            
            # If category filter is active, use the filter category instead
            if self.category_filter_id is not None:
                default_category_id = str(self.category_filter_id)
                default_category_name = self.category_filter
            
            # Get existing annotations to check for duplicates
            existing_annotations = self.store.get_annotation_data_for_file(self.state.current_filename).get('annotations', [])
            existing_boxes = []
            for ann in existing_annotations:
                bbox = ann.get('bbox')
                if bbox and len(bbox) == 4:
                    existing_boxes.append(tuple(bbox))
            
            # Get fixed bboxes from project configuration
            from .fixed_annotation_helper import FixedAnnotationHelper
            helper = FixedAnnotationHelper(project_name)
            
            if project_name == "carbonizacao-1":
                # For carbonizacao, get all remaining fixed bboxes with their configured categories
                from project_config import ProjectCategoryManager
                category_manager = ProjectCategoryManager(config)
                fixed_bboxes_with_categories = category_manager.get_fixed_bboxes_with_categories()
                
                temp_annotations_created = 0
                for bbox_config in fixed_bboxes_with_categories:
                    bbox = bbox_config["bbox"]
                    bbox_tuple = tuple(bbox)
                    # Check if this bbox already exists
                    if bbox_tuple not in existing_boxes:
                        # Use configured category or default if none set
                        configured_category_id = bbox_config["category_id"]
                        configured_category_name = bbox_config["category_name"]
                        
                        # If category filter is active, use the filter category
                        if self.category_filter_id is not None:
                            final_category_id = str(self.category_filter_id)
                            final_category_name = self.category_filter
                        # If bbox has a configured category, use it
                        elif configured_category_id and configured_category_name:
                            final_category_id = configured_category_id
                            final_category_name = configured_category_name
                        # Otherwise use null (no category)
                        else:
                            final_category_id = None
                            final_category_name = None
                        
                        temp_annotation = {
                            'bbox': bbox,
                            'category_id': final_category_id,
                            'category_name': final_category_name,
                            'confidence': 1.0,  # Fixed bboxes have 100% confidence
                            'annotation_source': ANNOTATION_SOURCE_HUMAN
                        }
                        self.temporary_inferences.append(temp_annotation)
                        temp_annotations_created += 1
            else:
                # For sinterizacao, create single bbox with variation
                bbox = helper.get_bbox_for_sinterizacao()
                bbox_tuple = tuple(bbox)
                
                # Check if this bbox already exists (unlikely with random variation)
                if bbox_tuple not in existing_boxes:
                    temp_annotation = {
                        'bbox': bbox,
                        'category_id': default_category_id, 
                        'category_name': default_category_name,
                        'confidence': 1.0,
                        'annotation_source': ANNOTATION_SOURCE_HUMAN
                    }
                    self.temporary_inferences.append(temp_annotation)
                    temp_annotations_created = 1
                else:
                    temp_annotations_created = 0
            
            if self.temporary_inferences:
                # Sort by spatial position (top-left to bottom-right)
                self.temporary_inferences.sort(key=lambda temp: (temp['bbox'][1], temp['bbox'][0]))
                self.current_inference_index = 0
                
                # Clear permanent bbox selection when creating temporary bboxes
                self.state.current_annotation_index = -1
                
                # Enable navigation handlers
                if hasattr(self.key_handler, 'enable_inference_navigation'):
                    self.key_handler.enable_inference_navigation(True)
                    
                if project_name == "carbonizacao-1":
                    msg = f"Created {len(self.temporary_inferences)} temporary fixed bboxes"
                    if self.category_filter:
                        msg += f" with filter category '{self.category_filter}'"
                    else:
                        msg += " with configured categories"
                else:
                    msg = f"Created {len(self.temporary_inferences)} temporary bbox"
                    if self.category_filter:
                        msg += f" with category '{default_category_name}' (filter active)"
                    elif default_category_name:
                        msg += f" with default category '{default_category_name}'"
                    else:
                        msg += " (no default category)"
                    
                msg += ". Tab: navigate, Space: confirm current, C: confirm all, B: cancel"
                print(msg)
                
                logger.info(f"Created {len(self.temporary_inferences)} temporary fixed bbox annotations for {self.state.current_filename}")
            else:
                if project_name == "carbonizacao-1":
                    print("All fixed bboxes already exist for this frame")
                else:
                    print("Bbox already exists at these coordinates")
                    
            return len(self.temporary_inferences) > 0
            
        except Exception as e:
            logger.error(f"Error creating temporary fixed bboxes: {e}", exc_info=True)
            print(f"Error creating temporary bboxes: {e}")
            return False

    def _trigger_auto_skip(self):
        """Trigger auto-skip timer after bbox creation."""
        logger.info(f"Auto-skip: _trigger_auto_skip called, current mode: {self.state.auto_skip}")
        if self.state.auto_skip > 0:  # Any auto-skip mode enabled
            self.auto_skip_start_time = time.time()
            self.state.auto_skip_triggered = True
            logger.info(f"Auto-skip: Timer started (mode {self.state.auto_skip})")
        else:
            logger.info("Auto-skip: Mode is OFF, no timer started")
    
    def _check_auto_skip_timer(self):
        """Check if auto-skip timer has elapsed and perform navigation. Returns True if navigation occurred."""
        # Add frequent logging to see what's happening
        if not self.state.auto_skip_triggered:
            return False
            
        if self.auto_skip_start_time is None:
            logger.info("Auto-skip: Timer triggered but start_time is None!")
            return False
            
        # Check if delay has elapsed
        elapsed = time.time() - self.auto_skip_start_time
        if elapsed < self.state.auto_skip_delay_seconds:
            # Still waiting - don't log every time to avoid spam
            return False
            
        # Timer elapsed, perform navigation
        logger.info(f"Auto-skip: Timer elapsed ({elapsed:.2f}s), performing navigation (mode {self.state.auto_skip})")
        self.state.auto_skip_triggered = False
        self.auto_skip_start_time = None
        
        if self.state.auto_skip == 1:  # Frame mode
            # Navigate to next frame (same as 'D' key)
            if self.state.current_index < self.state.total_files - 1:
                self.state.current_index += 1
                logger.info("Auto-skip: Navigated to next frame")
                return True
        elif self.state.auto_skip == 2:  # Annotation mode
            # Navigate to next annotated frame (same as ']' key)
            next_idx = self.store.find_next_annotated_index(self.state.current_index, self.image_files)
            if next_idx is not None:
                self.state.current_index = next_idx
                logger.info(f"Auto-skip: Navigated to next annotated frame at index {next_idx}")
                return True
            else:
                logger.info("Auto-skip: No next annotated frame found")
        return False
    
    def _cancel_auto_skip(self):
        """Cancel any pending auto-skip navigation."""
        if self.state.auto_skip_triggered:
            self.state.auto_skip_triggered = False
            self.auto_skip_start_time = None
            logger.debug("Auto-skip: Cancelled due to manual navigation")

    def run(self):
        """Starts the main annotation loop."""
        if self.state.total_files == 0:
            msg = f"Error: No images found or loaded from '{self.images_dir}'. Cannot start annotator."
            print(msg)
            logger.error(msg)
            return

        # Create window with high DPI support for maximum quality
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_EXPANDED)
        # Enable OpenGL for better rendering performance
        cv2.setWindowProperty(self.window_name, cv2.WND_PROP_OPENGL, cv2.WINDOW_OPENGL)

        # Set initial window size (user can resize later)
        initial_width = 1280
        initial_height = 720
        if config:
             try:
                  # Use larger window for better image quality display
                  w_pct = config.get_float("annotation.window_width_percent", 0.9)
                  h_pct = config.get_float("annotation.window_height_percent", 0.9)
                  # Use reasonable defaults if percentages are invalid
                  base_w = 1600 # Assume a base screen width for percentage calculation
                  base_h = 900  # Assume a base screen height
                  initial_width = int(w_pct * base_w) if 0.1 < w_pct <= 1.0 else 1280
                  initial_height = int(h_pct * base_h) if 0.1 < h_pct <= 1.0 else 720
             except Exception:
                 logger.warning("Could not read window size from config. Using defaults.")
                 initial_width = 1280
                 initial_height = 720

        try:
            cv2.resizeWindow(self.window_name, initial_width, initial_height)
        except Exception as e:
            logger.warning(f"Could not resize window initially: {e}. Using default size.")

        # Register the instance method as the mouse callback
        cv2.setMouseCallback(self.window_name, self._mouse_callback)

        logger.info("Starting annotation loop. Press 'H' for help, 'Q' twice to quit.")

        # --- Main Outer Loop (Frame Navigation) ---
        while 0 <= self.state.current_index < self.state.total_files:
            # --- Load image and prepare display base ---
            if not self._load_and_prepare_image():
                # Loading failed, attempt to move to the next image if possible
                logger.warning(f"Skipping index {self.state.current_index} due to loading error.")
                if self.state.current_index < self.state.total_files - 1:
                    self.state.current_index += 1
                    continue # Try next iteration of outer loop
                else:
                    logger.error("Failed to load the last image. Exiting.")
                    break # Exit outer loop if last image failed

            # --- Inner Loop (Handling keys and display updates for the current frame) ---
            while True:
                # Check auto-skip timer first, before anything else
                if self._check_auto_skip_timer():
                    logger.info("Breaking inner loop due to auto-skip navigation.")
                    break # Break inner loop to load new frame
                    
                # --- Prepare data for renderer ---
                current_filename = self.state.current_filename
                if current_filename is None: # Should be set by _load_and_prepare_image
                    logger.error("Internal error: current_filename lost. Breaking inner loop.")
                    break

                # Fetch potentially updated data for rendering
                file_data = self.store.get_annotation_data_for_file(current_filename)

                # Fetch stats only if needed (just before rendering)
                stats_data = None
                if self.state.show_stats:
                    stats_data = self.store.get_statistics()
                    if stats_data: # Ensure stats were actually returned
                        stats_data['total_files_actual'] = self.state.total_files # Add context

                # --- Render the current state using the base display image ---
                if self.img_display_base is None or self.state.img_original_shape is None:
                    logger.error("Cannot render frame: Display base image or original shape missing. Breaking inner loop.")
                    break # Should not happen if load succeeded, but safety check

                # Prepare model info for rendering
                model_info = {
                    'has_model': self.has_model,
                    'project_name': config.get("project.name", "unknown") if self.has_model else None
                }
                
                # Prepare temporary inference info
                inference_info = {
                    'temporary_inferences': self.temporary_inferences,
                    'current_index': self.current_inference_index
                } if self.temporary_inferences else None
                
                # Render the complete frame with all UI elements
                frame_to_show = self.renderer.draw_frame(
                    self.img_display_base,       # Base image to draw on
                    self.state.img_original_shape, # Original dims for scaling boxes
                    file_data,                   # Data containing annotations list etc.
                    current_filename,            # Current filename string
                    self.state.current_index,    # Current image index
                    self.state.total_files,      # Total number of images
                    self.state.show_help,        # Flag: show help overlay?
                    self.state.show_stats,       # Flag: show stats overlay?
                    self.state.quit_confirm,     # Flag: show quit confirm message?
                    stats_data,                  # Calculated stats data (or None)
                    model_info,                  # Model status information
                    inference_info,              # Temporary inference information
                    self.state.auto_inference,   # Auto-inference state
                    self.state.auto_fixed_bbox,  # Auto-fixed bbox state
                    self.state.auto_skip,        # Auto-skip state
                    self.state.display_mode if hasattr(self.state, 'display_mode') else 0,  # Display mode
                    self.key_handler.get_category_filter_name()  # Category filter name
                )

                # --- Display the frame ---
                try:
                    # Check if window still exists before trying to show image
                    # Use WND_PROP_VISIBLE or WND_PROP_AUTOSIZE which return >= 0 if window exists
                    if cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE) < 0:
                         logger.warning("Window closed by user (detected before imshow). Exiting run loop.")
                         cv2.destroyAllWindows()
                         return # Exit the run method
                    cv2.imshow(self.window_name, frame_to_show)
                except Exception as e:
                     # Catch potential errors if window is destroyed unexpectedly during imshow
                     logger.warning(f"Error showing image (window likely closed): {e}. Exiting run loop.")
                     return # Exit the run method

                # --- Wait for Key Press ---
                key = cv2.waitKeyEx(100) # Use a small timeout (e.g., 100ms) to keep UI responsive

                # --- Handle potential window closure during waitKey ---
                if key == -1: # Timeout or non-key event
                    try: # Double check window status if no key pressed
                        if cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE) < 0:
                            logger.warning("Window closed by user (detected after waitKey timeout). Exiting run loop.")
                            cv2.destroyAllWindows()
                            return # Exit the run method
                    except Exception:
                        # Window might already be destroyed if check fails
                        logger.warning("Window likely closed during waitKey check. Exiting run loop.")
                        return # Exit run method
                    # If window is fine, -1 just means timeout, continue inner loop to redraw
                    continue

                # --- FIX: Restore Quit Confirmation Reset Logic from Old Version ---
                # This block resets the confirmation if any key OTHER than Q or ESC
                # is pressed while the confirmation is active.
                quit_codes = self.key_handler.KEY_CODES.get('QUIT', ())
                if not isinstance(quit_codes, (list, tuple)):
                    quit_codes = (quit_codes,) # Ensure it's iterable
                is_quit_key = key in quit_codes
                is_esc_key = key == self.key_handler.KEY_CODES.get('ESC')

                if not is_quit_key and not is_esc_key and self.state.quit_confirm:
                    logger.debug("Quit confirmation reset by other key press.")
                    self.state.quit_confirm = False # Reset directly in state
                # --- END FIX ---

                # --- Delegate Key Handling ---
                # Process the key using the KeyHandler
                # KeyHandler interacts with self.state and self.store based on key pressed
                result = self.key_handler.handle_key(key)

                # --- Process Handler Result ---
                should_break_inner = False # Default: stay in inner loop (redraw same frame)
                if result:
                    # Unpack result: ('ACTION_NAME', should_break_inner_bool)
                    action, should_break_inner = result
                    logger.debug(f"Key action received: '{action}', Should break inner loop: {should_break_inner}")

                    # Check for immediate quit signals from handler
                    if action in ('QUIT_IMMEDIATE', 'QUIT_CONFIRMED'):
                        logger.info(f"Quit action '{action}' received. Exiting application.")
                        cv2.destroyAllWindows()
                        return # Exit the entire run method
                # else: Key was not handled or handler returned None/False for breaking

                # If the handler indicated breaking (e.g., navigation), exit the inner loop
                if should_break_inner:
                    logger.debug("Breaking inner loop based on key handler result (e.g., navigation, clear).")
                    break # Break inner 'while True' loop to load next/prev frame or exit
            # --- End of inner loop ---

            # Check index validity again before next iteration of outer loop
            # (index could have been modified by handler action)
            if not (0 <= self.state.current_index < self.state.total_files):
                logger.info(f"Index ({self.state.current_index}) is now out of bounds. Exiting outer annotation loop.")
                break # Exit the outer while loop
        # --- End of outer loop ---

        logger.info("Annotation loop finished or exited.")
        cv2.destroyAllWindows() # Ensure window is closed cleanly