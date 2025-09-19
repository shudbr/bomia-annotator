# src/bomia/annotation/definitions.py

# Dynamic categories based on active project
from project_config import ProjectCategoryManager

# Create a lazy-loaded category manager
_category_manager = None

def _get_category_manager():
    """Get or create the category manager instance."""
    global _category_manager
    if _category_manager is None:
        # Import config here to avoid circular import
        from config import config
        _category_manager = ProjectCategoryManager(config)
        _category_manager.reload_categories()
    return _category_manager

def get_categories():
    """Get categories for the current project."""
    return _get_category_manager().get_categories()

def get_subcategories():
    """Get subcategories for the current project."""
    return _get_category_manager().get_subcategories()

# For backward compatibility - these will be populated on first access
CATEGORIES = {}
SUBCATEGORIES = {}

# Function to refresh the module-level constants
def refresh_categories():
    """Refresh the module-level CATEGORIES and SUBCATEGORIES."""
    global CATEGORIES, SUBCATEGORIES
    CATEGORIES = get_categories()
    SUBCATEGORIES = get_subcategories()

# Note: UI Colors and Window Size settings are now managed via
# bomia.config.AnnotationSettings and potentially AnnotationRenderer defaults.
# The problematic tkinter logic for screen size detection has been removed.