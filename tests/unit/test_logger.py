import logging
import os
import json
from datamanager.utils.logger import setup_logger

def test_setup_logger():
    logger = setup_logger("TestLogger")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "TestLogger"
    assert len(logger.handlers) >= 2 # Console and File

def test_json_formatter(tmp_path):
    # Ensure we don't interfere with the global logger if possible, 
    # but setup_logger is designed to be global-ish for the name.
    log_file = tmp_path / "test.log"
    logger = logging.getLogger("TestJSON")
    logger.setLevel(logging.INFO)
    
    from datamanager.utils.logger import _JSONFormatter
    handler = logging.FileHandler(log_file)
    handler.setFormatter(_JSONFormatter())
    logger.addHandler(handler)
    
    logger.info("Test message")
    
    with open(log_file, "r") as f:
        line = f.readline()
        data = json.loads(line)
        assert data["message"] == "Test message"
        assert "time" in data
        assert data["level"] == "INFO"
