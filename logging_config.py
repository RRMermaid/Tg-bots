import logging

def setup_logging():
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # HTTP request URLs contain Telegram credentials; never log those.
    for name in ("httpx","httpcore","telegram"):
        logging.getLogger(name).setLevel(logging.WARNING)
