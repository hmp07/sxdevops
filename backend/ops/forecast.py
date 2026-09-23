"""轻量时序预测工具（纯 stdlib）：线性回归外推 + 移动平均 + 阈值到达时间。

供演示环境与 AI 工具（query_resource_forecast）共用：输入升序的
(timestamp_seconds, value) 序列，输出趋势、置信区间与容量阈值外推。
刻意不引入 numpy/pandas，演示场景 1-7 天窗口线性回归足够。
"""
import math

# 阈值 ETA 外推的最大天数（防线性模型无限外推）
DEFAULT_MAX_ETA_DAYS = 30


def _fit(points):
    """拟合最近一段窗口的线性回归，返回 (slope, intercept, r2, rmse, window_points)。

    只取末尾一段（max(24, 60%)，不超过总数），避免长周期均值掩盖近期拐点。
    """
    n = len(points)
    if n < 2:
        raise ValueError('预测至少需要 2 个数据点')
    window = min(n, max(24, int(n * 0.6)))
    pts = points[-window:]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    w = len(pts)
    mean_x = sum(xs) / w
    mean_y = sum(ys) / w
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx else 0.0
    intercept = mean_y - slope * mean_x
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    r2 = 1.0 - ss_res / ss_tot if ss_tot else 0.0
    rmse = math.sqrt(ss_res / w) if ss_res > 0 else 0.0
    return slope, intercept, r2, rmse, pts


def _trend_label(points, slope, step):
    """按预测期总变化相对历史值幅度判定 up/down/flat。"""
    scale = max(abs(sum(v for _, v in points) / len(points)), 1e-9)
    total_delta = slope * step
    if total_delta > scale * 0.01:
        return 'up'
    if total_delta < -scale * 0.01:
        return 'down'
    return 'flat'


def linear_forecast(points, horizon_points=12, confidence=1.96):
    """线性回归外推。

    points: [(ts_seconds, value), ...] 升序。
    返回 dict: slope/intercept/r2/trend/rmse + forecast/upper/lower
    （[(ts, val), ...]，置信带宽 = rmse * confidence 常量带）。
    """
    if len(points) < 2:
        raise ValueError('预测至少需要 2 个数据点')
    slope, intercept, r2, rmse, window_pts = _fit(points)
    last_ts = points[-1][0]
    step = (points[-1][0] - points[0][0]) / max(1, len(points) - 1)
    forecast = []
    for i in range(1, horizon_points + 1):
        ts = last_ts + step * i
        forecast.append((ts, slope * ts + intercept))
    band = rmse * confidence
    return {
        'slope': slope,
        'intercept': intercept,
        'r2': r2,
        'rmse': rmse,
        'trend': _trend_label(window_pts, slope, step * horizon_points),
        'forecast': forecast,
        'upper': [(ts, v + band) for ts, v in forecast],
        'lower': [(ts, v - band) for ts, v in forecast],
    }


def threshold_eta(points, threshold, max_days=DEFAULT_MAX_ETA_DAYS):
    """线性外推到达阈值的剩余秒数。

    返回 float 秒；已超过阈值返回 0.0；趋势向下/持平或外推超过
    max_days 返回 None。
    """
    if len(points) < 2:
        raise ValueError('预测至少需要 2 个数据点')
    slope, intercept, _, _, _ = _fit(points)
    last_ts, last_val = points[-1]
    if last_val >= threshold:
        return 0.0
    if slope <= 0:
        return None
    eta_ts = (threshold - intercept) / slope
    if eta_ts <= last_ts:
        return 0.0
    if eta_ts > last_ts + max_days * 86400:
        return None
    return eta_ts - last_ts


def moving_average(points, window=5):
    """尾随窗口均值平滑，返回同形状 [(ts, avg), ...]。"""
    result = []
    for i in range(len(points)):
        start = max(0, i - window + 1)
        chunk = points[start:i + 1]
        avg = sum(v for _, v in chunk) / len(chunk)
        result.append((points[i][0], avg))
    return result


def summarize_series(points):
    """序列摘要：start/end/min/max/mean/last/direction/count。"""
    if not points:
        return {
            'start': None, 'end': None, 'min': None, 'max': None,
            'mean': None, 'last': None, 'direction': 'flat', 'count': 0,
        }
    values = [v for _, v in points]
    first, last = values[0], values[-1]
    scale = max(abs(sum(values) / len(values)), 1e-9)
    delta = last - first
    direction = 'up' if delta > scale * 0.01 else ('down' if delta < -scale * 0.01 else 'flat')
    return {
        'start': points[0][0],
        'end': points[-1][0],
        'min': min(values),
        'max': max(values),
        'mean': sum(values) / len(values),
        'last': last,
        'direction': direction,
        'count': len(points),
    }
