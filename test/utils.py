import time
import itertools

def sleep_try(sleep_interval, max_time, test_func):
    max_count = float(max_time) / sleep_interval
    for counter in itertools.count():
        try:
            time.sleep(sleep_interval)
            test_func()
            return
        except:
            if counter >= max_count:
                raise


