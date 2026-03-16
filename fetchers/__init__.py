import pkgutil
import importlib
import inspect
from pathlib import Path
from .base import BaseFetcher

def get_all_fetchers():
    """
    Dynamically discovers and returns all Fetcher classes that inherit from BaseFetcher.
    """
    fetchers_classes = []
    # Get current directory of the fetchers package
    pkg_dir = str(Path(__file__).parent)
    
    # Iterate over all modules in the package
    for loader, module_name, is_pkg in pkgutil.iter_modules([pkg_dir]):
        if module_name in ["base"]:
            continue
            
        try:
            # Import the module dynamically
            # We use a relative import from the current package
            module = importlib.import_module(f".{module_name}", package=__package__)
            
            # Find all classes in the module that inherit from BaseFetcher
            for name, obj in inspect.getmembers(module):
                if (inspect.isclass(obj) and 
                    issubclass(obj, BaseFetcher) and 
                    obj is not BaseFetcher):
                    fetchers_classes.append(obj)
                    
        except ImportError as e:
            # If a fetcher cannot be imported due to missing dependencies, skip it
            # This makes the system robust to partial installations
            import logging
            logging.getLogger("DataManager").warning(f"Could not load fetcher module '{module_name}': {e}")
            
    return fetchers_classes
