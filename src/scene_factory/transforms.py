"""Pure TRS matrix resolution; Blender-independent, column-vector convention."""
import math


def multiply(a, b):
    # Python 3.12 changed built-in sum(float) accuracy. fsum plus a versioned
    # rounding rule yields the same plan in app 3.12 and Blender 3.11.
    return [[round(math.fsum(a[i][k] * b[k][j] for k in range(4)),12) for j in range(4)] for i in range(4)]


def identity():
    return [[float(i == j) for j in range(4)] for i in range(4)]


def trs(transform):
    x, y, z = [math.radians(v) for v in transform["rotation_degrees"]]
    cx, cy, cz = math.cos(x), math.cos(y), math.cos(z)
    sx, sy, sz = math.sin(x), math.sin(y), math.sin(z)
    rx = [[1,0,0,0],[0,cx,-sx,0],[0,sx,cx,0],[0,0,0,1]]
    ry = [[cy,0,sy,0],[0,1,0,0],[-sy,0,cy,0],[0,0,0,1]]
    rz = [[cz,-sz,0,0],[sz,cz,0,0],[0,0,1,0],[0,0,0,1]]
    result = multiply(multiply(rz, ry), rx)
    for i in range(3):
        for j in range(3):
            result[i][j] = round(result[i][j] * transform["scale"][j],12)
        result[i][3] = transform["location"][i]
    return result
