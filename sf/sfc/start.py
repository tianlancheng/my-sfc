# fix Python 3 relative imports inside packages
# CREDITS: http://stackoverflow.com/a/6655098/4183498
import os
import sys
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, parent_dir)
import sfc  # noqa
__package__ = 'sfc'


from sfc.common.launcher import start_sf


def start():
    start_sf('firewall', '0.0.0.0', 6001, 'firewall')

if __name__ == "__main__":
    start()
