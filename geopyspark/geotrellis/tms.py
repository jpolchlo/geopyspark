import copy
import io
import socket
import numpy as np

from geopyspark import get_spark_context
from geopyspark.geotrellis.color import ColorMap
from geopyspark.geotrellis.layer import Pyramid
from geopyspark.geotrellis.protobufcodecs import multibandtile_decoder


__all__ = ['TileRender', 'TMS']


class TileRender(object):
    """A Python implementation of the Scala geopyspark.geotrellis.tms.TileRender
    interface.  Permits a callback from Scala to Python to allow for custom
    rendering functions.

    Args:
        render_function (numpy.ndarray => bytes): A function to convert a numpy
            array to a collection of bytes giving a binary image file.

    Attributes:
        render_function (numpy.ndarray => bytes): A function to convert a numpy
            array to a collection of bytes giving a binary image file.
    """

    def __init__(self, render_function):
        self.render_function = render_function

    def requiresEncoding(self):
        return True

    def renderEncoded(self, scala_array):
        """A function to convert an array to an image.

        Args:
            scala_array: A linear array of bytes representing the protobuf-encoded
                contents of a tile

        Returns:
            bytes representing an image
        """
        try:
            tile = multibandtile_decoder(scala_array)
            cells = tile.cells
            image = self.render_function(cells)
            bio = io.BytesIO()
            image.save(bio, 'PNG')
            return bio.getvalue()
        except Exception:
            from traceback import print_exc
            print_exc()

    class Java:
        implements = ["geopyspark.geotrellis.tms.TileRender"]


class TileCompositer(object):
    """A Python implementation of the Scala geopyspark.geotrellis.tms.TileCompositer
    interface.  Permits a callback from Scala to Python to allow for custom
    compositing functions.

    Args:
        composite_function (list[numpy array] => bytes): A function to convert
            a list of numpy arrays to a collection of bytes giving a binary
            image file.

    Attributes:
        composite_function (list[numpy array] => bytes): A function to convert
            a list of numpy arrays to a collection of bytes giving a binary
            image file.
    """

    def __init__(self, composite_function):
        self.composite_function = composite_function

    def requiresEncoding(self):
        return True

    def compositeEncoded(self, all_scala_arrays): # return `bytes`
        """A function to convert an array to an image.

        Args:
            all_scala_arrays (array of bytes): An array containing the encoded
                representations of the incoming tiles

        Returns:
            [bytes] representing an image
        """

        try:
            cells = [multibandtile_decoder(scala_array).cells for scala_array in all_scala_arrays]
            image = self.composite_function(cells)
            bio = io.BytesIO()
            image.save(bio, 'PNG')
            return bio.getvalue()
        except Exception:
            from traceback import print_exc
            print_exc()

    class Java:
        implements = ["geopyspark.geotrellis.tms.TileCompositer"]


class TMS(object):
    """Provides a TMS server for raster data.

    In order to display raster data on a variety of different map interfaces
    (e.g., leaflet maps, geojson.io, GeoNotebook, and others), we provide
    the TMS class.

    Args:
        server (JavaObject): The Java TMSServer instance

    Attributes:
        pysc (pyspark.SparkContext): The ``SparkContext`` being used this session.
        server (JavaObject): The Java TMSServer instance
        host (str): The IP address of the host, if bound, else None
        port (int): The port number of the TMS server, if bound, else None
        url_pattern (string): The URI pattern for the current TMS service, with
            {z}, {x}, {y} tokens.  Can be copied directly to services such as
            `geojson.io`.
    """

    def __init__(self, server):
        self.pysc = get_spark_context()
        self.server = server
        self.handshake = ''
        self.bound = False
        self._host = None
        self._port = None
        self.pysc._gateway.start_callback_server()

    def set_handshake(self, handshake):
        self.server.set_handshake(handshake)
        self.handshake = handshake

    def bind(self, host, requested_port=None):
        """Starts up a TMS server.

        Args:
            host (str): The target host.  Typically "0.0.0.0", "localhost", or
                "127.0.0.1".  The first will make the TMS service accessible
                from the world.

            requested_port (optional, int): A port number to bind the service
                to.  If omitted, a random port.
        """
        try:
            if requested_port:
                self.server.bind(host, requested_port)
            else:
                self.server.bind(host)
            self.bound = True
            self._port = self.server.port()
            self._host = [l for l in
                          ([ip for ip in socket.gethostbyname_ex(socket.gethostname())[2] if not ip.startswith("127.")][:1],
                           [[(s.connect(('8.8.8.8', 53)), s.getsockname()[0], s.close()) for s in
                             [socket.socket(socket.AF_INET, socket.SOCK_DGRAM)]][0][1]])
                          if l][0][0]
        except:
            raise RuntimeError("Error binding to " + "{} on port {}".format(self._host, self._port) if requested_port else self._host)

    def unbind(self):
        """Shuts down the TMS service, freeing the assigned port."""
        self.server.unbind()
        self._port = None
        self._host = None

    @property
    def host(self):
        """Returns the IP string of the server's host if bound, else None.

        Returns:
            (str)"""
        return self._host

    @property
    def port(self):
        """Returns the port number for the current TMS server if bound, else None.

        Returns:
            (int)"""
        return self._port

    @property
    def url_pattern(self):
        """Returns the URI for the tiles served by the present server.  Contains
        {z}, {x}, and {y} tokens to be substituted for the desired zoom and x/y tile position.

        Returns:
            (str)"""
        if not self.bound:
            raise ValueError("Cannot generate URL for unbound TMS server")
        else:
            return "http://{}:{}/tile/{{z}}/{{x}}/{{y}}.png".format(self._host, self._port)

    @classmethod
    def build(cls, source, display):
        """Builds a TMS server from one or more layers.

        This function takes a SparkContext, a source or list of sources, and a
        display method and creates a TMS server to display the desired content.
        The display method is supplied as a ColorMap (only available when there
        is a single source), or a callable object which takes either a single
        tile input (when there is a single source) or a list of tiles (for
        multiple sources) and returns the bytes representing an image file for
        that tile.

        Args:
            source (tuple, Pyramid, list): The tile sources to render.  Tuple
                inputs are (string, string) pairs where the first component is
                the URI of a catalog and the second is the layer name.  A list
                input may be any combination of tuples and Pyramids.
            display (ColorMap, callable): Method for mapping tiles to images.
                ColorMap may only be applied to single input source.  Callable
                will take a single numpy array for a single source, or a list
                of numpy arrays for multiple sources.  In the case of multiple
                inputs, resampling may be required if the tile sources have
                different tile sizes.  Returns bytes representing the resulting
                image.
        """

        pysc = get_spark_context()

        def makeReader(arg):
            if isinstance(arg, Pyramid):
                reader = pysc._gateway.jvm.geopyspark.geotrellis.tms.TileReaders.createSpatialRddReader(
                    {z: lvl.srdd for z, lvl in arg.levels.items()},
                    pysc._gateway.jvm.geopyspark.geotrellis.tms.AkkaSystem.system())
            elif isinstance(arg, tuple) and isinstance(arg[0], str) and isinstance(arg[1], str):
                reader = pysc._gateway.jvm.geopyspark.geotrellis.tms.TileReaders.createCatalogReader(arg[0], arg[1])
            else:
                raise ValueError('Arguments must be of type Pyramid or (string, string)')

            return reader

        if isinstance(source, list) and len(source) == 1:
            source = source[0]

        if isinstance(display, ColorMap):
            if isinstance(source, list):
                raise ValueError("May only apply color maps to a single input source")
            else:
                reader = makeReader(source)
                wrapped_display = pysc._jvm.geopyspark.geotrellis.tms.RenderSinglebandFromCM.apply(display.cmap)
                route = pysc._jvm.geopyspark.geotrellis.tms.TMSServerRoutes.renderingTileRoute(reader, wrapped_display)
        elif callable(display):
            if isinstance(source, list):
                readers = [makeReader(arg) for arg in source]
                route = pysc._jvm.geopyspark.geotrellis.tms.TMSServerRoutes.compositingTileRoute(readers, TileCompositer(display))
            else:
                reader = makeReader(source)
                route = pysc._jvm.geopyspark.geotrellis.tms.TMSServerRoutes.renderingTileRoute(reader, TileRender(display))
        else:
            raise ValueError("Display method must be callable or a ColorMap")

        server = pysc._jvm.geopyspark.geotrellis.tms.TMSServer.createServer(route)
        return cls(server)
