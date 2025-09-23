
import random

class ChannelPolicy:

    def __init__(self, cfg):
        self.cfg = cfg

    def sample_delay(self):
        if self.cfg.jitter == 0:
            return self.cfg.delay
        low = max(0.0, self.cfg.delay - self.cfg.jitter)
        high = self.cfg.delay + self.cfg.jitter
        return random.uniform(low, high)

    def will_drop(self):
        return random.random() < self.cfg.loss_prob

    def will_corrupt(self):
        return random.random() < self.cfg.corrupt_prob