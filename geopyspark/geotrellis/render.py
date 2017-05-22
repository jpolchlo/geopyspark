from geopyspark.geotrellis.constants import RESAMPLE_METHODS, NEARESTNEIGHBOR, ZOOM

class ColorRamp(object):
    @classmethod
    def get(cls, geopysc, name, num_colors=None):
        if num_colors:
            return list(geopysc._jvm.geopyspark.geotrellis.ColorRamp.get(name, num_colors))
        else:
            return list(geopysc._jvm.geopyspark.geotrellis.ColorRamp.get(name))

    @classmethod
    def getHex(cls, geopysc, name, num_colors=None):
        if num_colors:
            return list(geopysc._jvm.geopyspark.geotrellis.ColorRamp.getHex(name, num_colors))
        else:
            return list(geopysc._jvm.geopyspark.geotrellis.ColorRamp.getHex(name))


class PngRDD(object):
    def __init__(self, pyramid, ramp_name, persist_mode="NONE", debug=False):
        """Convert a pyramid of TiledRasterRDDs into a displayable structure of PNGs

        Args:
            pyramid (list): A pyramid of TiledRasterRDD resulting from calling the pyramid
                method on an instance of that class
            ramp_name (str): The name of a color ramp; options are hot, coolwarm, magma,
                inferno, plasma, viridis, BlueToOrange, LightYellowToOrange, BlueToRed,
                GreenToRedOrange, LightToDarkSunset, LightToDarkGreen, HeatmapYellowToRed,
                HeatmapBlueToYellowToRedSpectrum, HeatmapDarkRedToYellowWhite,
                HeatmapLightPurpleToDarkPurpleToWhite, ClassificationBoldLandUse, and
                ClassificationMutedTerrain
            persist_mode (str): Sets the persistence mode.  See :func:`~PngRDD.set_persist`.

        Returns: A PngRDD object
        """

        __slots__ = ['geopysc', 'rdd_type', 'layer_metadata', 'max_zoom', 'pngpyramid', 'debug']

        level0 = pyramid[0]
        self.geopysc = level0.geopysc
        self.rdd_type = level0.rdd_type
        self.layer_metadata = list(map(lambda lev: lev.layer_metadata, pyramid))
        self.max_zoom = level0.zoom_level
        self.pngpyramid = list(map(lambda layer: self.geopysc._jvm.geopyspark.geotrellis.PngRDD.asSingleband(layer.srdd, ramp_name), pyramid))
        self.debug = debug
        set_persist(persist_mode)

    @classmethod
    def makePyramid(cls, tiledrdd, ramp_name, start_zoom=None, end_zoom=0, resample_method=NEARESTNEIGHBOR, persist_mode="NONE", debug=False):
        """Create a pyramided PngRDD from a TiledRasterRDD

        Args:
            tiledrdd (TiledRasterRDD): The TiledRasterRDD source
            ramp_name (str): The name of a color ramp; options are hot, coolwarm, magma,
                inferno, plasma, viridis, BlueToOrange, LightYellowToOrange, BlueToRed,
                GreenToRedOrange, LightToDarkSunset, LightToDarkGreen, HeatmapYellowToRed,
                HeatmapBlueToYellowToRedSpectrum, HeatmapDarkRedToYellowWhite,
                HeatmapLightPurpleToDarkPurpleToWhite, ClassificationBoldLandUse, and
                ClassificationMutedTerrain
            start_zoom (int, optional): The starting (highest resolution) zoom level for
                the pyramid.  Defaults to the zoom level of the source RDD.
            end_zoom (int, optional): The final (lowest resolution) zoom level for the
                pyramid.  Defaults to 0.
            resample_method (str, optional): The resample method to use for the reprojection.
                This is represented by a constant. If none is specified, then NEARESTNEIGHBOR
                is used.

        Returns: A PngRDD object
        """
        if resample_method not in RESAMPLE_METHODS:
            raise ValueError(resample_method, " Is not a known resample method.")

        reprojected = tiledrdd.reproject("EPSG:3857", scheme=ZOOM)

        if not start_zoom:
            if reprojected.zoom_level:
                start_zoom = reprojected.zoom_level
            else:
                raise AttributeError("No initial zoom level is available; Please provide a value for start_zoom")

        pyramid = reprojected.pyramid(start_zoom, end_zoom, resample_method)

        return cls(pyramid, ramp_name, persist_mode, debug)

    def lookup(self, col, row, zoom=None):
        """Return the value(s) in the image of a particular SpatialKey (given by col and row)

        Args:
            col (int): The SpatialKey column
            row (int): The SpatialKey row

        Returns: A list of bytes containing the resulting PNG images
        """
        if not zoom:
            idx = 0
        else:
            idx = self.max_zoom - zoom

        pngrdd = self.pngpyramid[idx]
        metadata = self.layer_metadata[idx]

        bounds = metadata.bounds
        min_col = bounds.minKey['col']
        min_row = bounds.minKey['row']
        max_col = bounds.maxKey['col']
        max_row = bounds.maxKey['row']

        if col < min_col or col > max_col:
            raise IndexError("column out of bounds")
        if row < min_row or row > max_row:
            raise IndexError("row out of bounds")

        result = pngrdd.lookup(col, row)

        return [bytes for bytes in result]

    def set_persist(self, storage_mode):
        """Set the persistence mode of the underlying RDD structure.

        Args:
            storage_mode (str): The string name of the storage mode to set.  Possible values
                are NONE, DISK_ONLY, DISK_ONLY_2, MEMORY_ONLY, MEMORY_ONLY_2, 
                MEMORY_ONLY_SER, MEMORY_ONLY_SER_2, MEMORY_AND_DISK, MEMORY_AND_DISK_2, 
                MEMORY_AND_DISK_SER, MEMORY_AND_DISK_SER_2, and OFF_HEAP.

        Returns: Nothing
        """
        for level in self.pyramid:
            level.srdd.setPersistenceMode(storage_mode)
        self.persisted = storage_mode != "NONE"
