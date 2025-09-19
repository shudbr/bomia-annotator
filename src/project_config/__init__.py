"""Configuration management modules."""

# Import the class but don't create the global instance here to avoid circular imports
from .project_categories import ProjectCategoryManager

__all__ = ["ProjectCategoryManager"]