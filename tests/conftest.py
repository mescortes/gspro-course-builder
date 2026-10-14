"""The unit tests import the engine with Westmount's course file (several of them check its hand-made sources), so
the course is pinned here: a second courses/<slug>/ folder, or an exported COURSE, must not change what they test.
tests/test_config.py builds its own course trees and sets COURSE for each."""
import os

os.environ["COURSE"] = "westmount"
