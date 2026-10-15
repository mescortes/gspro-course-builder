"""The unit tests import the engine with Westmount's course file (several of them check its hand-made sources), so
the course is pinned here: a second courses/<slug>/ folder, or an exported COURSE, must not change what they test.
tests/test_config.py builds its own course trees and sets COURSE for each.

The built-course tests (tests/test_course.py) test whichever course is named with --course <slug> (default westmount):
`pytest --course <slug> tests/test_course.py` after `COURSE=<slug> scripts/build_all.py`. With another course only
test_course.py is collected: the unit tests are Westmount's."""
import os


def pytest_addoption(parser):
    parser.addoption("--course", default=None,
                     help="slug of a built course for tests/test_course.py (the unit tests stay on Westmount)")


def pytest_configure(config):
    os.environ["COURSE"] = config.getoption("--course") or "westmount"


def pytest_ignore_collect(collection_path, config):
    """True skips the file; None leaves the decision to pytest (--ignore and the defaults)."""
    other = config.getoption("--course") not in (None, "westmount")
    if other and collection_path.suffix == ".py" and collection_path.name != "test_course.py":
        return True
    return None
