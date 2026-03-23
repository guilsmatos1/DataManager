from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("datamanager")
except PackageNotFoundError:
    __version__ = "dev"
