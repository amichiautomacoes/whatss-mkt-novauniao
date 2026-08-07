import random
import time


def wait_between_messages(base_delay_seconds: int) -> None:
    jitter = random.uniform(0.75, 1.35)
    time.sleep(max(1, base_delay_seconds * jitter))
