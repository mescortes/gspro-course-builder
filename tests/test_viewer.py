"""Static checks of the viewer's settings (viewer/index.html is not run headless in the unit tests)."""
import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "viewer" / "index.html").read_text()


def test_ponds_are_calm_silvery_mirrors():
    """The hole 3 pond read as a choppy blue sea: large blobs of sky in strongly distorted reflections. A small
    golf-course pond is near calm: fine ripples (Water.js `size` >= 10), weak distortion (<= 0.15), and a dark,
    neutral water colour so the reflected sky reads silver-grey rather than saturated blue."""
    m = re.search(r"new Water\(g, \{(.*?)\}\);", HTML, re.S)
    assert m
    opts = m.group(1)
    dist = float(re.search(r"distortionScale:\s*([\d.]+)", opts).group(1))
    col = int(re.search(r"waterColor:\s*0x([0-9a-fA-F]{6})", opts).group(1), 16)
    size = float(re.search(r"uniforms\.size\.value\s*=\s*([\d.]+)", HTML).group(1))
    r, g, b = col >> 16, (col >> 8) & 255, col & 255
    assert dist <= 0.15 and size >= 10
    assert max(r, g, b) <= 0x40 and max(r, g, b) - min(r, g, b) <= 0x18
    # the reflected sky is partly desaturated in the Water shader (silver, not postcard blue)
    k = re.search(r"reflectionSample = mix\( reflectionSample, vec3\( dot\( reflectionSample, vec3\( 0\.2126, 0\.7152, 0\.0722 \) \) \), ([\d.]+) \)", HTML)
    assert k and 0.2 <= float(k.group(1)) <= 0.7
