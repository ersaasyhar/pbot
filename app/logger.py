import logging
import sys

def get_logger():
    # Use standard logging config
    logger = logging.getLogger("scanner")
    logger.setLevel(logging.INFO)

    # Prevent duplicate handlers if called multiple times
    if not logger.handlers:
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

        # Console Handler
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

        # File Handler
        fh = logging.FileHandler("collector.log")
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger
