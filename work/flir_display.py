"""Host-side display AGC. Never modifies radiometry or recorded RAW frames.

Plateau HEQ and CLAHE are implemented here, not FLIR's proprietary pipeline.
All ranges are in Celsius; colour levels are 0..255. Only range adaptation
has temporal state: there is no frame queue or temporal image ghosting.
"""
import math
import time

import numpy as np

MODES = ('Auto', 'Detail', 'Linear auto', 'Manual', 'Background relative')


def migrate_mode(name):
    aliases = {'FLIR HEQ': 'Auto', 'Wall detail': 'Linear auto',
               'Auto (2–98%)': 'Linear auto', 'Auto adaptive': 'Auto',
               'Scene min–max': 'Linear auto'}
    name = aliases.get(name, name)
    return name if name in MODES else 'Auto'


def _clipped_cdf(hist, limit):
    """Plateau clipping with uniform redistribution; monotone bounded LUT."""
    cap = max(1., hist.sum() / hist.size * limit)
    clipped = np.minimum(hist, cap)
    clipped += (hist.sum() - clipped.sum()) / hist.size
    # Bin-centred integration avoids lifting a constant scene to full white.
    return (np.cumsum(clipped) - .5 * clipped) / max(clipped.sum(), 1.)


def _clahe(image, limit):
    """4x4 tiles, clipped CDFs, bilinear interpolation between tile centres."""
    h, w = image.shape
    ny, nx = min(4, h), min(4, w)
    ys, xs = np.linspace(0, h, ny + 1, dtype=int), np.linspace(0, w, nx + 1, dtype=int)
    indices = np.clip(np.rint(image * 255), 0, 255).astype(np.int32)
    luts = np.empty((ny, nx, 256), dtype=float)
    for y in range(ny):
        for x in range(nx):
            tile = indices[ys[y]:ys[y+1], xs[x]:xs[x+1]]
            luts[y, x] = _clipped_cdf(np.bincount(tile.ravel(), minlength=256), limit)
    def axes(edges, length):
        centres = (edges[:-1] + edges[1:] - 1) / 2
        pos = np.interp(np.arange(length), centres, np.arange(len(centres)))
        first = np.floor(pos).astype(int)
        return first, np.minimum(first + 1, len(centres)-1), pos - first
    y0, y1, fy = axes(ys, h)
    x0, x1, fx = axes(xs, w)
    top = luts[y0[:, None], x0, indices] * (1-fx) + luts[y0[:, None], x1, indices] * fx
    bottom = luts[y1[:, None], x0, indices] * (1-fx) + luts[y1[:, None], x1, indices] * fx
    return top * (1-fy[:, None]) + bottom * fy[:, None]


def _denoise(image, strength):
    """Small bilateral kernel on temperature, before colour mapping.

    Fixed .15 C range sigma is a display preference, not a claimed NETD.
    Large differences retain their weight; spatial processing adds no frames.
    """
    amount = np.clip(strength / 100., 0., 1.)
    if amount == 0:
        return image
    h, w = image.shape
    pad = np.pad(image, 1, mode='edge')
    total, weights = image.copy(), np.ones_like(image)
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
        other = pad[1+dy:1+dy+h, 1+dx:1+dx+w]
        weight = np.exp(-.5 * ((other-image) / .15)**2) * (.5 if dy and dx else .75)
        total += weight * other
        weights += weight
    return image * (1-amount) + total / weights * amount


class ToneMapper:
    def __init__(self):
        self.reset()

    def reset(self):
        self.bounds = None
        self.stamp = None
        self.key = None

    def map(self, temperatures, width, height, *, mode='Auto', low=15., high=35.,
            tone=0., span=100., contrast=1.5, min_span=1.5, detail=35., denoise=30.,
            temporal=True, now=None):
        mode = migrate_mode(mode)
        raw = np.asarray(temperatures, dtype=float).reshape(height, width)
        finite = np.isfinite(raw)
        valid = raw[finite]
        if not valid.size:
            return np.zeros(raw.size, dtype=np.uint8), 0., 1.
        centre = float(np.median(valid))
        clean = np.where(finite, raw, centre)
        # Manual is an exact temperature-to-colour mapping (no spatial filter).
        image = clean if mode == 'Manual' else _denoise(clean, denoise)
        if mode == 'Manual':
            low, high = float(low), float(high)
            if not math.isfinite(low) or not math.isfinite(high) or high <= low:
                raise ValueError('Manual maximum must be greater than minimum')
        else:
            low, high = np.quantile(valid, [.001, .999])
            floor = max(.1, float(min_span))
            if high-low < floor:
                low, high = centre-floor/2, centre+floor/2
            now = time.monotonic() if now is None else now
            key = (mode, floor)
            if temporal and self.bounds is not None and self.key == key:
                pl, ph = self.bounds
                # A real scene cut must not spend seconds clipped to old limits.
                cut = abs((low+high-pl-ph)/2) > max(3., 1.5*(ph-pl))
                if not cut:
                    a = 1-math.exp(-max(0., now-self.stamp)/.25)
                    low, high = pl+a*(low-pl), ph+a*(high-ph)
            if temporal:
                self.bounds, self.stamp, self.key = (float(low), float(high)), now, key
        linear = (image-low) / (high-low)
        mapped = linear
        if mode in ('Auto', 'Detail'):
            linear = np.clip(linear, 0., 1.)
            limit = float(np.clip(contrast, 1., 4.))
            idx = np.clip(np.rint(linear*255), 0, 255).astype(int)
            hist = np.bincount(idx[finite], minlength=256)
            cdf = _clipped_cdf(hist, limit)
            # Histogram clipping bounds the noise gain; linear blend retains
            # scene structure and unpopulated parts of the temperature range.
            mapped = .4*linear + .6*np.interp(linear*255, np.arange(256), cdf)
            if mode == 'Detail':
                amount = float(np.clip(detail/100., 0., 1.))
                mapped = (1-amount)*mapped + amount*_clahe(linear, limit)
        display_span = float(np.clip(span, 25., 400.))/100.
        shift = float(np.clip(tone, -100., 100.))*.006
        adjusted = .5 + (mapped-.5)/display_span + shift
        out = np.rint(np.clip(adjusted, 0., 1.)*255).astype(np.uint8)
        out[~finite] = 0
        # Report the actual black/white limits in the linear modes. Nonlinear
        # modes return their histogram domain, not a fictitious linear legend.
        if mode in ('Manual', 'Linear auto'):
            mid, size = (low+high)/2, high-low
            low, high = mid+(-.5-shift)*display_span*size, mid+(.5-shift)*display_span*size
        return out.ravel(), float(low), float(high)
