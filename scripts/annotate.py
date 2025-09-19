# scripts/annotate.py

import argparse
import os
import sys
import logging # Import logging module

# --- Path Setup ---
# Add src directory to Python path
SRC_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

# --- Early Import and Logging Setup ---
# Import config and logging setup first
try:
    from config import config  # Import the global config object
    from utils.logging_config import setup_logging

    # Setup logging as early as possible
    setup_logging()
    logger = logging.getLogger(__name__) # Get logger for this script
    logger.info("Logging configured.")

except ImportError as e:
    # Handle critical import errors before logging is fully configured
    print(f"FATAL: Failed to import core components (config/logging): {e}", file=sys.stderr)
    print(f"Ensure bomia-engine/src is in PYTHONPATH or run via 'poetry run'.", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"FATAL: An unexpected error occurred during initial setup: {e}", file=sys.stderr)
    sys.exit(1)


# --- Import Annotation Components ---
# Now import the rest of the required components
try:
    from annotator.annotator import UnifiedAnnotator
    from annotator.state import AnnotationState
    from annotator.store import AnnotationStore
    from annotator.renderer import AnnotationRenderer
    from annotator.key_handler import AnnotatorKeyHandler
except ImportError as e:
    logger.critical(f"Failed to import annotation components: {e}", exc_info=True)
    sys.exit(1)


def main():
    """
    Main function to initialize and run the Unified Annotation Tool.
    """
    logger.info("Setting up annotation tool...")

    # --- Configuration Validation (Configuration loaded globally in config.py) ---
    if not config:
         logger.critical("Application configuration failed to load. Cannot start annotator.")
         return # Exit main

    # argparse setup - Keep it minimal, primarily relying on config file
    parser = argparse.ArgumentParser(description="Unified annotation tool for classification and bounding boxes.")
    parser.add_argument("--model", help="Path to YOLO model for inference (optional, uses project default if available)")
    parser.add_argument("--conf", type=float, default=config.get("inference.confidence_threshold", 0.35), help="Confidence threshold for inference")
    parser.add_argument("--category-filter", type=str, default=None, help="Filter to only allow creating annotations for specific category (e.g., 'trator', 'operador')")
    args = parser.parse_args()

    # Model path resolution logic
    def resolve_model_path(config, args_model):
        """Resolve model path: CLI arg > project default > None"""
        if args_model:
            return args_model  # User explicitly provided model
        
        # Try default project model
        project_name = config.get("project.name")
        default_model = f"data/{project_name}/models/{project_name}/weights/best.pt"
        
        from pathlib import Path
        if Path(default_model).exists():
            return default_model
        
        return None  # No model available

    model_path = resolve_model_path(config, args.model)
    
    # Validate category filter if provided
    category_filter = args.category_filter
    category_filter_id = None
    if category_filter:
        # Import and refresh categories
        from annotator.definitions import refresh_categories, get_categories
        refresh_categories()
        categories = get_categories()
        
        # Check if the filter matches any category (case-insensitive)
        found = False
        for cat_id, cat_name in categories.items():
            if cat_name.lower() == category_filter.lower():
                category_filter_id = cat_id
                category_filter = cat_name  # Use the proper case
                found = True
                break
        
        if not found:
            logger.warning(f"Category filter '{category_filter}' not found in project categories")
            print(f"\nWarning: Category '{category_filter}' not recognized.")
            print(f"Available categories: {', '.join(categories.values()) if categories else 'None loaded'}")
            print("Proceeding without filter.\n")
            category_filter = None
            category_filter_id = None
        else:
            print(f"\nCategory filter active: Only allowing '{category_filter}' annotations")
            print("Note: All existing annotations will still be displayed\n")
    
    # Use config directly
    images_dir = config.path("raw_frames")
    annotations_file = config.path("annotations") # Store uses this path internally

    # --- Directory Checks (Optional - Store/Annotator might handle this) ---
    # Basic check for image directory existence
    if not images_dir.is_dir():
        logger.error(f"Images directory specified in configuration does not exist: {images_dir}")
        print(f"Error: Images directory '{images_dir}' not found.")
        print("Please check the configuration in your YAML file.")
        return # Exit if image dir is invalid

    # Ensure parent directory for annotations file exists (Store should handle this, but check is safe)
    try:
        annotations_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error(f"Failed to create parent directory for annotations file {annotations_file}: {e}")
        print(f"Error: Could not create directory for annotations file: {annotations_file.parent}")
        return

    # --- Instantiate Components ---
    try:
        logger.debug("Instantiating annotation components...")
        # 1. State (holds UI state)
        state = AnnotationState()

        # 2. Store (handles data load/save using path from config)
        store = AnnotationStore(annotations_file_path=annotations_file) # Pass path explicitly or let Store use config

        # 3. Renderer (handles drawing)
        renderer = AnnotationRenderer(state=state, store=store)

        # 4. Key Handler (needs state and store) - Filenames list will be set by Annotator later
        # Pass empty list initially, Annotator will update it.
        key_handler = AnnotatorKeyHandler(state=state, store=store, all_filenames=[], images_dir=images_dir)

        # 5. Annotator (main orchestrator, injects dependencies)
        #    It will load filenames and update the key_handler internally.
        annotator = UnifiedAnnotator(
            state=state,
            store=store,
            renderer=renderer,
            key_handler=key_handler,
            images_dir=images_dir,
            model_path=model_path,
            confidence_threshold=args.conf,
            category_filter=category_filter,
            category_filter_id=category_filter_id
            # window_name can be passed here if needed, defaults to 'Annotator'
        )
        logger.info("Annotation components instantiated successfully.")

    except Exception as e:
        logger.critical(f"Failed to initialize annotation components: {e}", exc_info=True)
        print(f"Error: Failed to initialize the annotator. Check logs for details.")
        return

    # --- Run the Annotator ---
    try:
        logger.info("Starting the annotation tool main loop...")
        annotator.run()
        logger.info("Annotation tool finished gracefully.")
    except Exception as e:
        logger.critical(f"An unexpected error occurred while running the annotator: {e}", exc_info=True)
        print(f"An error occurred during annotation. Check logs for details.")
    finally:
        # Ensure cleanup happens, though annotator.run() should handle cv2 windows
        logger.debug("Annotation script main function finished.")


if __name__ == "__main__":
    main()