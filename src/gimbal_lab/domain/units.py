"""Central unit conversions. Geometry translations use mm; trig uses radians."""
import numpy as np


def finite_array(value, label="数值") -> np.ndarray:
    array = np.asarray(value)
    if array.dtype.kind not in "iuf" or not np.all(np.isfinite(array)):
        raise ValueError(f"{label} 必须为有限实数")
    return array.astype(float, copy=True)


def _scale(value, factor):
    result = finite_array(value) * factor
    if not np.all(np.isfinite(result)):
        raise ValueError("单位转换结果超出有限数值范围")
    return float(result) if result.ndim == 0 else result


def mm_to_m(value):
    return _scale(value, 0.001)


def m_to_mm(value):
    return _scale(value, 1000.0)


def deg_to_rad(value):
    return _scale(value, np.pi / 180.0)


def rad_to_deg(value):
    return _scale(value, 180.0 / np.pi)

