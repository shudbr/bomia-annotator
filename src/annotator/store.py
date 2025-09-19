# src/bomia/annotation/store.py
import json
import os
import logging
from typing import Dict, Any, Optional, Tuple, List
from pathlib import Path
import threading
from datetime import datetime
# Import config
try:
    from config import config
except ImportError:
    config = None
    DEFAULT_ANNOTATIONS_FILE_FALLBACK = Path("./data/annotated/annotations.json")
logger = logging.getLogger(__name__)

# Define annotation sources
ANNOTATION_SOURCE_HUMAN = "human"
ANNOTATION_SOURCE_INFERENCE = "inference"

# Default structure for a single annotation within the list
ANNOTATION_ENTRY_DEFAULT = {
    "annotation_source": None,
    "bbox": None, # [x1, y1, x2, y2]
    "category_id": None,
    "category_name": None
    # Subcategory keys are NOT here by default, added specifically later
}

# Default structure for a top-level file entry in the JSON
# --- MODIFIED: Removed top-level subcategory keys ---
FILE_ENTRY_DEFAULT = {
    "annotations": [], # List to hold multiple annotation entries
    "original_path": None,
    # "subcategory_id": None, # <-- REMOVED
    # "subcategory_name": None, # <-- REMOVED
    "created_at_iso": None,
    "updated_at_iso": None
}
# --- END MODIFICATION ---

class AnnotationStore:
    """
    Manages loading, saving, and accessing annotation data (new format with list)
    from a JSON file. Assumes the file only contains the new structure.
    Provides thread-safe access.
    """
    def __init__(self, annotations_file_path: Optional[Path] = None):
        if annotations_file_path:
            self.annotations_file = annotations_file_path
        elif config:
            try:
                # Use config.path to ensure directory creation logic is triggered
                self.annotations_file = config.path("annotations")
            except Exception as e:
                logger.error(f"Error getting annotations path from config: {e}. Using fallback.")
                self.annotations_file = DEFAULT_ANNOTATIONS_FILE_FALLBACK
        else:
            self.annotations_file = DEFAULT_ANNOTATIONS_FILE_FALLBACK
            logger.warning(f"Using fallback annotations file path: {self.annotations_file}")

        # Ensure parent directory exists *before* loading/saving
        try:
            self.annotations_file.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create parent directory for annotations file {self.annotations_file}: {e}")
            # Depending on severity, you might want to raise an error here

        # Holds the new structure: Dict[filename, Dict[str, Any]] where the inner dict contains 'annotations' list
        self._annotations: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.load_annotations()

    def load_annotations(self) -> None:
        """
        Loads annotations from the JSON file into memory.
        Assumes the file is already in the new format:
        {filename: {"annotations": [...], "original_path": ..., ...}}
        """
        with self._lock:
            self._annotations = {} # Start fresh
            if not self.annotations_file.exists():
                logger.info(f"Annotations file not found at {self.annotations_file}. Initializing empty store.")
                return

            try:
                with open(self.annotations_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"Error reading or decoding JSON from {self.annotations_file}. Initializing empty store.", exc_info=True)
                return
            except Exception as e:
                logger.error(f"Unexpected error loading annotations from {self.annotations_file}: {e}. Initializing empty store.", exc_info=True)
                return

            if not isinstance(data, dict):
                logger.error(f"Annotations file {self.annotations_file} does not contain a valid JSON dictionary. Initializing empty store.")
                return

            # Basic validation: Check if entries look like the new format
            valid_entries = 0
            invalid_entries = 0
            for filename, file_data in data.items():
                # --- Updated Validation ---
                # Check if it's a dictionary and HAS an 'annotations' key which IS a list
                if isinstance(file_data, dict) and "annotations" in file_data and isinstance(file_data.get("annotations"), list):
                    # Optional: Deeper validation of items within the annotations list if needed
                    self._annotations[filename] = file_data
                    valid_entries += 1
                # --- End Updated Validation ---
                else:
                    logger.warning(f"Skipping entry for '{filename}': does not match expected new format (must be dict with 'annotations' list). Data: {file_data}")
                    invalid_entries += 1

            logger.info(f"Annotation loading complete. Loaded {valid_entries} valid entries. Skipped {invalid_entries} invalid/malformed entries.")


    def save_annotations(self) -> bool:
        """Saves the current in-memory annotations (new structure) to the JSON file."""
        with self._lock:
            # Sort the dictionary by filename before saving for consistency
            data_to_save = dict(sorted(self._annotations.items()))
            try:
                # Ensure parent directory exists (might be redundant, but safe)
                self.annotations_file.parent.mkdir(parents=True, exist_ok=True)
                # --- Use atomic write pattern ---
                temp_file_path = self.annotations_file.with_suffix(f".{os.getpid()}.tmp")
                with open(temp_file_path, 'w', encoding='utf-8') as f:
                    # Use indent=2 for readability, ensure_ascii=False for unicode
                    json.dump(data_to_save, f, indent=2, ensure_ascii=False)
                # Replace the original file with the temporary file atomically
                os.replace(temp_file_path, self.annotations_file)
                # --- End atomic write ---
                logger.debug(f"Successfully saved {len(self._annotations)} file entries to {self.annotations_file}")
                return True
            except Exception as e:
                logger.error(f"Error saving annotations to {self.annotations_file}: {e}", exc_info=True)
                # Clean up temporary file if it exists and save failed
                if 'temp_file_path' in locals() and Path(temp_file_path).exists():
                    try:
                        os.remove(temp_file_path)
                        logger.debug(f"Removed temporary save file: {temp_file_path}")
                    except OSError:
                        logger.error(f"Failed to remove temporary save file: {temp_file_path}")
                return False

    def get_annotation_data_for_file(self, filename: str) -> Dict[str, Any]:
        """
        Gets all data associated with a filename, including the list of annotations,
        original_path, etc.
        Returns a copy of the dictionary for the file, or an empty dict if not found.
        """
        with self._lock:
            entry = self._annotations.get(filename)
            # Using json load/dump for a simple deep copy is generally safe for JSON-serializable data
            # For very large datasets or performance-critical code, consider copy.deepcopy if needed
            return json.loads(json.dumps(entry)) if entry else {}

    def _ensure_file_entry(self, filename: str) -> Dict[str, Any]:
        """
        Ensures an entry for the filename exists in the internal dictionary.
        Initializes with the default new structure if it's a new file.
        Updates the top-level 'updated_at_iso' timestamp.
        Assumes lock is already held by the caller.
        Returns the dictionary entry for the filename.
        """
        now_iso = datetime.now().isoformat()
        if filename not in self._annotations:
            logger.debug(f"Creating new entry for filename: {filename}")
            # --- MODIFIED: Use updated FILE_ENTRY_DEFAULT ---
            self._annotations[filename] = FILE_ENTRY_DEFAULT.copy()
            self._annotations[filename]["annotations"] = [] # Ensure list exists
            self._annotations[filename]["created_at_iso"] = now_iso
            self._annotations[filename]["updated_at_iso"] = now_iso
            # --- END MODIFICATION ---
        else:
            # Update timestamp even if entry exists
            self._annotations[filename]["updated_at_iso"] = now_iso

        # Ensure essential keys exist if loading older/partial data (less likely now)
        if "annotations" not in self._annotations[filename] or not isinstance(self._annotations[filename].get("annotations"), list):
             self._annotations[filename]["annotations"] = []
        # Add checks for other FILE_ENTRY_DEFAULT keys if necessary

        return self._annotations[filename]


    def add_annotation(
        self,
        filename: str,
        bbox: Tuple[int, int, int, int],
        category_id: Optional[str], # Allow None initially
        category_name: Optional[str], # Allow None initially
        original_path: str, # Absolute path from caller
        annotation_source: str = ANNOTATION_SOURCE_HUMAN,
    ) -> None:
        """
        Adds a new annotation dictionary to the 'annotations' list for the given file.
        Updates file-level original_path and timestamps. Saves changes.
        Initial category can be None.
        """
        relative_path_str = original_path # Default if conversion fails or config missing

        # --- Convert absolute path to relative ---
        if config and config.root_dir:
            original_path_abs = Path(original_path)
            try:
                # Ensure root_dir is absolute for reliable comparison
                abs_root_dir = config.root_dir.resolve()
                if original_path_abs.is_absolute():
                     relative_path = original_path_abs.relative_to(abs_root_dir)
                     relative_path_str = relative_path.as_posix() # Use POSIX separators
                else:
                    # If original_path is already relative, assume it's relative to root
                    # (This might need adjustment based on how original_path is generated)
                    relative_path_str = Path(original_path).as_posix()
                    logger.debug(f"Assuming '{original_path}' is already relative to root for {filename}.")

            except ValueError:
                logger.warning(f"Original path '{original_path}' not relative to project root '{config.root_dir}'. Storing as provided/absolute for {filename}.")
                relative_path_str = Path(original_path).as_posix() # Store as is, using posix separators
            except Exception as e:
                logger.error(f"Error calculating relative path for {original_path} (file: {filename}): {e}. Storing as provided/absolute.", exc_info=True)
                relative_path_str = Path(original_path).as_posix()
        else:
            logger.warning(f"Config or config.root_dir not available. Storing path as provided for {filename}.")
            relative_path_str = Path(original_path).as_posix()
        # --- End path conversion ---

        with self._lock:
            file_entry = self._ensure_file_entry(filename) # Gets existing or creates new

            # Update top-level original_path (Store relative path)
            file_entry['original_path'] = relative_path_str

            # Create the new annotation entry dictionary
            new_annotation = ANNOTATION_ENTRY_DEFAULT.copy()
            new_annotation['bbox'] = list(bbox) # Ensure it's a list
            new_annotation['category_id'] = category_id # Store even if None initially
            new_annotation['category_name'] = category_name # Store even if None initially
            new_annotation['annotation_source'] = annotation_source

            # Add the new annotation to the list
            file_entry['annotations'].append(new_annotation)
            logger.debug(f"Added annotation to '{filename}': {new_annotation}")

            # Timestamp already updated by _ensure_file_entry
            needs_save = True

        if needs_save:
            self.save_annotations()

    def clear_annotations(self, filename: str) -> None:
        """
        Removes ALL annotations from the 'annotations' list for the given file.
        Keeps other file-level data. Saves changes.
        """
        needs_save = False
        with self._lock:
            if filename in self._annotations:
                file_entry = self._annotations[filename]
                # Check if 'annotations' key exists and is a non-empty list
                if isinstance(file_entry.get("annotations"), list) and file_entry["annotations"]:
                    num_cleared = len(file_entry["annotations"])
                    logger.info(f"Clearing {num_cleared} annotations for {filename}.")
                    file_entry["annotations"] = [] # Set to empty list
                    file_entry["updated_at_iso"] = datetime.now().isoformat()
                    needs_save = True
                else:
                    logger.info(f"No annotations list found or already empty for {filename}. No changes made.")
            else:
                logger.info(f"No entry found for frame {filename} to clear.")

        if needs_save:
            self.save_annotations()

    def update_last_annotation_category(
        self,
        filename: str,
        category_id: str,
        category_name: str
    ) -> bool:
        """
        Updates the category for the *last* annotation in the list for the given file.
        Sets the source to human and saves the changes.
        Args:
            filename: The name of the file to update.
            category_id: The new category ID.
            category_name: The new category name.
        Returns:
            True if the last annotation was successfully updated, False otherwise
            (e.g., if the annotations list was empty).
        """
        needs_save = False
        updated = False
        with self._lock:
            if filename in self._annotations:
                file_entry = self._annotations[filename] # Get entry directly
                annotations_list = file_entry.get("annotations")

                if isinstance(annotations_list, list) and annotations_list: # Check if list exists and is not empty
                    last_annotation = annotations_list[-1] # Get the last item

                    # Ensure last_annotation is a dictionary before proceeding
                    if not isinstance(last_annotation, dict):
                         logger.error(f"Last item in annotations list for {filename} is not a dictionary: {last_annotation}. Cannot update.")
                         return False

                    # Check if values actually changed
                    if (last_annotation.get('category_id') != category_id or
                        last_annotation.get('category_name') != category_name or
                        last_annotation.get('annotation_source') != ANNOTATION_SOURCE_HUMAN):

                        last_annotation['category_id'] = category_id
                        last_annotation['category_name'] = category_name
                        last_annotation['annotation_source'] = ANNOTATION_SOURCE_HUMAN # Assume human classified

                        # Ensure file's main timestamp is updated
                        file_entry["updated_at_iso"] = datetime.now().isoformat()
                        needs_save = True
                        updated = True
                        logger.debug(f"Updating last annotation category for {filename} to ID: {category_id}, Name: {category_name}")
                    else:
                         logger.debug(f"Last annotation for {filename} already has category ID: {category_id}. No update needed.")
                else:
                    logger.warning(f"Cannot update last annotation category for {filename}: annotations list is empty or invalid.")
            else:
                logger.warning(f"Cannot update last annotation category for {filename}: file entry does not exist.")

        if needs_save:
            self.save_annotations()
        return updated

    def update_annotation_category_by_index(
        self,
        filename: str,
        index: int,
        category_id: str,
        category_name: str
    ) -> bool:
        """
        Updates the category for the annotation at the specified index.
        Sets the source to human and saves the changes.
        Args:
            filename: The name of the file to update.
            index: The index of the annotation to update (0-based).
            category_id: The new category ID.
            category_name: The new category name.
        Returns:
            True if the annotation was successfully updated, False otherwise.
        """
        needs_save = False
        updated = False
        with self._lock:
            if filename in self._annotations:
                file_entry = self._annotations[filename]
                annotations_list = file_entry.get("annotations")

                if isinstance(annotations_list, list) and 0 <= index < len(annotations_list):
                    annotation = annotations_list[index]

                    # Ensure annotation is a dictionary before proceeding
                    if not isinstance(annotation, dict):
                        logger.error(f"Annotation at index {index} for {filename} is not a dictionary: {annotation}. Cannot update.")
                        return False

                    # Check if values actually changed
                    if (annotation.get('category_id') != category_id or
                        annotation.get('category_name') != category_name or
                        annotation.get('annotation_source') != ANNOTATION_SOURCE_HUMAN):

                        annotation['category_id'] = category_id
                        annotation['category_name'] = category_name
                        annotation['annotation_source'] = ANNOTATION_SOURCE_HUMAN  # Mark as human-updated
                        logger.info(f"Updated annotation at index {index} category to {category_id} ('{category_name}') for {filename}")
                        updated = True
                        needs_save = True
                    else:
                        logger.debug(f"No change needed for annotation at index {index} in {filename} - already has category {category_id}")
                else:
                    logger.warning(f"Cannot update annotation for {filename}: index {index} out of range (0-{len(annotations_list)-1 if annotations_list else 0})")
            else:
                logger.warning(f"Cannot update annotation for {filename}: file not found in store.")

        # Save annotations after modification
        if needs_save:
            self.save_annotations()
        return updated

    def delete_annotation_by_index(
        self,
        filename: str,
        index: int
    ) -> bool:
        """
        Deletes the annotation at the specified index from the annotations list.
        Args:
            filename: The name of the file to update.
            index: The index of the annotation to delete (0-based).
        Returns:
            True if the annotation was successfully deleted, False otherwise.
        """
        needs_save = False
        deleted = False
        with self._lock:
            if filename in self._annotations:
                file_entry = self._annotations[filename]
                annotations_list = file_entry.get("annotations")

                if isinstance(annotations_list, list) and 0 <= index < len(annotations_list):
                    # Delete the annotation at the specified index
                    deleted_annotation = annotations_list.pop(index)
                    logger.info(f"Deleted annotation at index {index} for {filename}: {deleted_annotation}")
                    
                    # Update timestamp
                    file_entry["updated_at_iso"] = datetime.now().isoformat()
                    deleted = True
                    needs_save = True
                else:
                    logger.warning(f"Cannot delete annotation for {filename}: index {index} out of range (0-{len(annotations_list)-1 if annotations_list else 0})")
            else:
                logger.warning(f"Cannot delete annotation for {filename}: file not found in store.")

        # Save annotations after modification
        if needs_save:
            self.save_annotations()
        return deleted

    # --- REMOVED update_file_subcategory method ---
    # def update_file_subcategory(
    #     self,
    #     filename: str,
    #     subcategory_id: str,
    #     subcategory_name: str
    # ) -> bool:
    #     """
    #     REMOVED - Updates the top-level subcategory information for a given file entry.
    #     This is no longer the correct place for subcategory info.
    #     """
    #     logger.warning("DEPRECATED: update_file_subcategory called. Subcategories should be updated within annotation entries.")
    #     return False # Indicate failure or do nothing
    # --- END REMOVED ---

    def _has_annotation_data(self, filename: str) -> bool:
        """Checks if a file entry has any annotations in its list."""
        # Assumes lock is held
        entry = self._annotations.get(filename, {})
        return isinstance(entry.get("annotations"), list) and bool(entry["annotations"])

    def find_next_annotated_index(self, start_index: int, all_filenames: List[str]) -> Optional[int]:
        """Finds the index of the next file with at least one annotation."""
        # No changes needed
        with self._lock:
            for i in range(start_index + 1, len(all_filenames)):
                if self._has_annotation_data(all_filenames[i]):
                    return i
        return None

    def find_prev_annotated_index(self, start_index: int, all_filenames: List[str]) -> Optional[int]:
        """Finds the index of the previous file with at least one annotation."""
        # No changes needed
        with self._lock:
            for i in range(start_index - 1, -1, -1):
                if self._has_annotation_data(all_filenames[i]):
                    return i
        return None

    def get_statistics(self) -> Dict[str, Any]:
        """Calculates statistics based on the current multi-annotation structure."""
        with self._lock:
            stats: Dict[str, Any] = {
                "total_files_in_store": len(self._annotations),
                "total_files_with_any_annotation": 0,
                "total_annotations": 0, # Total individual annotation dicts across all files
                "total_files_with_bbox": 0, # Files containing at least one annotation with a bbox
                "category_counts": {}, # Count of each category across all annotations
                "subcategory_counts": {} # Count of each subcategory found *within* annotations
            }
            category_counts: Dict[str, int] = {}
            subcategory_counts: Dict[str, int] = {} # <-- Modified: counts subcats inside annotations

            for filename, file_data in self._annotations.items():
                if not isinstance(file_data, dict): continue

                annotations_list = file_data.get("annotations", [])
                if not isinstance(annotations_list, list): continue # Skip if 'annotations' isn't a list

                # File-level checks
                has_any_annotation_in_list = bool(annotations_list)
                has_any_bbox_in_list = False

                if has_any_annotation_in_list:
                    stats["total_files_with_any_annotation"] += 1
                    stats["total_annotations"] += len(annotations_list)

                    # Iterate through individual annotations in the list
                    for annotation_entry in annotations_list:
                        if not isinstance(annotation_entry, dict): continue

                        # Check for bbox within this annotation
                        if annotation_entry.get('bbox'):
                            has_any_bbox_in_list = True

                        # Count category from this annotation
                        cat_name = annotation_entry.get('category_name', 'Unknown_Category')
                        if annotation_entry.get('category_id') is not None: # Only count if category is set
                             key = f"{cat_name}"
                             category_counts[key] = category_counts.get(key, 0) + 1

                        # --- MODIFIED: Count subcategory from this annotation ---
                        subcat_name = annotation_entry.get('subcategory_name')
                        if subcat_name: # Only count if subcategory_name exists and is not None/empty
                            subcategory_counts[subcat_name] = subcategory_counts.get(subcat_name, 0) + 1
                        # --- END MODIFICATION ---

                # Update file-level stats after checking all annotations in its list
                if has_any_bbox_in_list:
                    stats["total_files_with_bbox"] += 1

            stats["category_counts"] = category_counts
            stats["subcategory_counts"] = subcategory_counts # Store the counts derived from within annotations
            return stats