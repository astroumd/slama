
"""
Core functions/classes for spatial and velocity coordinates and reference frames
"""

# substantially stolen from dysh

import astropy.coordinates as coord
from astropy.coordinates import SkyCoord, EarthLocation, AltAz, Angle
from astropy.units import Quantity
import astropy.units as u
import numpy as np
from astropy.time import Time


MPS = u.m / u.s
KMS = u.km / u.s

# Velocity frame conventions
# string to astropy coordinate frame class
astropy_frame_dict = {
    "VLSR": coord.LSRK,
    "VRAD": coord.LSRK,
    "VELO": coord.LSRK,
    "VOPT": coord.LSRK,
    "LSRD": coord.LSRD,
    "lsrd": coord.LSRD,
    "LSRK": coord.LSRK,
    "lsrk": coord.LSRK,
    "-LSR": coord.LSRK,
    "-HEL": coord.HCRS,
    "-BAR": coord.ICRS,
    "BAR": coord.ICRS,
    "BARY": coord.ICRS,
    "icrs": coord.ICRS,
    "ICRS": coord.ICRS,
    "bary": coord.ICRS,
    "barycentric": coord.ICRS,
    "VHEL": coord.HCRS,
    "heliocentric": coord.HCRS,
    "helio": coord.HCRS,
    "hcrs": coord.HCRS,
    "HCRS": coord.HCRS,
    "VGEO": coord.GCRS,
    "geocentric": coord.GCRS,
    "gcrs": coord.GCRS,
    "GCRS": coord.GCRS,
    "-GAL": coord.Galactocentric,
    "galactocentric": coord.Galactocentric,
    "topocentric": coord.ITRS,  # but need to add observatory position
    "topo": coord.ITRS,  # but need to add observatory position
    "itrs": coord.ITRS,  # but need to add observatory position
    "fk5": coord.FK5,
    "gal": coord.Galactic,
}

astropy_convenience_frame_names = {
    "bary": "icrs",
    "barycentric": "icrs",
    "heliocentric": "hcrs",
    "helio": "hcrs",
    "geo": "gcrs",
    "geocentric": "gcrs",
    "topocentric": "itrs",
    "topo": "itrs",
    "vlsr": "lsrk",
}


# astropy-sanctioned coordinate frame string to label
frame_to_label = {
    "itrs": "Topocentric",
    "topocentric": "Topocentric",
    "topo": "Topocentric",
    "hcrs": "Heliocentric",
    "gcrs": "Geocentric",
    "icrs": "Barycentric",
    "fk5": "Barycentric",
    "lsrk": "LSRK",
    "lsrd": "LSRD",
    "galactocentric": "Galactocentric",
}

# velframe string to label
frame_dict = {
    "VLSR": "LSRK",
    "VRAD": "LSRK",
    "VELO": "LSRK",
    "VOPT": "LSRK",
    "LSRD": "LSRD",
    "LSRK": "LSRK",
    "-LSR": "LSRK",
    "-HEL": "heliocentric",
    "-BAR": "barycentric",
    "BAR": "barycentric",
    "BARY": "barycentric",
    "-OBS": "topocentric",
    "VHEL": "heliocentric",
    "VGEO": "geocentric",
    "TOPO": "topocentric",
    "TRUE": "topocentric",
    "VREST": "rest",
    "Z": "rest",
    "FREQ": "rest",
    "WAV": "rest",
    "WAVE": "rest",
    "CMB": "cmb",
    "GALAC": "galactic",
    "GALA": "galactic",
    "ALAC": "galactic",  # in case of 'VELGALAC', last 4 chars.
}


# label to velframe string
reverse_frame_dict = {
    "bary": "-BAR",
    "barycentric": "-BAR",
    "icrs": "-BAR",
    "galactocentric": "-GAL",
    "gcrs": "-GEO",
    "geocentric": "-GEO",
    "heliocentric": "-HEL",
    "hcrs": "-HEL",
    "helio": "-HEL",
    "heli": "-HEL",
    "lsr": "-LSR",
    "lsrk": "-LSR",
    "lsrd": "LSRD",
    "itrs": "-OBS",
    "topo": "-OBS",
    "topocentric": "-OBS",
    "fk5": "-BAR",
    "fk4": "-BAR",
    "cirs": "-GEO",
    "tete": "-GEO",
}

# reverse of above
reverse_velocity_convention_dict = {"optical": "OPTI", "radio": "RADI", "relativistic": "VELO"}

# dictionary to convert CRVAL4 to a polarization ID 
# "zero" entry for more graceful handling downstream
crval4_to_pol = {
    -1: "RR",
    -2: "LL",
    -3: "RL",
    -4: "LR",
    -5: "XX",
    -6: "YY",
    -7: "XY",
    -8: "YX",
    0: "UNKNOWN",
    1: "I",
    2: "Q",
    3: "U",
    4: "V",
}

def sma_location():
    """
    Create an `~astropy.coordinates.EarthLocation` for the SMA.
    Coordinates taken from CARMA's Observatory.cat:

    * latitude    = 19:49:33.8

    * longitude   = -155:28:46.4

    * height      = 4080 m

    Returns
    -------
    sma: `~astropy.coordinates.EarthLocation`
        astropy EarthLocation for the SMA
    """
    sma_lat = 19.8620556*u.degree
    sma_lon = -155.4795556*u.degree
    sma_height = 4080*u.m
    sma = EarthLocation.from_geodetic(lon=sma_lon, lat=sma_lat, height=sma_height)
    return sma  

def fake_sma_antpos():
    """
    used for testing.  Creates an EarthLocation with 8 antenna positions randomly distributed
    about the array center

    Returns
    -------
    antpos: `~astropy.coordinates.EarthLocation`
        astropy EarthLocations for 8 SMA antennas
    """
    s = SMA()
    # 0.005 degrees is 550 meters at the equator, ~typical baseline size
    lat = s.lat+np.random.rand(8)*0.005*u.degree
    lon = s.lon+np.random.rand(8)*0.005*u.degree
    h = s.height+np.random.rand(8)*2*u.m
    return EarthLocation.from_geodetic(lon=lon,lat=lat,height=h)


class SMA:
    """Singleton Submillimeter Array EarthLocation object"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = sma_location()
        return cls._instance


def eq2hor(lon, lat, frame, date_obs, unit="deg", location=SMA()):  # noqa: B008
    """
    Equatorial to horizontal coordinate conversion.

    Parameters
    ----------
    lon : float
        Longitude coordinate. E.g., RA or Galactic longitude.
    lat : float
        Latitude coordinate. E.g., Dec or Galactic latitude.
    frame : str
        Input coordinate frame. Must be recognized by `~astropy.coordinates`
    date_obs : str
        Date of observations. Must be a format compatible with `~astropy.time.Time`.
    unit : str
        Units of `lon` and `lat`.
    location : `~astropy.coordinates.EarthLocation`
        Observer location.

    Returns
    -------
    altaz : `~astropy.coordinates.AltAz`
        Horizontal coordinates.

    """

    lonlat = SkyCoord(lon, lat, unit=unit, frame=frame, obstime=Time(date_obs))
    return lonlat.transform_to(AltAz(location=location))


def hor2eq(az, alt, frame, date_obs, unit="deg", location=SMA()):  # noqa: B008
    """
    Horizontal to Equatorial coordinate conversion.

    Parameters
    ----------
    az : float
        Azimuth coordinate.
    alt : float
        Altitude or elevation coordinate.
    frame : str
        Output coordinate frame. Must be recognized by `~astropy.coordinates`
    date_obs : str
        Date of observations. Must be a format compatible with `~astropy.time.Time`.
    unit : str
        Units of `lon` and `lat`.
    location : `~astropy.coordinates.EarthLocation`
        Observer location.

    Returns
    -------
    eq : `~astropy.coordinates.SkyCoord`
        Celestial coordinates in `frame`.

    """

    altaz = SkyCoord(az=az, alt=alt, unit=unit, frame="altaz", obstime=Time(date_obs), location=location)
    return altaz.transform_to(astropy_frame_dict[frame])


def ra2ha(lst, ra):
    """
    Take LST (sec) and RA (deg) and output wrapped HA (hr).
    Follows GBTIDL implementation (with the hour conversion included)
    """
    ha = np.around(15 * (lst / 3600) - ra, 2)
    if ha > 180:
        ha -= 360
    elif ha < -180:
        ha += 360
    return np.around(ha / 15, 2)


def obsfreq(restfreq: Quantity | float, z: float) -> Quantity | float:
    """
    The observed frequency for a given rest frequency `restfreq` at redshift `z`.

    Parameters
    ----------
    restfreq : `~astropy.units.quantity.Quantity`
        The rest frequency of the source line
    z : float
        The redshift of the source

    Returns
    -------
    obsfreq : `~astropy.units.quantity.Quantity` or float, depending on what was input
        The frequency at which `restfreq` would be observed.

    """
    return restfreq / (1.0 + z)


def restfreq(obsfreq: Quantity | float, z: float) -> Quantity | float:
    """
    The rest frequency at redfshift `z` for a give observed frequency `obsfreq`.

    Parameters
    ----------
    obsfreq : `~astropy.units.quantity.Quantity`
        The observed frequency of the source line
    z : float
        The redfshift of the source

    Returns
    -------
    restfreq: `~astropy.units.quantity.Quantity` or float, depending on what was input
        The rest frequency corresponding to `obsfreq` at redshift `z`.
    """
    return obsfreq * (1.0 + z)

def solar_coordinate(time:Time=None, frame:str|coord.BaseCoordinateFrame=coord.GCRS) -> coord.SkyCoord:
    """Determine the location of the Sun at the given time in the given reference frame.  

    Parameters
    ---------
    time : `~astropy.time.Time`
        The time at which to compute the solar position. Default: None, which means 'now'
    frame: str or `~astropy.coord.BaseCoordinateFrame`
        The coordinate reference frame in which to return the solar position.
        Can be a string, e.g. "hcrs", "gcrs", or a coordinate frame class, e.g. GGRS.  Default: GCRS

    Returns
    ------
    solar_coordinate: `~astropy.coord.SkyCoord`
        The sky position of the Sun
    """
    if time is None:
        time = Time.now()
    coord_gcrs = coord.get_sun(time)
    if isinstance(frame,str):
        frame = frame.lower()
        frame = astropy_frame_dict.get(frame,None)
    if frame == coord.GCRS:
        return coord_gcrs
    else:
        return coord_gcrs.transform_to(frame)

def sun_altaz(solar_coordinate:SkyCoord, location:EarthLocation) -> SkyCoord:
    """
    Transform a solar coordinate in a coordinate frame, e.g. GCRS, to altitude-azimuth. Note
    that `~astropy.coordinates.SkyCoord` and `~astropy.coordinates.EarthLocation` can contain more than
    one coordinate, so if the location input EarthLocation has N coordinates (e.g. antenna positions), then 
    the returned `~astropy.coordinates.SkyCoord` will contain N coords. Neato.

    Parameters
    ----------
    solar_coordinate : ~astropy.coordinates.SkyCoord
        The position of the Sun on the sky.  See :meth:`solar_coordinate`.
    location : ~astropy.coordinates.EarthLocation
        The position(s) on the ground.

    Returns
    -------
    sun_altaz : ~astropy.coordinates.SkyCoord
        The AltAz coordinates for the input EarthLocation(s)
    """
    # if location is an array, add a new axis for AltAz so arrays can be broadcast correctly.
    if location.lat.isscalar:
        altaz_frame = AltAz(location=location,obstime=solar_coordinate.obstime)
    else:
        altaz_frame = AltAz(location=location[:,np.newaxis],obstime=solar_coordinate.obstime)
    return solar_coordinate.transform_to(altaz_frame)

def sun_distance(solar_altaz:SkyCoord, antaz:np.ndarray|Angle|Quantity, antel:np.ndarray|Angle|Quantity) -> Angle:
    """
    Compute the sun distance(s) in degrees for a collection of antennas

    Parameters
    ----------
    solar_coordinate : ~astropy.coordinates.SkyCoord
        The AltAz position(s) of the Sun on the sky.  Length must match lenght of antenna azimuth and elevation 
        arrays `antaz`, `antel`. See :meth:`solar_altaz`.
    antaz : ~np.ndarray or ~astropy.coordinates.Angle or ~astropy.units.Quantity 
        The azimuths of the antennas.  If input is `~np.ndarray`, units are assumed to be degrees
    antel : ~np.ndarray or ~astropy.coordinates.Angle or ~astropy.units.Quantity 
        The elevations of the antennas.  If input is `~np.ndarray`, units are assumed to be degrees
        The azimuths of the antennas.  If input is `~np.ndarray`, units are assumed to be degrees
    """
    if ( len(antaz) != len(antel) ) or (len(antaz) != len(solar_altaz.location)):
        raise ValueError(f"Input arrays must be the same length {len(solar_altaz)=} {len(antaz)=} {len(antel)=}")
    if not hasattr(antaz,"unit"):
        antaz = antaz*u.degree
    if not hasattr(antel,"unit"):
        antel = antel*u.degree
    antenna_altaz = AltAz(az=antaz,alt=antel,obstime=solar_altaz.obstime, location=solar_altaz.location)
    # separation() will return NxN but we just want 1xN, e.g. all sun positions vs all antenna positions.  
    # The desired values are along the diagonal.  Note we assume that the ordering in solar_altaz is
    # the same as in the azel arrays.
    angles = solar_altaz.separation(antenna_altaz)
    return Angle(np.diag(angles.value)*angles.unit)

