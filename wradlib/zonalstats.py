#-------------------------------------------------------------------------------
# Name:        zonalstats
# Purpose:
#
# Author:      Maik Heistermann, Kai Muehlbauer
#
# Created:     12.11.2015
# Copyright:   (c) Maik Heistermann, Kai Muehlbauer 2015
# Licence:     The MIT License
#-------------------------------------------------------------------------------
#!/usr/bin/env python
"""
Zonal Statistics
^^^^^^^^^^^^^^^^

.. versionadded:: 0.7.0

This module supports you in computing statistics over spatial zones. A typical
application would be to compute mean areal precipitation for a catchment by using
precipitation estimates from a radar grid in polar coordinates, or from precipitation
estimates in a Cartesian grid.

The general usage is similar to the ipol and adjustment modules: You have to
create an instance of a class by using the spatial information of your source and
target objects (e.g. radar bins and catchment polygons). You can then compute
zonal statistics for your target objects by calling the instance with an array of
values (one for each source object). Typically, creating the instance will be
computationally expensive, but only has to be done once (as long as the geometries
do not change). Calling the objects with actual data, however, will be very fast.

..note:: Right now we only support a limited set of 2-dimensional zonal statistics.
         In the future, we plan to extend this to three dimensions.


.. currentmodule:: wradlib.zonalstats

.. autosummary::
   :nosignatures:
   :toctree: generated/

   GridCellsToPoly
   GridPointsToPoly

"""

import os

from osgeo import ogr
import numpy as np
from scipy.spatial import cKDTree
import datetime as dt


class ZonalStatsBase():
    """Base class for all 2-dimensional zonal statistics.

    .. versionadded:: 0.7.0

    The base class for computing 2-dimensional zonal statistics for target
    polygons from source points or polygons. Provides the basic design
    for all other classes.
    
    If no source points or polygons can be associated to a target polygon (e.g.
    no intersection), the zonal statistic for that target will be NaN.

    Parameters
    ----------
    src : sequence of source points or polygons
    trg : sequence of target polygons -
    each item is an ndarray of shape (num vertices, 2) or an ogr.polygon geometry

    """
    def __init__(self, src, trg=None, ix=None, w=None, buffer=0., **kwargs):
        self.src = self._check_src(src, **kwargs)
        self._ix = []
        self._w = []
        self._buffer = buffer

        self._trg, self._dst = self._check_trg(trg, **kwargs)

        if self.trg is None:
            self._add_idx_weights(ix, w, **kwargs)

    # TODO: temporarily disabled
    # make this work for adding target polygons
    #def _add_target(self, trg, **kwargs):
    #    #print(trg)
    #
    #    ix, w = self.get_weights(trg, **kwargs)
    #    self._add_idx_weights(ix, w, **kwargs)

    def _add_idx_weights(self, ix, w, **kwargs):
        ix, w = self._check_ix_w(ix, w, **kwargs)
        self.ix = self.ix + [ix]
        self.w = self.w + [w]

    @property
    def ix(self):
        return self._ix

    @ix.setter
    def ix(self, value):
        self._ix = value

    @property
    def w(self):
        return self._w

    @w.setter
    def w(self, value):
        self._w = value

    @property
    def buffer(self):
        return self._buffer

    @buffer.setter
    def buffer(self, value):
        self._buffer = value
        # TODO: recalculate index and weights

    @property
    def trg(self):
        return self._trg

    #@trg.setter
    #def trg(self, value):
    #    self._trg = value

    def dump_src_shape(self, filename, remove=True):
        """ Output source grid points/polygons to ESRI_Shapefile

        Parameters
        ----------
        filename : string, path to shape-filename

        """
        trg_ds = ogr_create_ds('ESRI Shapefile', filename, remove=remove)
        lyr = self.src.GetLayerByName('src_grid')
        lyr.ResetReading()
        lyr.SetSpatialFilter(None)
        trg_lyr = trg_ds.CopyLayer(lyr, 'src_grid')

        # flush everything
        del trg_ds, trg_lyr

    def dump_all_shape(self, filename):
        """ Output source/target grid points/polygons to ESRI_Shapefile

        target layer features are attributed with source index and weight

        Parameters
        ----------
        filename : string, path to shape-filename

        """

        # create output file datasource
        drv_out = ogr.GetDriverByName('ESRI Shapefile')
        if os.path.exists(filename):
            drv_out.DeleteDataSource(filename)
        ds_out = drv_out.CreateDataSource(filename)

        # get and copy src geometry layer
        src_lyr = self.src.GetLayerByName('src_grid')
        src_lyr.ResetReading()
        src_lyr.SetSpatialFilter(None)
        dst_src_lyr = ds_out.CopyLayer(src_lyr, 'src_grid')

        # get and copy target polygon layer
        trg_lyr = self.trg.GetLayerByName('trg_poly')
        trg_lyr.ResetReading()
        dst_src_lyr = ds_out.CopyLayer(trg_lyr, 'trg_poly')

        # get and copy memory destination trg layers to output datasource
        for i in range(self._dst.GetLayerCount()):
            dst_trg_lyr = ds_out.CopyLayer(self._dst.GetLayerByIndex(i), 'trg_{0}'.format(i))

        # flush everything
        del ds_out

    def get_weights(self, trg, **kwargs):
        """This is the key method that needs to be filled for any inheriting class.
        """
        pass

    def check_empty(self):
        """
        """
        isempty = np.repeat(False, len(self.w))
        for i, weights in enumerate(self.w):
            if np.sum(weights)==0 or np.isnan(np.sum(weights)):
                isempty[i] = True
        return isempty
        
    def _check_src(self, src, **kwargs):
        """ Basic check of source elements (sequence of points or polygons).

            - array cast of source elements
            - create ogr_src datasource/layer holding src points/polygons
            - transforming source grid points/polygons to ogr.geometries on ogr.layer

        """
        t1 = dt.datetime.now()

        if type(src) is not ogr.DataSource:
            src = np.array(src)

            # create memory datasource, layer and create features
            if src.ndim == 3:
                geom_type = ogr.wkbPolygon
                fields = {'index': ogr.OFTInteger, 'area': ogr.OFTReal}
            # no Polygons, just Points
            else:
                geom_type = ogr.wkbPoint
                fields = {'index': ogr.OFTInteger}

            ogr_src = ogr_create_ds('Memory', 'out')
            ogr_create_layer(ogr_src, 'src_grid', geom_type, fields)
            ogr_add(ogr_src, src, name='src_grid')

        else:
            ogr_src = src

        t2 = dt.datetime.now()
        print "Setting up OGR Layer takes: %f seconds" % (t2 - t1).total_seconds()

        return ogr_src

    def _check_trg(self, trg, **kwargs):
        """ Basic check of target elements (sequence of points or polygons).

            Iterates over target elements (and transforms to ogr.Polygon if necessary)
            create ogr_trg datasource/layer holding target polygons

        """
        t1 = dt.datetime.now()
        # if no targets are given
        if trg is None:
            ogr_trg, ds_mem = None
        else:
            # create target polygon ogr.DataSource with dedicated target polygon layer
            ogr_trg = ogr_create_ds('Memory', 'out')
            if type(trg) is not ogr.DataSource:
                trg = np.array(trg)
                # create layer and features
                fields = {'index': ogr.OFTInteger, 'area': ogr.OFTReal}
                ogr_create_layer(ogr_trg, 'trg_poly', ogr.wkbPolygon, fields)
                ogr_add(ogr_trg, trg, name='trg_poly')
            else:
                # copy layer with features
                tmp_lyr = trg.GetLayer()
                ogr_trg_lyr = ogr_trg.CopyLayer(tmp_lyr, 'trg_poly')

            # the following code creates the destination target datasource with one layer
            # for each target polygon, consisting of the needed source data attributed with
            # index and weights
            # create intermediate mem datasource

            ds_mem = ogr_create_ds('Memory', 'out')

             # get src geometry layer
            src_lyr = self.src.GetLayerByName('src_grid')
            src_lyr.ResetReading()
            src_lyr.SetSpatialFilter(None)
            geom_type = src_lyr.GetGeomType()

            fields = {'index': ogr.OFTInteger, 'weight': ogr.OFTReal}

            # get target layer, iterate over polygons and calculate weights
            lyr = ogr_trg.GetLayer()
            lyr.ResetReading()
            for index, trg_poly in enumerate(lyr):

                # TODO: move the copy/add (ogr_add_by_index) inside the get_weights function
                # thus we can have the intersections also as ogr features

                # create layer
                dst_trg_lyr = ogr_create_layer(ds_mem, 'trg_{0}'.format(index), geom_type, fields)

                ix, w = self.get_weights(trg_poly.GetGeometryRef(), dst_lyr=dst_trg_lyr, **kwargs)
                self._add_idx_weights(ix, w, **kwargs)

                # copy/add
                ogr_add_by_index(dst_trg_lyr, src_lyr, zip(ix,w))

        t2 = dt.datetime.now()
        print "Setting up Target takes: %f seconds" % (t2 - t1).total_seconds()

        return ogr_trg, ds_mem

    def _check_ix_w(self, ix, w, **kwargs):
        """TODO Basic check of target attributes (sequence of values).

        """
        if ix is not None and w is not None:
            return np.array(ix), np.array(w)
        else:
            print("ix and w are complementary parameters and must both be given")
            raise TypeError

    def _check_vals(self, vals):
        """TODO Basic check of target elements (sequence of polygons).

        """
        if type(self.src) is ogr.DataSource:
            lyr = self.src.GetLayerByName('src_grid')
            lyr.ResetReading()
            lyr.SetSpatialFilter(None)
            src_len = lyr.GetFeatureCount()
        else:
            src_len = len(self.src)
        assert len(vals)==src_len, "Argument vals must be of length %d" % src_len
        return vals

    def mean(self, vals):
        """
        Evaluate (weighted) zonal mean for values given at the source points.

        Parameters
        ----------
        vals : 1-d ndarray of type float with the same length as self.src
            Values at the source element for which to compute zonal statistics

        """
        self._check_vals(vals)
        self.isempty = self.check_empty()
        out = np.zeros(len(self.ix))*np.nan
        out[~self.isempty] =  np.array( [np.average( vals[self.ix[i]], weights=self.w[i] ) \
                                        for i in np.arange(len(self.ix))[~self.isempty]] )
        return out
            

    def var(self, vals):
        """
        Evaluate (weighted) zonal variance for values given at the source points.

        Parameters
        ----------
        vals : 1-d ndarray of type float with the same length as self.src
            Values at the source element for which to compute zonal statistics

        """
        self._check_vals(vals)
        mean = self.mean(vals)
        out = np.zeros(len(self.ix))*np.nan
        out[~self.isempty] = np.array( [np.average( (vals[self.ix[i]] - mean[i])**2, weights=self.w[i]) \
                                       for i in np.arange(len(self.ix))[~self.isempty]] )
        return out


class GridCellsToPoly(ZonalStatsBase):
    """Compute weighted average for target polygons based on areal weights.

    .. versionadded:: 0.7.0

    Parameters
    ----------
    src : sequence of source polygons (shape NxMx2) or
        OGR DataSource object containing source points/polygons

    trg : sequence of target polygons (shape Nx2, num vertices x 2) or
        OGR DataSource object containing target polygons

    Keyword arguments
    -----------------
    buffer : float (same unit as coordinates)
             Points will be considered inside the target if they are contained in the buffer.
    """
    def get_weights(self, trg, **kwargs):
        """
        """
        #print(trg)
        t1 = dt.datetime.now()

        # if given, we apply a buffer value to the target polygon filter
        buffer = kwargs.get('buffer', 0.)
        #dst_trg_lyr = kwargs.get('dst_trg_lyr', None)

        # claim and reset source ogr layer
        layer = self.src.GetLayerByName('src_grid')
        layer.ResetReading()
        layer.SetSpatialFilter(trg.Buffer(self._buffer))

        areas = []
        ix = []

        # iterate over layer features
        for ogr_src in layer:
            geom = ogr_src.GetGeometryRef()
            #print(ogr_src.GetFID(), ogr_src.GetField('index'))
            ix.append(ogr_src.GetFID())
            # fetch precalculated area, if fully contained
            if trg.Contains(geom):
                areas.append(ogr_src.GetField('area'))
            # otherwise calculate intersection
            else:
                isec = trg.Intersection(geom)
                #print(isec.GetGeometryName(), isec.GetGeometryCount())
                areas.append(isec.Area())

        areas = np.array(areas)
        w = areas / np.sum(areas)
        #print(w)
        ix = np.array(ix)
        t2 = dt.datetime.now()
        print "Getting Weights takes: %f seconds" % (t2 - t1).total_seconds()

        return ix, w


    def _get_intersection(self, trg=None, idx=None, **kwargs):
        """Just a toy function if you want to inspect the intersection polygons of an arbitrary target
        or an target by index.
        """

        # check wether idx is given
        if idx is not None:
            if self._dst:
                try:
                    lyr = self._dst.GetLayerByName('trg_poly')
                    feat = lyr.GetFeature(idx)
                    trg = feat.GetGeometryRef()
                except:
                    raise TypeError("No target polygon found at index {0}".format(idx))
            else:
                raise TypeError('No target polygons found in object!')

        # check for trg
        if trg is None:
            raise TypeError('Either *trg* or *idx* keywords must be given!')

        # check for geometry
        if not type(trg) == ogr.Geometry:
            trg = numpy_to_ogr(trg, 'Polygon')

        if idx is None:
            # claim and reset source layer
            # apply spatial filter
            layer = self.src.GetLayerByName('src_grid')
            layer.ResetReading()
            layer.SetSpatialFilter(trg)
        else:
            # claim and reset source layer
            layer = self.src.GetLayerByName('trg_{0}'.format(idx))
            layer.ResetReading()


        intersecs = []
        for ogr_src in layer:
            geom = ogr_src.GetGeometryRef()
            if trg.Contains(geom):
                intersecs.append(ogr_to_numpy(geom))
            else:
                # this might be wrapped in its own recursive function, with generators
                isec = trg.Intersection(geom)
                geom_name = isec.GetGeometryName()
                if geom_name in ["MULTIPOLYGON",]:
                    for i in range(isec.GetGeometryCount()):
                        intersecs.append(ogr_to_numpy(isec.GetGeometryRef(i)))
                elif isec.GetGeometryName() in ["GEOMETRYCOLLECTION"]:
                    for i in range(isec.GetGeometryCount()):
                        g = isec.GetGeometryRef(i)
                        if g.GetGeometryName() in ["POLYGON"]:
                            intersecs.append(ogr_to_numpy(g))
                elif isec.GetGeometryName() in ["POLYGON"]:
                    intersecs.append(ogr_to_numpy(isec))
                else:
                    print("Unknown Geometry:", isec.GetGeometryName(), isec.ExportToWkt())

        return np.array(intersecs)



class ShapeToPoly(GridCellsToPoly):
    def __init__(self, filename, **kwargs):

        from wradlib import io
        ds, lyr = io.open_shape(filename)

        self.src = ds
        self._trg = ds
        self._dst = ds
        ix = []
        w = []

        # get target features
        cnt = ds.GetLayerByName('trg_poly').GetFeatureCount()

        for i in range(cnt):
            lyr = ds.GetLayerByName('trg_{0}'.format(i))
            lyr.ResetReading()
            ix.append([ogr_src.GetField('index') for ogr_src in lyr])
            lyr.ResetReading()
            w.append([ogr_src.GetField('weight') for ogr_src in lyr])

        self.ix = ix
        self.w = w


class GridPointsToPoly(ZonalStatsBase):
    """Compute zonal average from all points in or close to the target polygon.

    .. versionadded:: 0.7.0

    Parameters
    ----------
    src : sequence of source points points (shape Nx2) or
        OGR DataSource object containing source points
    trg : sequence of target polygons (shape Nx2, num vertices x 2) or
        OGR DataSource object containing target polygons

    Keyword arguments
    -----------------
    buffer : float (same unit as coordinates)
             Points will be considered inside the target if they are contained in the buffer.

    """
    def get_weights(self, trg, **kwargs):
        """
        """
        # Pre-selection to increase performance
        ix_ = self.get_points_in_target(trg, **kwargs)
        if len(ix_)==0:
            # No points in target polygon? Find the closest point to provide a value
            ix_ = self.get_point_next_to_target(trg, **kwargs)
        w = np.ones(len(ix_)) / len(ix_ )
        return ix_, w

    def get_points_in_target(self, trg, **kwargs):
        """Helper method that can also be used to return intermediary results.
        """
        t1 = dt.datetime.now()

        # claim and reset source ogr layer
        layer = self.src.GetLayer()
        layer.ResetReading()
        layer.SetSpatialFilter(trg.Buffer(self._buffer))

        ix_ = [ogr_src.GetFID() for ogr_src in layer]

        t2 = dt.datetime.now()
        print("Getting Weights takes: %f seconds" % (t2 - t1).total_seconds())

        return ix_

    def get_point_next_to_target(self, trg, **kwargs):
        """ Computes the target centroid and finds the closest point from src.
        """
        layer = self.src.GetLayer()
        layer.ResetReading()
        layer.SetSpatialFilter(None)
        src_pts = np.array([ogr_src.GetGeometryRef().GetPoint_2D(0) for ogr_src in layer])

        centroid = get_centroid(trg)
        tree = cKDTree(src_pts)
        distnext, ixnext = tree.query([centroid[0], centroid[1]], k=1)
        return np.array([ixnext])


# def ogr_create_datasource(src, geom_type=None):
#     """Creates OGR.DataSource object in memory from numpy source array.
#
#     .. versionadded:: 0.7.0
#
#     OGR.DataSource object consists of one OGR.Layer with OGR.Feature(s)
#     (polygon or point geometries) built from numpy src points or polygons.
#
#     OGR.Features 'FID' corresponds to source data element
#     Polygons also get precomputed 'area' field attached.
#
#     Parameters
#     ----------
#     vert : a numpy array of polygon vertices of shape (num polygons, num vertices, 2)
#
#     Returns
#     -------
#     out : an OGR.DataSource object
#
#     """
#
#     if geom_type is None:
#         # Polygons have NxMx2 dimensionality
#         if src.ndim == 3:
#             geom_type = ogr.wkbPolygon
#             fields = {'index': ogr.OFTInteger, 'area': ogr.OFTReal}
#         # no Polygons, just Points
#         else:
#             geom_type = ogr.wkbPoint
#             fields = {'index': ogr.OFTInteger}
#     elif geom_type == ogr.wkbPolygon:
#         fields = {'index': ogr.OFTInteger, 'area': ogr.OFTReal}
#
#     ds = ogr_create_ds('Memory', 'out')
#     ogr_create_layer(ds, 'src', geom_type=geom_type)
#     #lyr = ds.CreateLayer('src', geom_type=geom_type)
#     #for fname, fvalue in fields.items():
#     #    lyr.CreateField(ogr.FieldDefn(fname, fvalue))
#
#     return ds

def ogr_create_ds(drv, name, remove=False):
    """Creates OGR.DataSource object.

    .. versionadded:: 0.7.0

    OGR.DataSource object consists of one OGR.Layer with OGR.Feature(s)
    (polygon or point geometries) built from numpy src points or polygons.

    OGR.Features 'FID' corresponds to source data element
    Polygons also get precomputed 'area' field attached.

    Parameters
    ----------
    drv : string, GDAL/OGR driver string

    name : string, path to filename

    Returns
    -------
    out : an OGR.DataSource object

    """


    drv = ogr.GetDriverByName(drv)
    if remove:
        if os.path.exists(name):
            drv.DeleteDataSource(name)
    ds = drv.CreateDataSource(name)

    return ds

def ogr_create_layer(ds, name, geom_type=None, fields=None):
    """Creates OGR.Layer objects in OGR.DataSource object.

    .. versionadded:: 0.7.0

    OGR.DataSource object consists of one OGR.Layer with OGR.Feature(s)
    (polygon or point geometries) built from numpy src points or polygons.

    OGR.Features 'FID' corresponds to source data element
    Polygons also get precomputed 'area' field attached.

    Parameters
    ----------
    ds : OGR.DataSource object

    name : string, OGRLayer name

    geom_type : OGR GeometryType (eg. ogr.wkbPolygon)

    fields : dictionary, dict.keys are field names strings
            dict.values are OGR.DataTypes (eg. ogr.OFTReal)

    Returns
    -------
    out : an OGR.Layer object

    """

    if geom_type is None:
        raise TypeError("geometry_type needed")

    lyr = ds.CreateLayer(name, geom_type=geom_type)
    for fname, fvalue in fields.items():
        lyr.CreateField(ogr.FieldDefn(fname, fvalue))

    return lyr


def ogr_add(ds, src, name=None):
    """ Creates OGR.Feature objects in OGR.Layer object.

    .. versionadded:: 0.7.0

    OGR.Features are built from numpy src points or polygons.

    OGR.Features 'FID' corresponds to source data element
    Polygons also get precomputed 'area' field attached.

    Parameters
    ----------
    ds : OGR.DataSource object

    src : source data numpy array

    name : string, name of wanted Layer
    """

    if name is not None:
        lyr = ds.GetLayerByName(name)
    else:
        lyr = ds.GetLayer()

    defn = lyr.GetLayerDefn()
    geom_name = ogr.GeometryTypeToName(lyr.GetGeomType())
    fields = [defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())]
    feat = ogr.Feature(defn)

    for index, src_item in enumerate(src):
        geom = numpy_to_ogr(src_item, geom_name)
        feat.SetFID(index)

        if 'area' in fields:
            feat.SetField('area', geom.Area())
        if 'index' in fields:
            feat.SetField('index', index)

        feat.SetGeometry(geom)
        lyr.CreateFeature(feat)


def ogr_add_by_index(layer, src_layer, values):
    """ Copies OGR.Feature objects to an OGR.Layer object.

    .. versionadded:: 0.7.0

    OGR.Features are read by index from src layer. Attributes
    are attached.

    Parameters
    ----------
    layer : OGR.Layer object

    src_layer : source layer

    values : list of tupels (index, weights)
    """


    defn = layer.GetLayerDefn()
    feat = ogr.Feature(defn)

    for idx, weight in values:
        geom = src_layer.GetFeature(idx)
        feat.SetFID(idx)
        feat.SetField('index', idx)
        feat.SetField('weight', weight)
        feat.SetGeometry(geom.GetGeometryRef())
        layer.CreateFeature(feat)


def numpy_to_ogr(vert, geom_name):
    """Convert a vertex array to gdal/ogr geometry.

    .. versionadded:: 0.7.0

    Using JSON as a vehicle to efficiently deal with numpy arrays.

    Parameters
    ----------
    vert : a numpy array of vertices of shape (num vertices, 2)

    Returns
    -------
    out : an ogr Geometry object of type geom_name

    """

    if geom_name == 'Polygon':
        json_str = "{{'type':{0!r},'coordinates':[{1!r}]}}".format(geom_name, vert.tolist())
    else:
        json_str = "{{'type':{0!r},'coordinates':{1!r}}}".format(geom_name, vert.tolist())

    return ogr.CreateGeometryFromJson(json_str)


def ogr_to_numpy(ogrobj):
    """Backconvert a gdal/ogr geometry to a numpy vertex array.

    .. versionadded:: 0.7.0

    Using JSON as a vehicle to efficiently deal with numpy arrays.

    Parameters
    ----------
    ogrobsj : an ogr Geometry object

    Returns
    -------
    out : a nested ndarray of vertices of shape (num vertices, 2)

    """
    jsonobj = eval(ogrobj.ExportToJson())

    return np.squeeze(jsonobj['coordinates'])


# def intersect(src, trg):
#     """Return intersection and its area from target and source vertex.
#
#     .. versionadded:: 0.7.0
#
#     Parameters
#     ----------
#     src : numpy array of shape (n corners, 2) or ogr.Geometry
#     trg : numpy array of shape (n corners, 2) or ogr.Geometry
#
#     Returns
#     -------
#     out : intersection, area of intersection
#
#     """
#     # Convert to ogr if necessary
#     if not type(trg) == ogr.Geometry:
#         trg = numpy_to_ogr(trg, 'Polygon')
#     if not type(src) == ogr.Geometry:
#         src = numpy_to_ogr(src, 'Polygon')
#     isec = trg.Intersection(src)
#     if isec.GetGeometryName() in ["POLYGON", "MULTIPOLYGON"]:
#         return ogr_to_numpy(isec), isec.Area()
#     else:
#         return None, 0.


# def could_intersect(src, trg):
#     """Roughly checks for intersection between polygons in src and trg.
#
#     .. versionadded:: 0.7.0
#
#     This function should be used to filter polygons from src for which an
#     intersection with trg *might* be possible. It simply uses the spatial
#     bounding box (extent/envelope) of trg and checks whetehr any corner points
#     of src fall within. Beware that this does not mean that the polygons in
#     fact intersect. This function is just to speed up the computation of true
#     intersections by preselection.
#
#     Parameters
#     ----------
#     src : array polygons
#     trg : numpy array of polygon vertices of shape (n vertices, 2)
#
#     Returns
#     -------
#     out : Boolean array of same length as src
#         ith element is True if at least on vertex of the ith element of src
#         is within the bounding box of trg
#
#     """
#     bbox = get_bbox(trg[:,0], trg[:,1])
#
#     right_of_left = np.any(src[...,0]>=bbox["left"], axis=1)
#     left_of_right = np.any(src[...,0]<=bbox["right"], axis=1)
#     above_bottom  = np.any(src[...,1]>=bbox["bottom"], axis=1)
#     below_top     = np.any(src[...,1]<=bbox["top"], axis=1)
#
#     return right_of_left & left_of_right & above_bottom & below_top


def mask_from_bbox(x, y, bbox, polar=False):
    """Return 2-d index array based on spatial selection from a bounding box.

    Use this function to create a 2-d boolean mask from 2-d arrays of grids points.

    .. versionadded:: 0.7.0

    Parameters
    ----------
    x : nd array of shape (num rows, num columns)
        x (Cartesian) coordinates
    y : nd array of shape (num rows, num columns)
        y (Cartesian) coordinates
    bbox : dictionary with keys "left", "right", "bottom", "top"
        These must refer to the same Cartesian reference system as x and y
    polar : x, y are aligned polar (azimuth x range)

    Returns
    -------
    out : mask, shape
          mask is a boolean array that is True if the point is inside the bbox
          shape is the shape of the True subgrid

    """
    ny, nx = x.shape

    ix = np.arange(x.size).reshape(x.shape)

    # Find bbox corners
    #    Plant a tree
    tree = cKDTree(np.vstack((x.ravel(),y.ravel())).transpose())
    # find lower left corner index
    dists, ixll = tree.query([bbox["left"], bbox["bottom"]], k=1)
    ill = (ixll / nx)-1
    jll = (ixll % nx)-1
    # find upper right corner index
    dists, ixur = tree.query([bbox["right"],bbox["top"]], k=1)
    iur = (ixur / nx)+1
    jur = (ixur % nx)+1

    # for polar grids we need all 4 corners
    if polar:
        # find upper left corner index
        dists, ixul = tree.query([bbox["left"], bbox["top"]], k=1)
        iul = (ixul / nx)-1
        jul = (ixul % nx)-1
        # find lower right corner index
        dists, ixlr = tree.query([bbox["right"],bbox["bottom"]], k=1)
        ilr = (ixlr / nx)+1
        jlr = (ixlr % nx)+1

    mask = np.repeat(False, ix.size).reshape(ix.shape)

    # for polar grids we have to handle the azimuth carefully
    if polar:
        # ranges are not problematic, just get min and max
        jmin = min(jll, jul, jur, jlr)
        jmax = max(jll, jul, jur, jlr)

        # azimuth array for angle_between calculation
        ax = np.array([[ill, ilr],
                       [ill, iur],
                       [iul, ilr],
                       [iul, iur]])

        # this calculates the angles between 4 azimuth and returns indices
        # of the greatest angle
        ar = angle_between(ax[:,0], ax[:,1])
        maxind = np.argmax(ar)
        imin, imax = ax[maxind,:]

        # if catchment extends over zero angle
        if imin > imax:
            mask[:imax, jmin:jmax] = True
            mask[imin:, jmin:jmax] = True
            shape = (int(ar[maxind]), jmax-jmin)
        else:
            mask[imin:imax, jmin:jmax] = True
            shape = (int(ar[maxind]), jmax-jmin)

    else:

        if iur>ill:
            mask[ill:iur,jll:jur] = True
            shape = (iur-ill, jur-jll)
        else:
            mask[iur:ill,jll:jur] = True
            shape = (ill-iur, jur-jll)

    return mask, shape


def angle_between(source_angle, target_angle):
    """Return angle between source and target radial angle
    """
    sin1 = np.sin(np.radians(target_angle)-np.radians(source_angle))
    cos1 = np.cos(np.radians(target_angle)-np.radians(source_angle))
    return np.rad2deg(np.arctan2(sin1, cos1))


# def points_in_polygon(polygon, points, buffer=0.):
#     """Select points inside or close to polygon.
#
#     .. versionadded:: 0.7.0
#
#     Parameters
#     ----------
#     polygon : ndarray of polygon vertices of shape (num vertices, 2)
#     points : nd array of point coordinates of shape (num points, 2)
#     buffer : neighbourhood around polygon borders in which a point will be considered as inside the polygon.
#
#     Returns
#     -------
#     out : index array indicating the points that are located inside the polygon.
#
#     """
#     mpath = Path( polygon )
#     return  mpath.contains_points(points, radius=-buffer)

# def subset_points(pts, bbox, buffer=0.):
#     """Subset a large set of points by polygon bbox.
#
#     .. versionadded:: 0.7.0
#
#     Parameters
#     ----------
#     pts : ndarray of points of shape (num points, 2)
#     bbox : dictionary with keys "left", "right", "bottom", "top"
#         These must refer to the same Cartesian reference system as x and y
#     buffer : extends the bbox in all directions, default value = 0
#
#     Returns
#     -------
#     out : index array indicating the points that are located inside the bbox.
#
#
#     """
#     x = pts[:,0]
#     y = pts[:,1]
#     return np.where(
#             (x >= bbox["left"]  -buffer) & \
#             (x <= bbox["right"] +buffer) & \
#             (y >= bbox["bottom"]-buffer) & \
#             (y <= bbox["top"]   +buffer) )[0]


def get_bbox(x, y):
    """Return bbox dictionary that represents the extent of the points.
    """
    return dict(left=np.min(x),
                right=np.max(x),
                bottom=np.min(y),
                top=np.max(y))


def get_centroid(polyg):
    """Return centroid of a polygon

    Parameters
    ----------
    polyg : ndarray of shape (num vertices, 2) or ogr.Geometry object

    Returns
    -------
    out : x and y coordinate of the centroid

    """
    if not type(polyg) == ogr.Geometry:
        polyg = numpy_to_ogr(polyg, 'Polygon')
    return polyg.Centroid().GetPoint()[0:2]



def grid_centers_to_vertices(X, Y, dx, dy):
    """Produces array of vertices from grid's center point coordinates.

    .. warning:: This has to be done in the "native" grid projection.
                 Once you reprojected the coordinates, this trivial function
                 cannot be used to compute vertices from center points.

    Parameters
    ----------
    X : 2-d array of x coordinates (same shape as the actual 2-D grid)
    Y : 2-d array of y coordinates (same shape as the actual 2-D grid)
    dx : grid spacing in x direction
    dy : grid spacing in y direction

    Returns
    -------
    out : 3-d array of vertices for each grid cell of shape (n grid points,
          5, 2)

    """
    left    = X - dx/2
    right   = X + dy/2
    bottom  = Y - dy/2
    top     = Y + dy/2

    verts = np.vstack(( [left.ravel() ,bottom.ravel()],
                        [right.ravel(),bottom.ravel()],
                        [right.ravel(),top.ravel()],
                        [left.ravel() ,top.ravel()],
                        [left.ravel() ,bottom.ravel()]) ).T.reshape((-1,5,2))

    return verts


if __name__ == '__main__':
    print 'wradlib: Calling module <zonalstats> as main...'
