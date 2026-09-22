"""RC epochs, atomic commands and monotonic deadman regressions."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from command_injector import CommandInjector


class RCTests(unittest.TestCase):
    def setUp(self):
        self.frames = []
        self.rc = CommandInjector(lambda frame: self.frames.append(frame) or True)
        self.rc.enabled = True
        self.safe = dict(enumerate(self.rc.failsafe_us, 1))
        self.epoch = self.rc.acquire('a', self.safe)

    def test_deadman_cannot_revive_throttle(self):
        self.rc.set_channels({**self.safe, 3: 1700}, 'a', self.epoch)
        self.rc._last_cmd_ts -= 1
        with self.assertRaises(ValueError):
            self.rc.set_channels({'roll': 1600}, 'a', self.epoch)
        self.assertEqual(self.rc._channels_us[2], 988)
        with self.assertRaises(ValueError):
            self.rc.set_channels({**self.safe, 3: 1700}, 'a', self.epoch)
        epoch = self.rc.acquire('a', self.safe)
        self.assertNotEqual(epoch, self.epoch)

    def test_ownership_and_atomic_validation(self):
        for channels, owner, epoch in [
            (self.safe, 'b', self.epoch),
            (self.safe, 'a', 'old'),
            ({**self.safe, 16: float('nan')}, 'a', self.epoch),
            ({'roll': 1600}, 'a', self.epoch),
        ]:
            with self.assertRaises(ValueError):
                self.rc.set_channels(channels, owner, epoch)
            self.assertEqual(self.rc._channels_us, list(self.safe.values()))

    def test_wall_clock_jump_does_not_expire_command(self):
        with patch('time.time', return_value=1e20):
            self.assertFalse(self.rc.failsafe_active)

    def test_release_owner_immediate_safe_frame(self):
        self.rc.set_channels({**self.safe, 3: 1700}, 'a', self.epoch)
        self.rc.release('b')
        self.assertFalse(self.frames)
        self.rc.release('a')
        self.assertTrue(self.rc.failsafe_active)
        self.assertAlmostEqual(self.rc.unpack_rc_frame(self.frames[-1])[2], 988, delta=1)

    def test_acquire_requires_safe_full_state(self):
        self.rc.reset()
        for channels in [{'roll': 1500}, {**self.safe, 3: 1700}]:
            with self.assertRaises(ValueError):
                self.rc.acquire('a', channels)


if __name__ == '__main__':
    unittest.main()
