

class LaunchAllPool(object):
    def __init__(self, shepherd):
        self.shepherd = shepherd

    def start(self, reqid):
        self.shepherd.start_flock(reqid)

    def stop(self, reqid):
        self.shepherd.stop_flock(reqid)
