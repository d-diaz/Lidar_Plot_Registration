"""Functions for creating 3D geometric representations of trees."""

import json
import subprocess
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
import pdal
from shapely.geometry import Point, Polygon


def arrays_equal_shape(*args, raise_exc=True):
    """Confirms all inputs, when converted to arrays, have equal shape.

    Parameters
    -----------
    args : array-like
        any arguments that can be converted to arrays with np.asanyarray
    raise_exc : boolean
        whether to raise a ValueError exception

    Returns
    --------
    result : bool
        whether or not all args have same shape

    """
    arrs = [np.asanyarray(arg) for arg in args]
    shapes = np.array([arr.shape for arr in arrs])
    equal_shapes = np.all(shapes == shapes[0])

    if not equal_shapes and raise_exc:
        raise ValueError('Input shapes mismatch: {}'.format(shapes))

    return equal_shapes


def get_raster_bbox_as_polygon(path_to_raster):
    """Returns a Shapely Polygon defining the bounding box of a raster

    Parameters
    ----------
    path_to_raster : string, path to file
        A raster image that can be read by rasterio.

    Returns
    --------
    bbox : shapely Polygon object
        A polygon describing the bounding box of the raster
    """
    with rasterio.open(path_to_raster) as raster_src:
        pass

    bounds = raster_src.bounds
    points = [
        Point(bounds[0], bounds[1]),  # lower left corner
        Point(bounds[0], bounds[3]),  # upper left corner
        Point(bounds[2], bounds[3]),  # upper right corner
        Point(bounds[2], bounds[1])  # lower left corner
    ]

    bbox = Polygon([(p.x, p.y) for p in points])
    return bbox


def get_elevation(dem, x, y):
    """Calculates elevations from a digital elevation model at specified (x, y)
    coordinates.

    Parameters
    ----------
    dem : string, path to file
        A digital elevation model in a format that can be read by rasterio.
    x : numeric, or numpy array of numeric values
        x-coordinate(s) of points to query
    y : numeric, or numpy array of numeric values
        y-coordinate(s) of points to query

    Returns
    --------
    elev : numpy array
        elevation at specified (x, y) coordinates
    """
    with rasterio.open(dem) as src:
        terrain = src.read(1)

    # check that inputs are equal shape
    arrays_equal_shape(x, y)

    coords = np.stack((x, y))
    # have rasterio identify the raster rows and columns where these coords occur
    rows, cols = src.index(*coords)
    # index into the raster at these rows and columns
    try:
        elev = terrain[rows, cols]
    except IndexError:
        bounds = src.bounds
        error_msg = """
        (x,y) location outside bounds of elevation raster:
        {}""".format(bounds)
        raise IndexError(error_msg)

    return elev


def get_treetop_location(stem_x,
                         stem_y,
                         stem_z,
                         height,
                         lean_direction=0.0,
                         lean_severity=0.0):
    """Calculates 3D coordinates for the top of a tree, allowing specification
    of direction and severity of leaning.

    Parameters
    -----------
    stem_x : numeric, or array of numeric values
        x-coordinate stem base
    stem_y : numeric, or array of numeric values
        y-coordinate of stem base
    stem_z : numeric, or array of numeric values
        z-coordinate of stem base
    height : numeric, or array of numeric values
        vertical height of the tree apex from the base of the stem
    lean_direction : numeric, or array of numeric values
        direction of tree lean, in degrees with 0 = east, 90 = north, 180 = west
    lean_severity : numeric, or array of numeric values
        how much the tree is leaning, in degrees from vertical; 0 = no lean, and
        90 meaning the tree is horizontal.

    Returns
    --------
    top_x, top_y, top_z : three numeric values or three numpy arrays
        The coodrinates that define the tree top.
    """
    stem_x = np.asanyarray(stem_x)
    stem_y = np.asanyarray(stem_y)
    stem_z = np.asanyarray(stem_z)
    height = np.asanyarray(height)
    lean_severity = np.asanyarray(lean_severity)
    lean_direction = np.asanyarray(lean_direction)

    if np.any(lean_severity >= 90):
        raise ValueError('lean_severity must be < 90 degrees from vertical.')

    if np.any(height < 0):
        raise ValueError('height must be >= 0.')

    arrays_equal_shape(stem_x, stem_y, stem_z, height, lean_severity,
                       lean_direction)

    # convert direction of lean to radians
    theta_lean = np.deg2rad(lean_direction)

    # convert severity of lean to radians, and from horizontal
    phi_lean = np.deg2rad(lean_severity)

    top_x = stem_x + height * np.tan(phi_lean) * np.cos(theta_lean)
    top_y = stem_y + height * np.tan(phi_lean) * np.sin(theta_lean)
    top_z = stem_z + height

    return np.array((top_x, top_y, top_z))


def get_peripheral_points(stem_base, crown_radii, crown_edge_heights):
    """Calculates the x,y,z coordinates of the points of maximum crown width
    in E, N, W, and S directions around a tree.

    Parameters
    -----------
    stem_base : array with shape(3,)
        (x,y,z) coordinates of stem base
    crown_radii : array of numerics, shape (4,)
        distance from stem base to point of maximum crown width in each
        direction. Order of radii expected is E, N, W, S.
    crown_edge_heights : array of numerics, shape (4,)
        elevation (z coordinate) at point of maximum crown width in each
        direction. Order expected is E, N, W, S.

    Returns
    --------
    periph_pts : array with shape (4, 3)
        (x,y,z) coordinates of points at maximum crown width
    """

    east_point = np.array(
        (stem_base[0] + crown_radii[0], stem_base[1], crown_edge_heights[0]),
        dtype=float)

    north_point = np.array(
        (stem_base[0], stem_base[1] + crown_radii[1], crown_edge_heights[1]),
        dtype=float)

    west_point = np.array(
        (stem_base[0] - crown_radii[2], stem_base[1], crown_edge_heights[2]),
        dtype=float)

    south_point = np.array(
        (stem_base[0], stem_base[1] - crown_radii[3], crown_edge_heights[3]),
        dtype=float)

    periph_pts = np.stack((east_point, north_point, west_point, south_point))

    return periph_pts


def get_crown_center_xy(stem_base, crown_radii):
    """Calculates x,y coordinates of center of crown projection.

    The center of the crown projection is determined as the midpoint between
    points of maximum crown width in the x and y directions.

    Parameters
    -----------
    stem_base : array with shape(3,)
        (x,y,z) coordinates of stem base
    crown_radii : array of numerics, shape (4,)
        distance from stem base to point of maximum crown width in each
        direction. Order of radii expected is E, N, W, S.

    Returns
    --------
    center_xy : array with shape (2,)
        x,y coordinates of the center of the crown projection
    """
    stem_base = np.asanyarray(stem_base)
    crown_radii = np.asanyarray(crown_radii)
    center_xy = np.array((stem_base[0] - np.diff(crown_radii[0::2] / 2),
                          stem_base[1] - np.diff(crown_radii[1::2]) / 2))
    return center_xy[:, 0]


def get_crown_eccentricity(stem_base, crown_radii, crown_ratio):
    """Calculates eccentricity-index values for an asymmetric hull
    representing a tree crown. Eccentricity-index values are used to determine
    the x,y positions of the base and the apex of a tree crown.

    The eccentricity-index is defined by Koop (1989, p.49-51) as 'the ratio of
    distance between tree base and centre point of the crown projection and
    crown radius'. Eccentricity-index values should range [-1, 1]. A value of 0
    indicates that the x,y location of the tree apex or base is at the center of
    the horizontal crown projection. Values that approach -1 or 1 indicate the
    x,y location of the tree apex or base is near the edge of the crown.

        Koop, H. (1989). Forest Dynamics: SILVI-STAR: A Comprehensive Monitoring
        System. Springer: New York.

    Parameters
    -----------
    stem_base : array with shape(3,)
        (x,y,z) coordinates of stem base
    crown_radii : array of numerics, shape (4,)
        distance from stem base to point of maximum crown width in each
        direction. Order of radii expected is E, N, W, S.
    crown_ratio : numeric
        ratio of live crown length to total tree height

    Returns
    --------
    idx : array with shape (2, 2)
        eccentricity-index values for the top (0, ) and bottom of a tree (1, ).
    """
    center_xy = get_crown_center_xy(stem_base, crown_radii)
    eccen = np.array((
        (center_xy[0] - stem_base[0]) /
        crown_radii[0::2].mean(),  # x direction
        (center_xy[1] - stem_base[1]) / crown_radii[1::2].mean()  # y direction
    ))
    idx = np.array((
        -2 / np.pi * np.arctan(eccen) * crown_ratio,  # top of tree, x and y
        2 / np.pi * np.arctan(eccen) * crown_ratio)  # bottom of tree, x and y
                   )

    return idx


def get_crown_apex_and_base(stem_base, crown_radii, top_height, base_height,
                            crown_ratio):
    """Calculates the (x,y,z) position of the apex and base of a tree crown.

    This models a tree crown as an asymmetric hull comprised of
    quarter-ellipses.

    Parameters
    -----------
    stem_base: array with shape(3,)
        (x,y,z) coordinates of stem base
    crown_radii : array of numerics, shape (4,)
        distance from stem base to point of maximum crown width in each
        direction. Order of radii expected is E, N, W, S.
    crown_ratio : numeric
        ratio of live crown length to total tree height
    top_z : numeric
        elevation (z coordinate) of top of tree crown
    bottom_z : numeric
        elevation (z coordinate) of bottom of tree crown

    Returns
    --------
    apex, base : arrays with shape (3,)
        (x,y,z) coordinates for crown apex and crown base
    """
    stem_base = np.asanyarray(stem_base)
    crown_radii = np.asanyarray(crown_radii)

    center_xy = get_crown_center_xy(stem_base, crown_radii)
    eccen_idx = get_crown_eccentricity(stem_base, crown_radii, crown_ratio)
    apex = np.array(
        (
            center_xy[0] + np.diff(crown_radii[0::2]) *
            eccen_idx[0][0],  # x location of crown apex
            center_xy[1] + np.diff(crown_radii[1::2]) *
            eccen_idx[0][1],  # y location of crown apex
            top_height),
        dtype=float)

    base = np.array(
        (
            center_xy[0] + np.diff(crown_radii[0::2]) *
            eccen_idx[1][0],  # x location of crown base
            center_xy[1] + np.diff(crown_radii[1::2]) *
            eccen_idx[1][1],  # y location of crown base
            base_height),
        dtype=float)

    return apex, base


def get_circular_plot_boundary(x, y, radius, dem=None):
    """Returns coordinates of 32 points along the circumference of a circular
    plot.

    If a digital elevation model readable by rasterio is also provided, the
    elevations of the circumerference points will also be calculated.

    Parameters
    -----------
    x : numeric, or numpy array of numeric values
        x-coordinate of plot center
    y : numeric, or numpy array of numeric values
        y-coordinate of plot center
    dem : string, path to file
        A digial elevation model in a format that can be read by rasterio

    Returns
    --------
    xs, ys, zs : numpy arrays, each with shape (32,)
        x, y, and z coordinates of the plot boundary
    """
    theta = np.linspace(0, 2 * np.pi, 32)
    xs = (radius * np.cos(theta) + x)
    ys = (radius * np.sin(theta) + y)

    if dem:
        zs = get_elevation(dem, xs, ys)
    else:
        zs = np.zeros(32)

    return xs, ys, zs


def make_hull(stem_base, peripheral_points, crown_base, crown_apex,
              crown_shapes, top_only=False):
    """
    Parameters
    ----------
    stem_base : array with shape(3,)
        (x,y,z) coordinates of stem base
    peripheral_points: array with shape (4,3)
        (x,y,z) coordinates for four peripheral points
    crown_base : array with shape(3,)
        (x,y,z) coordinates of crown base
    crown_apex : array with shape(3,)
        (x,y,z) coordinates of crown apex
    crown_shapes : array with shape (4,2)
        shape coefficients describing curvature of crown profiles
        in each direction (E, N, W, S) for top and bottom of crown
    top_only : bool
        if True, will only return the top portion of the crown, i.e., the points
        above the maximum crown width
    """
    # places where we'll calculate crown surface
    theta = np.linspace(0, 2 * np.pi, 32, endpoint=True)  # angles
    zs = np.linspace(crown_base[2], crown_apex[2], 50)  # heights
    thetas, zz = np.meshgrid(theta, zs)

    # calculate height difference between apex and peripheral points
    top_periph_h = crown_apex[2] - peripheral_points[:, 2]

    # calculate radial (horizontal) distance from apex axis to peripheral points
    top_periph_r = np.hypot(peripheral_points[:, 1] - crown_apex[1],
                            peripheral_points[:, 0] - crown_apex[0])

    # calculate the angle between peripheral points and apex axis
    periph_v_apex_theta = np.arctan2(peripheral_points[:, 1] - crown_apex[1],
                                     peripheral_points[:, 0] - crown_apex[0])

    # calculate radii along peripheral line (maximum crown widths by angle
    # theta using linear interpolation)
    top_pline_r = np.interp(
        thetas, periph_v_apex_theta, top_periph_r, period=2 * np.pi)

    # convert peripheral line to x,y,z coords
    top_pline_xs = top_pline_r * np.cos(thetas) + crown_apex[0]
    top_pline_ys = top_pline_r * np.sin(thetas) + crown_apex[1]
    top_pline_zs = crown_apex[2] - np.interp(
        thetas, periph_v_apex_theta, top_periph_h, period=2 * np.pi)

    # identify those points in the grid that are higher than the peripheral line
    grid_top = zz >= top_pline_zs

    # calculate the shape coefficients at each angle theta (relative to apex)
    # using linear interpolation
    top_shape = np.interp(
        thetas[grid_top], periph_v_apex_theta, crown_shapes[0], period=2 * np.pi)

    # calculate crown radius at each height z for top of crown
    edge_r = np.empty_like(zz)
    edge_r[grid_top] = ((1 - (zz[grid_top] - top_pline_zs[grid_top])**top_shape /
                   (crown_apex[2] - top_pline_zs[grid_top])**top_shape) * top_pline_r[grid_top]**
                  top_shape)**(1 / top_shape)

    # calculate cartesian coordinates of crown edge points
    edge_x = np.empty_like(zz)
    edge_y = np.empty_like(zz)
    edge_x[grid_top] = edge_r[grid_top] * np.cos(thetas[grid_top]) + crown_apex[0]
    edge_y[grid_top] = edge_r[grid_top] * np.sin(thetas[grid_top]) + crown_apex[1]


    if top_only:
        return edge_x[grid_top].flatten(), edge_y[grid_top].flatten(), zz[grid_top].flatten()

    else: # generate the full crown

        # calculate height difference between base and peripheral points
        bot_periph_h = peripheral_points[:, 2] - crown_base[2]

        # calculate the angle between peripheral points and base axis
        periph_v_base_theta = np.arctan2(peripheral_points[:, 1] - crown_base[1],
                                         peripheral_points[:, 0] - crown_base[0])

        # identify those points in the grid that are higher than the peripheral line
        grid_bottom = zz < top_pline_zs

        # calculate the angles between points on the peripheral line and crown base
        bot_pline_theta = np.empty_like(thetas)
        bot_pline_theta[grid_bottom] = np.arctan2(top_pline_ys[grid_bottom] - crown_base[1],
                                     top_pline_xs[grid_bottom] - crown_base[0])

        # calculate radial distance between points on the peripheral line and
        # crown base
        bot_pline_r = np.hypot(top_pline_xs - crown_base[0],
                               top_pline_ys - crown_base[1])

        # calculate the shape coefficients at each angle theta (relative to base)
        # using linear interpolation
        bot_shape = np.interp(
            bot_pline_theta[grid_bottom], periph_v_base_theta, crown_shapes[1], period=2 * np.pi)


        edge_r[grid_top] = ((1 - (zz[grid_top] - top_pline_zs[grid_top])**top_shape /
               (crown_apex[2] - top_pline_zs[grid_top])**top_shape) * top_pline_r[grid_top]**
              top_shape)**(1 / top_shape)

        # calculate crown radius at height z
        edge_r[grid_bottom] = ((1 - (top_pline_zs[grid_bottom] - zz[grid_bottom])**bot_shape /
                       (top_pline_zs[grid_bottom] - crown_base[2])**bot_shape) * bot_pline_r[grid_bottom]**
                      bot_shape)**(1 / bot_shape)

        # calculate cartesian coordinates of crown edge points
        edge_x[grid_bottom] = edge_r[grid_bottom] * np.cos(bot_pline_theta[grid_bottom]) + crown_base[0]
        edge_y[grid_bottom] = edge_r[grid_bottom] * np.sin(bot_pline_theta[grid_bottom]) + crown_base[1]

        return edge_x.flatten(), edge_y.flatten(), zz.flatten()



class Tree(object):
    def __init__(self,
                 species,
                 dbh,
                 height,
                 stem_x,
                 stem_y,
                 stem_z,
                 lean_direction=0,
                 lean_severity=0,
                 crown_ratio=0.65,
                 crown_radii=None,
                 crown_edge_heights=None,
                 crown_shapes=np.ones((2, 4)),
                 top_only=False):
        """Initialize a Tree with field-measured attributes.

        Parameters
        -----------
        species : string
            tree species code or name
        dbh : numeric
            diameter at breast height
        height : numeric
            vertical height of the tree apex from the base of the stem
        stem_x : numeric
            x-coordinate stem base
        stem_y : numeric
            y-coordinate of stem base
        stem_z : numeric
            z-coordinate of stem base
        lean_direction : numeric
            direction of tree lean, in degrees with 0 = east, 90 = north,
            180 = west, etc.
        lean_severity : numeric
            how much the tree is leaning, in degrees from vertical; 0 = no lean,
            and 90 meaning the tree is horizontal
        crown_ratio : numeric
            ratio of live crown length to total tree height
        crown_radii : array of numerics, shape (4,)
            distance from stem base to point of maximum crown width in each
            direction. Order of radii expected is E, N, W, S.
        crown_edge_heights: array of numerics, shape (4,)
            height above ground at point of maximum crown width in each
            direction. Order expected is E, N, W, S.
        crown_shapes : array with shape (2,4)
            shape coefficients describing curvature of crown profiles
            in each direction (E, N, W, S) for top and bottom of tree crown. The
            crown_shapes[0, 0:4] describe the shape of the top of the crown.
            crown_shapes[1, 0:4] describe the shape of the bottom of the crown.
            Coef values of 1.0 produce a cone, values < 1 produce concave
            shapes, and values > 1 will produce convex shapes, with coef == 2.0
            producing an ellipse.
        top_only : bool
            if True, will only return the top portion of the crown, i.e., the
            points above the maximum crown width
        """
        self.species = species
        self.dbh = dbh
        self.height = height
        self.stem_x = stem_x
        self.stem_y = stem_y
        self.stem_z = stem_z
        self.lean_direction = lean_direction
        self.lean_severity = lean_severity
        self.crown_ratio = crown_ratio
        self.base_height = height - (crown_ratio * height)
        self.crown_shapes = crown_shapes
        self.top_only = top_only

        self.top_x, self.top_y, self.top_z = get_treetop_location(
            self.stem_x, self.stem_y, self.stem_z, self.height,
            self.lean_direction, self.lean_severity)
        self.base_z = self.base_height + self.stem_z

        if crown_radii is None:
            self.crown_radii = np.full(4, 0.25 * height)
        else:
            self.crown_radii = crown_radii

        if crown_edge_heights is None:
            self.crown_edge_heights = np.full(4, 0.5 * height) + self.stem_z
        else:
            self.crown_edge_heights = crown_edge_heights + self.stem_z

        self.stem_base = np.array((self.stem_x, self.stem_y, self.stem_z))
        self.peripheral_points = get_peripheral_points(
            self.stem_base, self.crown_radii, self.crown_edge_heights)

        self.crown_apex, self.crown_base = get_crown_apex_and_base(
            self.stem_base, self.crown_radii, self.top_z, self.base_z,
            self.crown_ratio)

    def get_hull(self):
        return make_hull(self.stem_base, self.peripheral_points,
                         self.crown_base, self.crown_apex, self.crown_shapes,
                         self.top_only)


def poisson_pipeline(infile, outfile, depth=8):
    pipeline = {
        "pipeline": [
            infile, {
                "type": "filters.normal"
            }, {
                "type": "filters.poisson",
                "depth": depth,
                "density": "true"
            }, {
                "type": "filters.normal"
            },
            {
                "type": "writers.ply",
                "filename": outfile,
                "storage_mode": "default",
                "faces": "true"
            }
        ]
    }

    return pipeline


def poisson_mesh(infile, outfile, depth=8):
    """Generates a Poisson surface mesh from a lidar point cloud and writes the
    output in polygon file format (PLY).

    Parameters
    -----------
    infile : string, path to file
        LAS or LAZ format point cloud to read from disk
    outfile : string, path to file
        PLY format file to save mesh to disk
    depth : int
        Maximum depth of octree used for mesh construction. Increasing this
        value will provide more detailed mesh and require more computation time.
    """
    pipeline_json = json.dumps(poisson_pipeline(infile, outfile, depth))

    # validate the pipeline using python extension to PDAL
    pipeline = pdal.Pipeline(pipeline_json)

    if pipeline.validate():
        proc = subprocess.run(['pdal', 'pipeline', '--stdin'],
                              stderr=subprocess.PIPE,
                              stdout=subprocess.PIPE,
                              input=pipeline_json.encode('utf-8'))
        if proc.returncode != 0:
            print(proc.stderr.decode())
    else:
        raise

def make_tree_all_params(species, dbh, height, stem_x, stem_y, stem_z,
              lean_direction, lean_severity, crown_ratio, crown_radius_E,
              crown_radius_N, crown_radius_W, crown_radius_S,
              crown_edge_height_E, crown_edge_height_N, crown_edge_height_W,
              crown_edge_height_S, shape_top_E, shape_top_N, shape_top_W,
              shape_top_S, shape_bot_E, shape_bot_N, shape_bot_W, shape_bot_S,
              top_only=False):
    """Creates a tree and returns its crown as a hull exposing all parameters
    used as individual arguments.

    This is used primarily for the plotting functions in the visualization.py
    script in this package. The parameters are the same as involved in
    instantiating a Tree object.

    Returns
    --------
    x, y, z : numpy arrays
        the x, y, and z coordinates of points that occur along the edge of the
        tree crown.
    """
    crown_radii = np.array((crown_radius_E,
                            crown_radius_N,
                            crown_radius_W,
                            crown_radius_S))

    crown_edge_heights = np.array((crown_edge_height_E,
                                   crown_edge_height_N,
                                   crown_edge_height_W,
                                   crown_edge_height_S))

    crown_shapes = np.array(((shape_top_E,
                              shape_top_N,
                              shape_top_W,
                              shape_top_S),
                             (shape_bot_E,
                              shape_bot_N,
                              shape_bot_W,
                              shape_bot_S)
                            ))
    new_tree = Tree(species,
                    dbh,
                    height,
                    stem_x,
                    stem_y,
                    stem_z,
                    lean_direction,
                    lean_severity,
                    crown_ratio,
                    crown_radii,
                    crown_edge_heights,
                    crown_shapes,
                    top_only)

    x, y, z = new_tree.get_hull()
    return x, y, z
