# src/bomia/annotation/key_handler.py
# Refatorado para padrões Python e com correção focada em _handle_quit.

import logging
from typing import Any, Callable, Tuple, List, Optional, Dict
import random
from datetime import datetime # Ensure datetime is imported
from pathlib import Path

# Import the state and store classes
try:
    from .state import AnnotationState
    # Import store and constants
    from .store import AnnotationStore, ANNOTATION_SOURCE_HUMAN
    # Import definitions for category/subcategory mapping
    from .definitions import CATEGORIES, SUBCATEGORIES, refresh_categories
    # Import fixed annotation helper
    from .fixed_annotation_helper import FixedAnnotationHelper
except ImportError:
    # Fallbacks for type hinting
    print("Error importing annotation components in key_handler. Using fallbacks.")
    class AnnotationState: pass
    class AnnotationStore:
         # Dummy methods needed by handlers below if import fails
         _lock = None # Add dummy lock attribute if accessed directly
         _annotations = {} # Add dummy annotations dict
         def clear_annotations(self, filename: str): pass
         def update_last_annotation_category(self, filename: str, cat_id: str, cat_name: str) -> bool: return False
         def get_annotation_data_for_file(self, filename: str) -> Dict[str, Any]: return {}
         def find_next_annotated_index(self, start_index: int, all_filenames: List[str]) -> Optional[int]: return None
         def find_prev_annotated_index(self, start_index: int, all_filenames: List[str]) -> Optional[int]: return None
         def get_statistics(self) -> Dict[str, Any]: return {}
         def save_annotations(self): pass # Add dummy save method
         def add_annotation(self, **kwargs): pass # Add dummy add_annotation method

    CATEGORIES = {}
    SUBCATEGORIES = {}
    ANNOTATION_SOURCE_HUMAN = "human"
    def refresh_categories(): pass
    class FixedAnnotationHelper:
        def __init__(self, project_name): pass
        def get_next_bbox(self, filename, existing): return None
        def get_bbox_for_sinterizacao(self): return (541, 532, 1258, 808)
    # Basic logging config if main one failed
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.error("Failed to import dependencies in key_handler.")
else:
    logger = logging.getLogger(__name__)

# Type Alias for handler return value
HandlerResult = Optional[Tuple[str, bool]] # (action_name, should_break_inner_loop)

class KeyHandler:
    """Base class for handling keyboard input."""
    # Mapeamento de códigos de tecla (ajustado para cobrir variantes comuns)
    KEY_CODES = {
        'ESC': 27,
        'ARROW_LEFT': (65361, 2424832),
        'ARROW_RIGHT': (65363, 2555904),
        'ARROW_UP': (65362, 2490368),
        'ARROW_DOWN': (65364, 2621440),
        'HOME': (65360, 2359296), # Linux, Windows
        'END': (65367, 2293760), # Linux, Windows
        'PAGE_UP': (65365, 2162688), # Linux, Windows
        'PAGE_DOWN': (65366, 2228224), # Linux, Windows
        'SHIFT': 65505, # Shift key
        'CAT_0': ord('0'),
        'CAT_1': ord('1'),
        'CAT_2': ord('2'),
        'CAT_3': ord('3'),
        'CAT_4': ord('4'),
        'CAT_5': ord('5'),
        'CAT_6': ord('6'),
        'CAT_7': ord('7'),
        'CAT_8': ord('8'),
        'CAT_9': ord('9'),
        'SUBCAT_I': (ord('7'), 65429, 65456+7), # 7, NumPad 7 (NumLock off/on), KP_7 (X11)
        'SUBCAT_M': (ord('8'), 65431, 65456+8), # 8, NumPad 8 (NumLock off/on), KP_8 (X11)
        'SUBCAT_F': (ord('9'), 65434, 65456+9), # 9, NumPad 9 (NumLock off/on), KP_9 (X11)
        'HELP': (ord('h'), ord('H')),
        'STATS': (ord('p'), ord('P')),
        'QUIT': (ord('q'), ord('Q')),
        'PREV_ANNOTATED': ord('['),
        'NEXT_ANNOTATED': ord(']'),
        'DELETE_SELECTED': (ord('x'), ord('X')),  # X key for selected annotation
        'DELETE_ALL': (65535, 127),  # Delete key, Backspace for all annotations
        'JUMP_FWD_ALIAS': (ord('w'), ord('W')), # Alias W
        'JUMP_BWD_ALIAS': (ord('s'), ord('S')), # Alias S
        'PREV_ALIAS': (ord('a'), ord('A')), # Alias A
        'NEXT_ALIAS': (ord('d'), ord('D')), # Alias D
        'RANDOM_ANNOTATION': (ord('b'), ord('B')),
        'REPEAT_LAST_BBOX': (ord('j'), ord('J')),  # J key for repeating last drawn bbox
        'INFERENCE': (ord('r'), ord('R')),  # R key for single inference
        'TAB': 9,
        'SHIFT_TAB': 353,  # Shift+Tab
        'SPACE': 32,
        'CONFIRM_ALL': (ord('c'), ord('C')),
        'AUTO_INFERENCE_TOGGLE': (ord('t'), ord('T')),  # T key for auto-inference toggle
        'AUTO_FIXED_BBOX_TOGGLE': (ord('k'), ord('K')),  # K key for auto-fixed bbox toggle
        'AUTO_SKIP_TOGGLE': (ord('l'), ord('L')),  # L key for auto-skip toggle
        'DISPLAY_MODE_TOGGLE': (ord('u'), ord('U')),  # U key for display mode toggle
    }

    def __init__(self):
        """Initialize the key handler."""
        # Handlers map key_name (from KEY_CODES) to a handler function
        self.handlers: Dict[str, Callable[[int], Any]] = {}

    def register_handler(self, key_name: str, handler: Callable[[int], Any]):
        """
        Register a handler function for a specific key name defined in KEY_CODES.
        """
        if key_name not in self.KEY_CODES:
             logger.warning(f"Attempted to register handler for unknown key name: {key_name}")
             return
        self.handlers[key_name] = handler

    def handle_key(self, key_code: int) -> Any:
        """
        Process a key press event by finding and executing the appropriate handler.
        """
        if key_code == -1: # No key pressed or non-key event
            return None

        logger.debug(f"Key pressed: Code={key_code}")

        # Check each registered handler
        for key_name, handler in self.handlers.items():
            key_codes_for_name = self.KEY_CODES.get(key_name)
            if key_codes_for_name is None: # Should not happen if registered correctly
                continue

            match = False
            # Check if the received key_code matches the registered code(s) for this key_name
            if isinstance(key_codes_for_name, (tuple, list)):
                if key_code in key_codes_for_name:
                    match = True
            elif key_code == key_codes_for_name: # If it's a single value
                    match = True

            if match:
                logger.debug(f"Matched key '{key_name}' -> executing handler.")
                try:
                    # Execute the handler and return its result
                    return handler(key_code)
                except Exception as e:
                    # Log errors during handler execution
                    logger.error(f"Error executing handler for key '{key_name}' (Code: {key_code}): {e}", exc_info=True)
                    # Add user feedback if possible (depends on context, might need main_window reference)
                    # print(f"Error processing key '{key_name}'. Check logs.")
                    return None # Indicate error or unexpected result

        # If no handler matched the key_code
        logger.debug(f"No handler found for key code: {key_code}")
        return None

class AnnotatorKeyHandler(KeyHandler):
    """
    Key handler specific to the UnifiedAnnotator. Interacts with State and Store
    to handle multiple annotations per frame.
    """
    def __init__(self, state: AnnotationState, store: AnnotationStore, all_filenames: List[str], images_dir: Optional[Path] = None):
        """
        Initialize with references to state, store, and filenames.
        """
        super().__init__()
        self.state = state
        self.store = store
        self.all_filenames = all_filenames # Store the list for navigation bounds
        # Store images_dir for path resolution in handlers
        self.images_dir = images_dir
        
        # Category filter
        self.category_filter = None
        self.category_filter_id = None
        
        # Inference capability tracking
        self.has_model = False
        self.annotator = None  # Will be set by annotator
        
        # Track shift key state for modifier combinations
        self.shift_pressed = False
        
        # Refresh categories to ensure they're loaded for the current project
        refresh_categories()
        
        self._register_default_handlers() # Register handlers upon initialization

    def _register_default_handlers(self):
        """Register all handlers for the annotator actions."""
        # System Handlers
        self.register_handler('ESC', self._handle_esc)
        self.register_handler('QUIT', self._handle_quit)
        self.register_handler('HELP', self._handle_help)
        self.register_handler('STATS', self._handle_stats)
        self.register_handler('DISPLAY_MODE_TOGGLE', self._handle_display_mode_toggle)

        # Frame Navigation
        self.register_handler('HOME', self._handle_first_frame)
        self.register_handler('END', self._handle_last_frame)
        self.register_handler('ARROW_LEFT', self._handle_prev_frame)
        self.register_handler('ARROW_RIGHT', self._handle_next_frame)
        self.register_handler('PREV_ALIAS', self._handle_prev_frame) # Alias A
        self.register_handler('NEXT_ALIAS', self._handle_next_frame) # Alias D
        self.register_handler('ARROW_UP', self._handle_jump_forward) # Alias W / Arrow Up
        self.register_handler('ARROW_DOWN', self._handle_jump_backward) # Alias S / Arrow Down
        self.register_handler('PAGE_UP', self._handle_page_up)
        self.register_handler('PAGE_DOWN', self._handle_page_down)
        self.register_handler('SHIFT', self._handle_shift)
        self.register_handler('JUMP_FWD_ALIAS', self._handle_jump_forward) # Alias W
        self.register_handler('JUMP_BWD_ALIAS', self._handle_jump_backward) # Alias S
        self.register_handler('PREV_ANNOTATED', self._handle_prev_annotated_frame)
        self.register_handler('NEXT_ANNOTATED', self._handle_next_annotated_frame)

        # Annotation Actions
        # Category selection -> Applies to LAST annotation in list
        # Get actual categories from definitions
        from .definitions import get_categories
        actual_categories = get_categories()
        for cat_id in actual_categories.keys():
            # Register handler for this category
            self.register_handler(f'CAT_{cat_id}', self._create_category_handler(cat_id))


        # --- MODIFIED: Register the new subcategory handler logic ---
        # Subcategory selection (NumPad 7,8,9) -> Applies to LAST 'panela_cura_ativa' annotation
        from .definitions import get_subcategories
        actual_subcategories = get_subcategories()
        subcat_key_mapping = {'i': 'SUBCAT_I', 'm': 'SUBCAT_M', 'f': 'SUBCAT_F'}
        for subcat_id, subcat_name in actual_subcategories.items():
            if subcat_id in subcat_key_mapping:
                self.register_handler(subcat_key_mapping[subcat_id], self._create_subcategory_handler(subcat_id))
        # --- END MODIFICATION ---

        # Delete Selected Annotation -> Deletes currently selected annotation only (X key)
        self.register_handler('DELETE_SELECTED', self._handle_delete_selected_annotation) # X
        # Delete All Annotations -> Deletes ALL annotations for the frame (Delete/Backspace keys)
        self.register_handler('DELETE_ALL', self._handle_delete_all_annotations) # Delete/Backspace
        self.register_handler('RANDOM_ANNOTATION', self._handle_random_annotation) # B
        self.register_handler('REPEAT_LAST_BBOX', self._handle_repeat_last_bbox) # J
        
        # Tab navigation for existing annotations (when not in inference mode)
        self.register_handler('TAB', self._handle_next_annotation)
        self.register_handler('SHIFT_TAB', self._handle_prev_annotation)
        
        # Inference Action -> Only register if model is available
        # Will be registered later via set_model_available() if model loads
        
        # Auto-inference toggle (always available, but functionality depends on model)
        self.register_handler('AUTO_INFERENCE_TOGGLE', self._handle_auto_inference_toggle)
        
        # Auto-fixed bbox toggle (always available)
        self.register_handler('AUTO_FIXED_BBOX_TOGGLE', self._handle_auto_fixed_bbox_toggle)
        
        # Auto-skip toggle (always available)
        self.register_handler('AUTO_SKIP_TOGGLE', self._handle_auto_skip_toggle)
        
    def set_model_available(self, has_model: bool):
        """Enable/disable inference handler based on model availability."""
        self.has_model = has_model
        if has_model:
            self.register_handler('INFERENCE', self._handle_inference)
            logger.info("Inference handler registered - press 'R' to run inference")
        else:
            # Remove handler if it was registered
            if 'INFERENCE' in self.handlers:
                del self.handlers['INFERENCE']
                
    def set_annotator(self, annotator):
        """Set reference to annotator for inference calls."""
        self.annotator = annotator
        
    def set_category_filter(self, category_filter: Optional[str], category_filter_id: Optional[int]):
        """Set the category filter for restricting new annotations."""
        self.category_filter = category_filter
        self.category_filter_id = category_filter_id
        if category_filter:
            logger.info(f"Category filter set: {category_filter} (ID: {category_filter_id})")
    
    def get_category_filter_name(self) -> Optional[str]:
        """Get the current category filter name."""
        return self.category_filter
        
    def enable_inference_navigation(self, enable: bool):
        """Enable/disable inference navigation handlers when temp inferences exist."""
        if enable:
            # Store original Tab handlers before overwriting
            self._stored_tab_handlers = {}
            for key in ['TAB', 'SHIFT_TAB']:
                if key in self.handlers:
                    self._stored_tab_handlers[key] = self.handlers[key]
                    
            self.register_handler('TAB', self._handle_next_inference)
            self.register_handler('SHIFT_TAB', self._handle_prev_inference)
            self.register_handler('SPACE', self._handle_confirm_current)
            self.register_handler('CONFIRM_ALL', self._handle_confirm_all)
            
            # Store original category handlers before overwriting
            self._stored_category_handlers = {}
            from .definitions import get_categories
            actual_categories = get_categories()
            for cat_id in actual_categories.keys():
                key_name = f'CAT_{cat_id}'
                if key_name in self.handlers:
                    self._stored_category_handlers[key_name] = self.handlers[key_name]
                # Register inference-specific category handler
                self.register_handler(key_name, self._create_inference_category_handler(cat_id))
                
            logger.debug("Inference navigation handlers enabled")
        else:
            # Remove inference-specific handlers
            for key in ['SPACE', 'CONFIRM_ALL']:
                if key in self.handlers:
                    del self.handlers[key]
                    
            # Restore original Tab handlers
            if hasattr(self, '_stored_tab_handlers'):
                for key_name, handler in self._stored_tab_handlers.items():
                    self.handlers[key_name] = handler
                self._stored_tab_handlers = {}
                    
            # Restore original category handlers
            if hasattr(self, '_stored_category_handlers'):
                for key_name, handler in self._stored_category_handlers.items():
                    self.handlers[key_name] = handler
                self._stored_category_handlers = {}
                    
            logger.debug("Inference navigation handlers disabled, original handlers restored")


    # --- Helper ---
    def _reset_drawing_state(self):
        """Helper to reset drawing flags in the state."""
        if hasattr(self.state, 'reset_drawing'):
             self.state.reset_drawing()
        else: # Fallback if state object is incomplete during dev/error
             if hasattr(self.state, 'drawing'): self.state.drawing = False
             if hasattr(self.state, 'start_point'): self.state.start_point = None

    # --- Handler Implementations (Using module-level HandlerResult type hint) ---

    # System Handlers
    def _handle_esc(self, key_code: int) -> HandlerResult:
        """Handle ESC key: immediate quit."""
        logger.info("ESC key pressed. Requesting immediate quit.")
        return 'QUIT_IMMEDIATE', True # Signal to break loops and quit

    def _handle_quit(self, key_code: int) -> HandlerResult:
        """Handle Q key: quit with confirmation."""
        logger.info(f"Entering _handle_quit. Current quit_confirm state: {getattr(self.state, 'quit_confirm', False)}")

        if getattr(self.state, 'quit_confirm', False):
            logger.info("Quit confirmed by second Q press. Exiting.")
            return 'QUIT_CONFIRMED', True # Signal to break loops and quit
        else:
            if hasattr(self.state, 'quit_confirm'):
                self.state.quit_confirm = True
            logger.info("Quit confirmation activated.")
            print("Press Q again to confirm quit.") # User feedback
            return 'QUIT_PENDING', False # Do not break inner loop, stay on frame

    def _handle_help(self, key_code: int) -> HandlerResult:
        """Toggle help display."""
        if hasattr(self.state, 'show_help'):
            self.state.show_help = not self.state.show_help
            # Reset other overlays except the one being toggled
            if hasattr(self.state, 'reset_overlays'):
                 self.state.reset_overlays(except_help=True)
            logger.debug(f"Toggled help overlay: {self.state.show_help}")
        else:
             logger.warning("State object missing 'show_help' attribute.")
        return 'TOGGLE_HELP', False # Don't break inner loop

    def _handle_stats(self, key_code: int) -> HandlerResult:
        """Toggle statistics display."""
        if hasattr(self.state, 'show_stats'):
            self.state.show_stats = not self.state.show_stats
            # Reset other overlays except the one being toggled
            if hasattr(self.state, 'reset_overlays'):
                 self.state.reset_overlays(except_stats=True)

            # If turning stats on, calculate them now
            if self.state.show_stats:
                try:
                    self.state.stats_data = self.store.get_statistics()
                    if self.state.stats_data: # Check if data was retrieved
                        # Add context from the current state
                        self.state.stats_data['total_files_actual'] = getattr(self.state, 'total_files', 'N/A')
                except Exception as e:
                     logger.error(f"Error getting statistics: {e}", exc_info=True)
                     self.state.stats_data = {"error": "Could not retrieve stats"}
            logger.debug(f"Toggled stats overlay: {self.state.show_stats}")
        else:
             logger.warning("State object missing 'show_stats' attribute.")
        return 'TOGGLE_STATS', False # Don't break inner loop

    def _handle_display_mode_toggle(self, key_code: int) -> HandlerResult:
        """Toggle display mode: 0=full, 1=no overlays, 2=boxes only."""
        if hasattr(self.state, 'display_mode'):
            # Cycle through the 3 modes
            self.state.display_mode = (self.state.display_mode + 1) % 3
            
            mode_names = ["Full Display", "No Overlays", "Boxes Only"]
            print(f"Display mode: {mode_names[self.state.display_mode]}")
            logger.debug(f"Display mode changed to: {self.state.display_mode}")
            
            return 'TOGGLE_DISPLAY_MODE', False  # Don't break inner loop, just redraw
        else:
            logger.warning("State object missing 'display_mode' attribute.")
            return 'TOGGLE_DISPLAY_MODE_FAILED', False

    # Navigation Handlers
    def _handle_first_frame(self, key_code: int) -> HandlerResult:
        """Go to the first frame."""
        if self.state.current_index > 0:
            self._reset_drawing_state()
            # Cancel any pending auto-skip
            if self.annotator and hasattr(self.annotator, '_cancel_auto_skip'):
                self.annotator._cancel_auto_skip()
            self.state.current_index = 0
            logger.debug("Navigating to first frame.")
            return 'FIRST_FRAME', True
        logger.debug("Already at first frame.")
        return None

    def _handle_last_frame(self, key_code: int) -> HandlerResult:
        """Go to the last frame."""
        last_index = self.state.total_files - 1
        if self.state.current_index < last_index:
            self._reset_drawing_state()
            # Cancel any pending auto-skip
            if self.annotator and hasattr(self.annotator, '_cancel_auto_skip'):
                self.annotator._cancel_auto_skip()
            self.state.current_index = last_index
            logger.debug("Navigating to last frame.")
            return 'LAST_FRAME', True
        logger.debug("Already at last frame.")
        return None

    def _handle_prev_frame(self, key_code: int) -> HandlerResult:
        """Go to the previous frame."""
        if self.state.current_index > 0:
            self._reset_drawing_state()
            # Cancel any pending auto-skip
            if self.annotator and hasattr(self.annotator, '_cancel_auto_skip'):
                self.annotator._cancel_auto_skip()
            self.state.current_index -= 1
            return 'PREV_FRAME', True
        logger.debug("Already at the beginning.")
        return None

    def _handle_next_frame(self, key_code: int) -> HandlerResult:
        """Go to the next frame."""
        last_index = self.state.total_files - 1
        if self.state.current_index < last_index:
            self._reset_drawing_state()
            # Cancel any pending auto-skip
            if self.annotator and hasattr(self.annotator, '_cancel_auto_skip'):
                self.annotator._cancel_auto_skip()
            self.state.current_index += 1
            return 'NEXT_FRAME', True
        logger.debug("Already at the end.")
        return None

    def _handle_jump_forward(self, key_code: int) -> HandlerResult:
        """Jump forward by a set number of frames."""
        jump_amount = 10
        last_index = self.state.total_files - 1
        if self.state.current_index < last_index:
            self._reset_drawing_state()
            target_index = min(last_index, self.state.current_index + jump_amount)
            if target_index > self.state.current_index:
                 self.state.current_index = target_index
                 return 'JUMP_FORWARD', True
            else: logger.debug("Jump forward resulted in no change."); return None
        logger.debug("At the end, cannot jump forward."); return None

    def _handle_jump_backward(self, key_code: int) -> HandlerResult:
        """Jump backward by a set number of frames."""
        jump_amount = 10
        if self.state.current_index > 0:
            self._reset_drawing_state()
            target_index = max(0, self.state.current_index - jump_amount)
            if target_index < self.state.current_index:
                self.state.current_index = target_index
                return 'JUMP_BACKWARD', True
            else: logger.debug("Jump backward resulted in no change."); return None
        logger.debug("At the beginning, cannot jump backward."); return None

    def _handle_jump_far_forward(self, key_code: int) -> HandlerResult:
        """Jump forward by a larger number of frames."""
        jump_amount = 100
        last_index = self.state.total_files - 1
        if self.state.current_index < last_index:
            self._reset_drawing_state()
            target_index = min(last_index, self.state.current_index + jump_amount)
            if target_index > self.state.current_index:
                self.state.current_index = target_index
                return 'JUMP_FAR_FORWARD', True
            else: logger.debug("Jump far forward resulted in no change."); return None
        logger.debug("At the end, cannot jump far forward."); return None

    def _handle_jump_far_backward(self, key_code: int) -> HandlerResult:
        """Jump backward by a larger number of frames."""
        jump_amount = 100
        if self.state.current_index > 0:
            self._reset_drawing_state()
            target_index = max(0, self.state.current_index - jump_amount)
            if target_index < self.state.current_index:
                self.state.current_index = target_index
                return 'JUMP_FAR_BACKWARD', True
            else: logger.debug("Jump far backward resulted in no change."); return None
        logger.debug("At the beginning, cannot jump far backward."); return None

    def _handle_shift(self, key_code: int) -> HandlerResult:
        """Handle shift key press/release - just track the state."""
        self.shift_pressed = True
        return None  # Don't break loop or perform action for shift alone

    def _handle_page_up(self, key_code: int) -> HandlerResult:
        """Handle PageUp: 100 frames normally, 1000 frames with Shift."""
        if self.shift_pressed:
            self.shift_pressed = False  # Reset shift state
            return self._handle_jump_very_far_forward(key_code)
        else:
            return self._handle_jump_far_forward(key_code)

    def _handle_page_down(self, key_code: int) -> HandlerResult:
        """Handle PageDown: 100 frames normally, 1000 frames with Shift."""
        if self.shift_pressed:
            self.shift_pressed = False  # Reset shift state
            return self._handle_jump_very_far_backward(key_code)
        else:
            return self._handle_jump_far_backward(key_code)

    def _handle_jump_very_far_forward(self, key_code: int) -> HandlerResult:
        """Jump forward by a very large number of frames (1000)."""
        jump_amount = 1000
        last_index = self.state.total_files - 1
        if self.state.current_index < last_index:
            self._reset_drawing_state()
            target_index = min(last_index, self.state.current_index + jump_amount)
            if target_index > self.state.current_index:
                self.state.current_index = target_index
                return 'JUMP_VERY_FAR_FORWARD', True
            else: logger.debug("Jump very far forward resulted in no change."); return None
        logger.debug("At the end, cannot jump very far forward."); return None

    def _handle_jump_very_far_backward(self, key_code: int) -> HandlerResult:
        """Jump backward by a very large number of frames (1000)."""
        jump_amount = 1000
        if self.state.current_index > 0:
            self._reset_drawing_state()
            target_index = max(0, self.state.current_index - jump_amount)
            if target_index < self.state.current_index:
                self.state.current_index = target_index
                return 'JUMP_VERY_FAR_BACKWARD', True
            else: logger.debug("Jump very far backward resulted in no change."); return None
        logger.debug("At the beginning, cannot jump very far backward."); return None

    def _handle_next_annotated_frame(self, key_code: int) -> HandlerResult:
        """Jump to the next frame that has any annotation."""
        self._reset_drawing_state()
        if self.category_filter_id is not None:
            next_idx = self._find_next_category_filtered_index(self.state.current_index)
        else:
            next_idx = self.store.find_next_annotated_index(self.state.current_index, self.all_filenames)
        if next_idx is not None:
            self.state.current_index = next_idx
            logger.debug(f"Navigating to next annotated frame: index {next_idx}")
            return 'NEXT_ANNOTATED', True
        else:
            print("No further annotated frames found.")
            logger.debug("No next annotated frame found.")
            return 'NO_NEXT_ANNOTATED', True # Still break to redraw without message

    def _handle_prev_annotated_frame(self, key_code: int) -> HandlerResult:
        """Jump to the previous frame that has any annotation."""
        self._reset_drawing_state()
        if self.category_filter_id is not None:
            prev_idx = self._find_prev_category_filtered_index(self.state.current_index)
        else:
            prev_idx = self.store.find_prev_annotated_index(self.state.current_index, self.all_filenames)
        if prev_idx is not None:
            self.state.current_index = prev_idx
            logger.debug(f"Navigating to previous annotated frame: index {prev_idx}")
            return 'PREV_ANNOTATED', True
        else:
            print("No previous annotated frames found.")
            logger.debug("No previous annotated frame found.")
            return 'NO_PREV_ANNOTATED', True # Still break to redraw without message

    def _find_next_category_filtered_index(self, start_index: int) -> Optional[int]:
        """Find the next frame that has annotations of the filtered category."""
        for i in range(start_index + 1, len(self.all_filenames)):
            filename = self.all_filenames[i]
            if self._has_category_annotation(filename):
                return i
        return None
    
    def _find_prev_category_filtered_index(self, start_index: int) -> Optional[int]:
        """Find the previous frame that has annotations of the filtered category."""
        for i in range(start_index - 1, -1, -1):
            filename = self.all_filenames[i]
            if self._has_category_annotation(filename):
                return i
        return None
    
    def _has_category_annotation(self, filename: str) -> bool:
        """Check if a file has annotations of the filtered category."""
        file_data = self.store.get_annotation_data_for_file(filename)
        annotations = file_data.get('annotations', [])
        if not annotations:
            return False
        
        for annotation in annotations:
            if annotation.get('category_id') == self.category_filter_id:
                return True
        return False

    # --- Annotation Action Handlers ---


    def _handle_delete_selected_annotation(self, key_code: int) -> HandlerResult:
        """Handle X: Delete the currently selected annotation only."""
        filename = self.state.current_filename
        if not filename:
            logger.warning("Cannot delete annotation: current filename is not set in state.")
            print("Cannot delete annotation: No file loaded.")
            return 'DELETE_SELECTED_FAILED', False
            
        # Check if an annotation is currently selected
        if self.state.current_annotation_index < 0:
            print("No annotation selected. Use Tab to select an annotation first.")
            return 'DELETE_SELECTED_NO_SELECTION', False
            
        # Get current annotations to check bounds
        file_data = self.store.get_annotation_data_for_file(filename)
        if not file_data or not file_data.get('annotations'):
            print("No annotations to delete.")
            return 'DELETE_SELECTED_NO_ANNOTATIONS', False
            
        annotations = file_data['annotations']
        if self.state.current_annotation_index >= len(annotations):
            print("Selected annotation index out of bounds.")
            self.state.current_annotation_index = -1  # Reset invalid selection
            return 'DELETE_SELECTED_INVALID_INDEX', False
            
        # Delete the selected annotation
        success = self.store.delete_annotation_by_index(filename, self.state.current_annotation_index)
        
        if success:
            print(f"Deleted annotation {self.state.current_annotation_index + 1}")
            logger.info(f"Deleted annotation at index {self.state.current_annotation_index} for {filename}")
            
            # Update selection index after deletion
            remaining_count = len(annotations) - 1  # One less after deletion
            if remaining_count == 0:
                # No annotations left
                self.state.current_annotation_index = -1
            elif self.state.current_annotation_index >= remaining_count:
                # If we deleted the last annotation, move to the new last one
                self.state.current_annotation_index = remaining_count - 1
            # If we deleted from the middle, keep the same index (it now points to the next annotation)
            
            # Force redraw to show updated state
            return 'DELETE_SELECTED_ANNOTATION', True
        else:
            print("Failed to delete annotation.")
            return 'DELETE_SELECTED_FAILED', False

    def _handle_delete_all_annotations(self, key_code: int) -> HandlerResult:
        """Handle Delete/Backspace: Delete ALL annotations in the current frame."""
        filename = self.state.current_filename
        if not filename:
            logger.warning("Cannot delete annotations: current filename is not set in state.")
            print("Cannot delete annotations: No file loaded.")
            return 'DELETE_ALL_FAILED', False
            
        # Get current annotations to check if any exist
        file_data = self.store.get_annotation_data_for_file(filename)
        if not file_data or not file_data.get('annotations'):
            print("No annotations to delete.")
            return 'DELETE_ALL_NO_ANNOTATIONS', False
            
        # Count annotations before deletion for feedback
        annotation_count = len(file_data['annotations'])
        
        # Clear all annotations for this frame
        success = self.store.clear_annotations(filename)
        
        if success:
            print(f"Deleted all {annotation_count} annotations from current frame")
            logger.info(f"Cleared all {annotation_count} annotations for {filename}")
            
            # Reset selection since all annotations are gone
            self.state.current_annotation_index = -1
            
            # Force redraw to show cleared state
            return 'DELETE_ALL_ANNOTATIONS', True
        else:
            print("Failed to delete annotations.")
            logger.warning(f"Failed to clear annotations for {filename}")
            return 'DELETE_ALL_FAILED', False

    def _create_category_handler(self, category_id: str) -> Callable[[int], HandlerResult]:
        """
        Creates a handler for category keys.
        Applies the category to the selected annotation if one is selected (via Tab navigation),
        otherwise applies to the LAST annotation in the current frame's list.
        """
        # Get fresh categories in case they've changed
        from .definitions import get_categories
        actual_categories = get_categories()
        category_name = actual_categories.get(category_id, f"UnknownID_{category_id}") # Look up name once

        def handler(key_code: int) -> HandlerResult:
            filename = self.state.current_filename
            if not filename:
                logger.warning(f"Category key pressed for '{category_id}', but no file loaded.")
                print("Cannot set category: No file loaded.")
                return f'SET_CATEGORY_{category_id}_FAILED', False

            if category_name.startswith("UnknownID_"):
                 logger.error(f"Invalid category_id '{category_id}' used in handler.")
                 print(f"Error: Invalid category ID {category_id}")
                 return f'SET_CATEGORY_{category_id}_FAILED', False

            # Store the last pressed category for J key behavior
            self.state.last_pressed_category_id = category_id
            self.state.last_pressed_category_name = category_name
            logger.debug(f"Stored last pressed category: {category_id} ({category_name})")

            # Check if an annotation is selected via Tab navigation
            if self.state.current_annotation_index >= 0:
                # Update the selected annotation
                success = self.store.update_annotation_category_by_index(
                    filename, self.state.current_annotation_index, category_id, category_name
                )
                
                if success:
                    logger.info(f"Applied category {category_id} ('{category_name}') to selected annotation {self.state.current_annotation_index} of {filename}")
                    print(f"Category set for selected annotation: {category_name}")
                else:
                    logger.warning(f"Failed to apply category {category_id} to selected annotation {self.state.current_annotation_index} of {filename}")
                    print(f"Warning: Could not set category for selected annotation")
                    
                return f'SET_CATEGORY_SELECTED_{category_id}', True  # Refresh to show updated category
            else:
                # No selection, update the last annotation as before
                success = self.store.update_last_annotation_category(filename, category_id, category_name)

                if success:
                    # Also update the stored category in state for repeat functionality
                    self.state.last_drawn_category_id = category_id
                    self.state.last_drawn_category_name = category_name
                    logger.info(f"Applied category {category_id} ('{category_name}') to last annotation of {filename}")
                    print(f"Category set for last annotation: {category_name}")
                else:
                    logger.warning(f"Failed to apply category {category_id} to last annotation of {filename} (maybe list is empty?).")
                    print(f"Warning: Could not set category for {filename}. No annotations yet?")

                # Do not break inner loop, just update data and redraw
                return f'SET_CATEGORY_LAST_{category_id}', False

        handler.__name__ = f"handle_category_{category_name.replace(' ', '_').lower()}"
        return handler

    # --- CORRECTED SUBCATEGORY HANDLER ---
    def _create_subcategory_handler(self, subcategory_key: str) -> Callable[[int], HandlerResult]:
        """
        Factory function to create a handler for a specific subcategory assignment key.
        This updates the *last* annotation with category 'panela_cura_ativa'
        by adding/updating subcategory info within that annotation entry.
        """
        # --- FIX: Look up subcategory_name HERE, in the outer function scope ---
        from .definitions import get_subcategories
        actual_subcategories = get_subcategories()
        actual_subcategory_name = actual_subcategories.get(subcategory_key, f"unknown_key_{subcategory_key}")
        if actual_subcategory_name.startswith("unknown_key_"):
             logger.debug(f"Subcategory key '{subcategory_key}' not found in current project.")
             # Return a dummy handler that does nothing or logs an error if key is invalid
             def dummy_handler(key_code: int) -> HandlerResult:
                 logger.debug(f"Invalid subcategory key '{subcategory_key}' pressed.")
                 print(f"Error: Invalid subcategory key '{subcategory_key}'")
                 return f'SET_SUBCATEGORY_FAILED_INVALID_KEY', False
             dummy_handler.__name__ = f"handle_invalid_subcategory_{subcategory_key}"
             return dummy_handler
        # --- END FIX ---

        def handler(key_code: int) -> HandlerResult:
            filename = self.state.current_filename
            if not filename:
                logger.warning(f"Subcategory key pressed for '{subcategory_key}', but no file loaded.")
                print("Cannot set subcategory: No file loaded.")
                return f'SET_SUBCATEGORY_FAILED_NO_FILE', False

            # Use the name looked up in the outer scope
            subcategory_name_to_set = actual_subcategory_name

            logger.debug(f"Attempting to assign subcategory '{subcategory_name_to_set}' (ID: {subcategory_key}) to relevant annotation in {filename}")

            needs_save = False
            updated_annotation = False
            target_category_name = "panela_cura_ativa" # Hardcoded target category

            # --- Access annotation store safely ---
            # Check if store and its lock attribute exist before trying to acquire
            if not hasattr(self.store, '_lock') or self.store._lock is None:
                 logger.error("AnnotationStore lock not available. Cannot safely update.")
                 print("Error: Internal issue accessing annotation data.")
                 return f'SET_SUBCATEGORY_FAILED_LOCK', False

            with self.store._lock: # Acquire lock before accessing internal data
                # Get the raw file data dictionary (must hold lock)
                # Use .get() for safer access to the top-level entry
                file_data = self.store._annotations.get(filename)

                # Check if file_data exists and annotations is a list
                if file_data and isinstance(file_data.get("annotations"), list):
                    annotations_list = file_data["annotations"]
                    target_annotation_index = -1

                    # Find the index of the last annotation with the target category
                    for i in range(len(annotations_list) - 1, -1, -1):
                        annotation_entry = annotations_list[i]
                        if isinstance(annotation_entry, dict) and annotation_entry.get("category_name") == target_category_name:
                            target_annotation_index = i
                            break # Found the most recent one

                    if target_annotation_index != -1:
                        target_annotation = annotations_list[target_annotation_index]
                        # Ensure target_annotation is a dictionary before modifying
                        if not isinstance(target_annotation, dict):
                            logger.error(f"Found target annotation at index {target_annotation_index} for {filename}, but it's not a dictionary: {target_annotation}. Cannot update.")
                            # --- FIX: Replace continue with return ---
                            return f'SET_SUBCATEGORY_FAILED_INVALID_ENTRY', False # Exit handler for this key press
                            # --- END FIX ---

                        # Check if update is actually needed
                        if (target_annotation.get('subcategory_id') != subcategory_key or
                            target_annotation.get('subcategory_name') != subcategory_name_to_set): # Use looked-up name

                            logger.info(f"Updating annotation at index {target_annotation_index} for file {filename} with subcategory: {subcategory_name_to_set}")
                            target_annotation['subcategory_id'] = subcategory_key
                            target_annotation['subcategory_name'] = subcategory_name_to_set # Use looked-up name
                            # Ensure file's main timestamp is updated when its contents change
                            file_data["updated_at_iso"] = datetime.now().isoformat()
                            needs_save = True
                            updated_annotation = True
                        else:
                            logger.debug(f"Annotation at index {target_annotation_index} for {filename} already has subcategory {subcategory_name_to_set}. No update needed.")
                            updated_annotation = True # Treat as success for UI feedback

                    else:
                        logger.warning(f"Subcategory key '{subcategory_key}' pressed for {filename}, but no annotation with category '{target_category_name}' found in the list.")
                        print(f"Info: No '{target_category_name}' annotation found to apply subcategory.")
                else:
                    logger.warning(f"Subcategory key '{subcategory_key}' pressed, but no valid annotation data found for {filename}.")
                    print(f"Info: No annotations found for {filename}.")
            # --- Lock released ---

            if needs_save:
                if hasattr(self.store, 'save_annotations'):
                    self.store.save_annotations()
                else:
                    logger.error("Cannot save annotations: store object missing 'save_annotations' method.")
                    print("Error: Failed to save annotation changes.")


            # Update UI (e.g., status bar) - Placeholder
            if updated_annotation:
                 print(f"Status: Set subcategory: {subcategory_name_to_set}") # Example console feedback
            # (Actual UI update happens on redraw in the main loop)

            # Do not break inner loop, just update data and redraw
            return f'SET_SUBCATEGORY_{subcategory_key}', False

        # --- FIX: Set __name__ using the name looked up in the outer scope ---
        # Set a descriptive name for debugging using the name we looked up earlier
        handler.__name__ = f"handle_subcategory_{actual_subcategory_name.replace(' ', '_').lower()}"
        return handler
    # --- END CORRECTED SUBCATEGORY HANDLER ---

    def _handle_random_annotation(self, key_code: int) -> HandlerResult:
        """
        Handle 'B' key: Create temporary fixed bboxes that can be confirmed like inference results.
        - Creates all fixed bboxes as temporary annotations with appropriate default categories
        - Use Tab/Space/C to navigate and confirm like inference system
        """
        if not self.annotator:
            logger.warning("Cannot create temporary bboxes: annotator not set")
            print("Cannot create temporary bboxes: No annotator available")
            return 'CREATE_TEMP_BBOXES_FAILED', False
            
        # Call the annotator method to create temporary fixed bboxes
        success = self.annotator.create_fixed_bboxes_as_temporary()
        
        if success:
            return 'CREATE_TEMP_BBOXES', True  # Refresh display
        else:
            return 'CREATE_TEMP_BBOXES_FAILED', False

    def _handle_repeat_last_bbox(self, key_code: int) -> HandlerResult:
        """
        Handle 'J' key: Repeat the last bbox that was drawn by the user.
        Uses the same bbox coordinates as the last drawn annotation.
        """
        filename = self.state.current_filename
        if not filename:
            logger.warning("Cannot repeat last bbox: current filename is not set in state.")
            print("Cannot repeat last bbox: No file loaded.")
            return 'REPEAT_LAST_BBOX_FAILED', False

        # Check if we have a last drawn bbox stored
        if self.state.last_drawn_bbox is None:
            logger.info("No last drawn bbox available to repeat.")
            print("No previous bbox to repeat. Draw a bbox first.")
            return 'NO_LAST_BBOX', False
            
        # Check if we have a last pressed category (unless category filter is active)
        if (self.category_filter_id is None and 
            self.state.last_pressed_category_id is None):
            logger.info("No category key pressed yet.")
            print("No category selected yet. Press a category key (0-9) first.")
            return 'NO_CATEGORY_SELECTED', False

        bbox_to_save = self.state.last_drawn_bbox

        # Check if this bbox already exists to avoid duplicates
        current_file_data = self.store.get_annotation_data_for_file(filename)
        if current_file_data and isinstance(current_file_data.get("annotations"), list):
            existing_annotations = current_file_data["annotations"]
            for annotation in existing_annotations:
                if annotation.get('bbox') == list(bbox_to_save):
                    logger.info(f"Bbox {bbox_to_save} already exists for {filename}. Skipping duplicate.")
                    print("Bbox already exists at these coordinates. Skipping duplicate.")
                    return 'BBOX_ALREADY_EXISTS', False

        # Get the absolute path to the image
        original_path = filename # Default path
        try:
            from pathlib import Path
            # Use self.images_dir if available (set during AnnotatorKeyHandler init)
            img_dir = getattr(self, 'images_dir', None)
            if img_dir and isinstance(img_dir, Path) and img_dir.is_dir():
                image_path = img_dir / filename
                if image_path.exists(): # Check if constructed path is valid
                     original_path = str(image_path.resolve())
                else:
                     logger.warning(f"Constructed image path {image_path} does not exist. Using filename as path.")
            else:
                # Fallback: try getting from state if not set on self
                img_dir_state = getattr(self.state, 'images_dir', None)
                if img_dir_state and isinstance(img_dir_state, Path) and img_dir_state.is_dir():
                     image_path = img_dir_state / filename
                     if image_path.exists():
                         original_path = str(image_path.resolve())
                     else:
                          logger.warning(f"Constructed image path from state {image_path} does not exist. Using filename as path.")
                else:
                     logger.warning("Could not determine images_dir attribute from self or state. Using filename as path.")
        except Exception as e:
            logger.error(f"Error resolving image path: {e}")

        # Get category info - use last pressed category key (0-9)
        # If category filter is active, use the filter category
        if self.category_filter_id is not None:
            category_id = self.category_filter_id
            category_name = self.category_filter
        else:
            # Use the stored category from the last pressed category key (0-9)
            category_id = self.state.last_pressed_category_id
            category_name = self.state.last_pressed_category_name

        try:
            # Add the annotation
            self.store.add_annotation(
                filename=filename,
                bbox=bbox_to_save,
                category_id=category_id,
                category_name=category_name,
                original_path=original_path,
                annotation_source=ANNOTATION_SOURCE_HUMAN
            )
            logger.info(f"Repeated last bbox {bbox_to_save} for {filename} with last pressed category: {category_name} (ID: {category_id})")
            print(f"Repeated last bbox with last pressed category: {category_name}")
            
            # Auto-select the newly created annotation (same as mouse drawing)
            file_data = self.store.get_annotation_data_for_file(filename)
            if file_data and file_data.get('annotations'):
                # Set selection to the last annotation (which is the one we just added)
                self.state.current_annotation_index = len(file_data['annotations']) - 1
                logger.debug(f"Auto-selected newly repeated bbox at index {self.state.current_annotation_index}")
            
            # Trigger auto-skip after successful bbox creation
            if self.annotator and hasattr(self.annotator, '_trigger_auto_skip'):
                self.annotator._trigger_auto_skip()
                
        except Exception as e:
            logger.error(f"Error repeating last bbox: {e}", exc_info=True)
            print(f"Error repeating last bbox: {e}")
            return 'REPEAT_LAST_BBOX_FAILED', False

        # Return True to break inner loop and refresh display
        return 'REPEAT_LAST_BBOX', True

    def _handle_inference(self, key_code: int) -> HandlerResult:
        """
        Handle 'R' key: Toggle inference mode - run inference or clear existing inferences.
        Uses the loaded model to detect objects and add them as inference annotations.
        """
        if not self.has_model or not self.annotator:
            logger.warning("Cannot run inference: No model loaded or annotator not set")
            print("No model available for inference")
            return 'INFERENCE_FAILED', False
            
        filename = self.state.current_filename
        if not filename:
            logger.warning("Cannot run inference: current filename is not set in state.")
            print("Cannot run inference: No file loaded.")
            return 'INFERENCE_FAILED', False
            
        # Check if we're already in inference mode
        if self.annotator.temporary_inferences:
            # Clear inference mode
            logger.info(f"Exiting inference mode for {filename}")
            self.annotator.clear_temporary_inferences()
            print("Exited inference mode")
            return 'INFERENCE_CANCELLED', True
            
        try:
            # Call the annotator's inference method
            success = self.annotator.run_inference_on_current_frame()
            
            if success:
                logger.info(f"Inference completed for {filename}")
                # Enable navigation handlers if inferences were found
                if self.annotator.temporary_inferences:
                    self.enable_inference_navigation(True)
                # Return True to break inner loop and refresh display
                return 'INFERENCE_COMPLETED', True
            else:
                logger.warning(f"Inference failed for {filename}")
                return 'INFERENCE_FAILED', False
                
        except Exception as e:
            logger.error(f"Error during inference for {filename}: {e}", exc_info=True)
            print(f"Error during inference: {e}")
            return 'INFERENCE_ERROR', False
            
    def _handle_auto_inference_toggle(self, key_code: int) -> HandlerResult:
        """
        Handle 'T' key: Toggle auto-inference mode on/off.
        When enabled, inference will run automatically when changing frames.
        """
        if not self.has_model or not self.annotator:
            logger.warning("Cannot toggle auto-inference: No model loaded or annotator not set")
            print("No model available for auto-inference")
            return 'AUTO_INFERENCE_FAILED', False
            
        # Toggle the auto-inference state
        self.state.auto_inference = not self.state.auto_inference
        
        if self.state.auto_inference:
            # Disable auto-fixed bbox when enabling auto-inference (mutual exclusion)
            if self.state.auto_fixed_bbox:
                self.state.auto_fixed_bbox = False
                print("Auto-fixed bbox disabled (mutual exclusion)")
            logger.info("Auto-inference mode enabled")
            print("Auto-inference mode: ON")
        else:
            logger.info("Auto-inference mode disabled")
            print("Auto-inference mode: OFF")
            
        return 'AUTO_INFERENCE_TOGGLED', True  # Refresh display to show status
            
    def _handle_auto_fixed_bbox_toggle(self, key_code: int) -> HandlerResult:
        """
        Handle 'K' key: Toggle auto-fixed bbox mode on/off.
        When enabled, fixed bboxes will be created automatically when changing frames.
        """
        # Toggle the auto-fixed bbox state
        self.state.auto_fixed_bbox = not self.state.auto_fixed_bbox
        
        if self.state.auto_fixed_bbox:
            # Disable auto-inference when enabling auto-fixed bbox (mutual exclusion)
            if self.state.auto_inference:
                self.state.auto_inference = False
                print("Auto-inference disabled (mutual exclusion)")
                
            # Immediately create fixed bboxes for current frame
            if self.annotator:
                try:
                    success = self.annotator.create_fixed_bboxes_as_temporary()
                    if success:
                        logger.debug("Auto-fixed bbox: Created temporary fixed bboxes immediately")
                except Exception as e:
                    logger.error(f"Auto-fixed bbox immediate creation failed: {e}", exc_info=True)
                    
            logger.info("Auto-fixed bbox mode enabled")
            print("Auto-fixed bbox mode: ON")
        else:
            # Clear temporary fixed bboxes when disabling auto-fixed mode
            if self.annotator and self.annotator.temporary_inferences:
                self.annotator.clear_temporary_inferences()
                logger.debug("Auto-fixed bbox: Cleared temporary fixed bboxes")
                
            logger.info("Auto-fixed bbox mode disabled")
            print("Auto-fixed bbox mode: OFF")
            
        return 'AUTO_FIXED_BBOX_TOGGLED', True  # Refresh display to show status
            
    def _handle_auto_skip_toggle(self, key_code: int) -> HandlerResult:
        """
        Handle 'L' key: Cycle through auto-skip modes.
        0: OFF, 1: Frame, 2: Annotation
        """
        # Cycle through the 3 auto-skip states
        self.state.auto_skip = (self.state.auto_skip + 1) % 3
        
        mode_names = ["OFF", "Frame", "Annotation"]
        mode_name = mode_names[self.state.auto_skip]
        
        logger.info(f"Auto-skip mode changed to: {mode_name}")
        print(f"Auto-skip mode: {mode_name}")
        
        return 'AUTO_SKIP_TOGGLED', True  # Refresh display to show status
            
    def _handle_next_inference(self, key_code: int) -> HandlerResult:
        """Handle Tab key: Navigate to next inference."""
        logger.debug(f"Tab pressed, handling next inference. Temp inferences: {len(self.annotator.temporary_inferences) if self.annotator else 0}")
        if self.annotator and self.annotator.temporary_inferences:
            self.annotator.navigate_inference(1)
            return 'NEXT_INFERENCE', True  # Refresh display
        return 'NO_INFERENCES', False
        
    def _handle_prev_inference(self, key_code: int) -> HandlerResult:
        """Handle Shift+Tab key: Navigate to previous inference."""
        if self.annotator and self.annotator.temporary_inferences:
            self.annotator.navigate_inference(-1)
            return 'PREV_INFERENCE', True  # Refresh display
        return 'NO_INFERENCES', False
        
    def _handle_confirm_current(self, key_code: int) -> HandlerResult:
        """Handle Space key: Confirm current inference."""
        if self.annotator and self.annotator.temporary_inferences:
            success = self.annotator.confirm_current_inference()
            # Disable navigation if no more inferences
            if not self.annotator.temporary_inferences:
                self.enable_inference_navigation(False)
            return 'CONFIRM_CURRENT', True  # Refresh display
        return 'NO_INFERENCES', False
        
    def _handle_confirm_all(self, key_code: int) -> HandlerResult:
        """Handle C key: Confirm all inferences."""
        if self.annotator and self.annotator.temporary_inferences:
            success = self.annotator.confirm_all_inferences()
            # Disable navigation after confirming all
            self.enable_inference_navigation(False)
            return 'CONFIRM_ALL', True  # Refresh display
        return 'NO_INFERENCES', False
        
    def _create_inference_category_handler(self, category_id: str) -> Callable[[int], HandlerResult]:
        """Create a handler for changing category of current inference."""
        from .definitions import get_categories
        actual_categories = get_categories()
        category_name = actual_categories.get(category_id, f"UnknownID_{category_id}")
        
        def handler(key_code: int) -> HandlerResult:
            if not self.annotator or not self.annotator.temporary_inferences:
                return 'NO_INFERENCES', False
                
            if category_name.startswith("UnknownID_"):
                logger.error(f"Invalid category_id '{category_id}' used in inference handler.")
                print(f"Error: Invalid category ID {category_id}")
                return f'UPDATE_INFERENCE_CATEGORY_{category_id}_FAILED', False
                
            # Store the last pressed category for J key behavior
            self.state.last_pressed_category_id = category_id
            self.state.last_pressed_category_name = category_name
            logger.debug(f"Stored last pressed category from inference: {category_id} ({category_name})")
                
            # Update the category of current inference
            success = self.annotator.update_current_inference_category(category_id, category_name)
            
            if success:
                logger.info(f"Updated inference category to {category_id} ('{category_name}')")
                return f'UPDATE_INFERENCE_CATEGORY_{category_id}', True  # Refresh display
            else:
                logger.warning(f"Failed to update inference category")
                return f'UPDATE_INFERENCE_CATEGORY_{category_id}_FAILED', False
                
        # Mark this as an inference handler so we can remove it later
        handler._is_inference_handler = True
        handler.__name__ = f"handle_inference_category_{category_name.replace(' ', '_').lower()}"
        return handler
        
    def _handle_next_annotation(self, key_code: int) -> HandlerResult:
        """Handle Tab key: Navigate to next existing annotation when not in inference mode."""
        filename = self.state.current_filename
        if not filename:
            return 'NO_FILE', False
            
        # Get current annotations for the file
        file_data = self.store.get_annotation_data_for_file(filename)
        if not file_data or not file_data.get('annotations'):
            return 'NO_ANNOTATIONS', False
            
        annotations = file_data['annotations']
        if not annotations:
            return 'NO_ANNOTATIONS', False
            
        # Create a sorted list of indices based on bbox position (top-left to bottom-right)
        sorted_indices = list(range(len(annotations)))
        sorted_indices.sort(key=lambda i: (
            annotations[i]['bbox'][1] if annotations[i].get('bbox') else 0,  # y1 (top)
            annotations[i]['bbox'][0] if annotations[i].get('bbox') else 0   # x1 (left)
        ))
        
        # Find current position in sorted order
        if self.state.current_annotation_index == -1:
            # No selection yet, start at first
            current_sorted_pos = -1
        else:
            try:
                current_sorted_pos = sorted_indices.index(self.state.current_annotation_index)
            except ValueError:
                current_sorted_pos = -1
                
        # Move to next in sorted order
        current_sorted_pos = (current_sorted_pos + 1) % len(sorted_indices)
        self.state.current_annotation_index = sorted_indices[current_sorted_pos]
            
        logger.debug(f"Selected annotation {self.state.current_annotation_index} of {len(annotations)} (sorted position {current_sorted_pos})")
        return 'NEXT_ANNOTATION', True  # Refresh display
        
    def _handle_prev_annotation(self, key_code: int) -> HandlerResult:
        """Handle Shift+Tab key: Navigate to previous existing annotation when not in inference mode."""
        filename = self.state.current_filename
        if not filename:
            return 'NO_FILE', False
            
        # Get current annotations for the file
        file_data = self.store.get_annotation_data_for_file(filename)
        if not file_data or not file_data.get('annotations'):
            return 'NO_ANNOTATIONS', False
            
        annotations = file_data['annotations']
        if not annotations:
            return 'NO_ANNOTATIONS', False
            
        # Create a sorted list of indices based on bbox position (top-left to bottom-right)
        sorted_indices = list(range(len(annotations)))
        sorted_indices.sort(key=lambda i: (
            annotations[i]['bbox'][1] if annotations[i].get('bbox') else 0,  # y1 (top)
            annotations[i]['bbox'][0] if annotations[i].get('bbox') else 0   # x1 (left)
        ))
        
        # Find current position in sorted order
        if self.state.current_annotation_index == -1:
            # No selection yet, start at last
            current_sorted_pos = len(sorted_indices)
        else:
            try:
                current_sorted_pos = sorted_indices.index(self.state.current_annotation_index)
            except ValueError:
                current_sorted_pos = len(sorted_indices)
                
        # Move to previous in sorted order
        current_sorted_pos = (current_sorted_pos - 1) % len(sorted_indices)
        self.state.current_annotation_index = sorted_indices[current_sorted_pos]
            
        logger.debug(f"Selected annotation {self.state.current_annotation_index} of {len(annotations)} (sorted position {current_sorted_pos})")
        return 'PREV_ANNOTATION', True  # Refresh display