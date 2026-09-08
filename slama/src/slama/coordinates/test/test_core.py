"""Unit tests for slama.coordinates.core (no network/SMAX server required).

Coordinate transforms are checked with physically-grounded assertions
(round trips, known geometric special cases) rather than hardcoded
reference numbers where possible, so the tests stay meaningful if
astropy's internal ephemeris/IERS data changes.
"""
import numpy as np
import pytest
import astropy.coordinates as coord
import astropy.units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time

from slama.coordinates.core import (
    KMS,
    MPS,
    SMA,
    astropy_frame_dict,
    crval4_to_pol,
    eq2hor,
    fake_sma_antpos,
    hor2eq,
    obsfreq,
    ra2ha,
    restfreq,
    sma_location,
    solar_coordinate,
    sun_altaz,
    sun_distance,
    sun_distance_from_coord,
)


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

class TestUnits:
    def test_mps_is_meters_per_second(self):
        assert MPS == u.m / u.s

    def test_kms_is_km_per_second(self):
        assert KMS == u.km / u.s


# ---------------------------------------------------------------------------
# sma_location / SMA singleton
# ---------------------------------------------------------------------------

class TestSmaLocation:
    def test_returns_earthlocation(self):
        assert isinstance(sma_location(), EarthLocation)

    def test_known_lat_lon_height(self):
        sma = sma_location()
        assert sma.lat.deg == pytest.approx(19.8620556, abs=1e-6)
        assert sma.lon.deg == pytest.approx(-155.4795556, abs=1e-6)
        assert sma.height.to(u.m).value == pytest.approx(4080, abs=1e-6)


class TestSmaSingleton:
    def test_returns_same_instance_every_call(self):
        assert SMA() is SMA()

    def test_matches_sma_location(self):
        s = SMA()
        expected = sma_location()
        assert s.lat.deg == pytest.approx(expected.lat.deg)
        assert s.lon.deg == pytest.approx(expected.lon.deg)


# ---------------------------------------------------------------------------
# fake_sma_antpos
# ---------------------------------------------------------------------------

class TestFakeSmaAntpos:
    def test_returns_eight_antennas(self):
        antpos = fake_sma_antpos()
        assert len(antpos) == 8

    def test_positions_are_near_array_center(self):
        # By construction, each antenna is offset from SMA() by
        # [0, 0.005) deg in lat/lon and [0, 2) m in height.
        s = SMA()
        antpos = fake_sma_antpos()
        assert np.all(antpos.lat.deg >= s.lat.deg)
        assert np.all(antpos.lat.deg <= s.lat.deg + 0.005)
        assert np.all(antpos.lon.deg >= s.lon.deg)
        assert np.all(antpos.lon.deg <= s.lon.deg + 0.005)
        assert np.all(antpos.height.to(u.m).value >= s.height.to(u.m).value)
        assert np.all(antpos.height.to(u.m).value <= s.height.to(u.m).value + 2)


# ---------------------------------------------------------------------------
# ra2ha
# ---------------------------------------------------------------------------

class TestRa2Ha:
    def test_zero_lst_zero_ra(self):
        assert ra2ha(lst=0, ra=0) == 0.0

    def test_no_wrap_needed(self):
        # LST = 12h = 180 deg; RA = 0 -> HA = 180 deg = 12 hr, right at
        # the (inclusive) wrap boundary, so no wrap applied.
        assert ra2ha(lst=12 * 3600, ra=0) == 12.0

    def test_wraps_above_180_degrees(self):
        # LST = 20h = 300 deg; RA = 0 -> HA_deg = 300, wraps to -60 deg
        # -> -4.0 hr.
        assert ra2ha(lst=20 * 3600, ra=0) == -4.0

    def test_wraps_below_negative_180_degrees(self):
        # LST = 0; RA = 200 deg -> HA_deg = -200, wraps to 160 deg
        # -> 160/15 = 10.666... -> 10.67 hr.
        assert ra2ha(lst=0, ra=200) == 10.67


# ---------------------------------------------------------------------------
# obsfreq / restfreq
# ---------------------------------------------------------------------------

class TestObsfreqRestfreq:
    def test_obsfreq_plain_float(self):
        assert obsfreq(100.0, z=1.0) == pytest.approx(50.0)

    def test_restfreq_plain_float(self):
        assert restfreq(50.0, z=1.0) == pytest.approx(100.0)

    def test_zero_redshift_is_identity(self):
        assert obsfreq(115.271 * u.GHz, z=0.0) == 115.271 * u.GHz
        assert restfreq(115.271 * u.GHz, z=0.0) == 115.271 * u.GHz

    def test_round_trip_with_quantity(self):
        rest = 115.271 * u.GHz
        z = 0.02
        assert restfreq(obsfreq(rest, z), z).to_value(u.GHz) == pytest.approx(rest.value)

    def test_obsfreq_preserves_quantity_type(self):
        result = obsfreq(115.271 * u.GHz, z=0.5)
        assert isinstance(result, u.Quantity)
        assert result.unit == u.GHz


# ---------------------------------------------------------------------------
# eq2hor / hor2eq
# ---------------------------------------------------------------------------

class TestEq2Hor:
    def test_returns_altaz(self):
        # transform_to() on a SkyCoord always returns a SkyCoord, whose
        # .frame is the requested AltAz frame -- not a bare AltAz.
        result = eq2hor(lon=83.6331, lat=22.0145, frame="icrs", date_obs="2024-01-01T00:00:00")
        assert isinstance(result, SkyCoord)
        assert isinstance(result.frame, AltAz)

    def test_alt_and_az_are_finite_degrees(self):
        result = eq2hor(lon=83.6331, lat=22.0145, frame="icrs", date_obs="2024-01-01T00:00:00")
        assert np.isfinite(result.alt.deg)
        assert np.isfinite(result.az.deg)
        assert -90.0 <= result.alt.deg <= 90.0
        assert 0.0 <= result.az.deg < 360.0


class TestHor2Eq:
    def test_returns_skycoord_in_requested_frame(self):
        result = hor2eq(az=0, alt=45, frame="icrs", date_obs="2024-01-01T00:00:00")
        assert isinstance(result, SkyCoord)
        assert result.frame.name == "icrs"

    def test_zenith_declination_matches_site_latitude(self):
        # At alt=90 (zenith), the equatorial declination at the SMA
        # should be close to the SMA's own geodetic latitude -- exact
        # equality doesn't hold because ICRS declination also picks up
        # geodetic-vs-geocentric latitude difference, precession,
        # nutation, and aberration, which together amount to a few
        # tenths of a degree.
        result = hor2eq(az=0, alt=90, frame="icrs", date_obs="2024-06-15T08:00:00")
        assert result.dec.deg == pytest.approx(SMA().lat.deg, abs=0.2)


class TestEqHorRoundTrip:
    def test_eq_to_hor_to_eq_recovers_original_coordinates(self):
        lon, lat = 210.8023, -60.8339  # arbitrary but fixed ICRS position
        date_obs = "2025-03-21T04:00:00"
        altaz = eq2hor(lon=lon, lat=lat, frame="icrs", date_obs=date_obs)
        back = SkyCoord(altaz).transform_to("icrs")
        assert back.ra.deg == pytest.approx(lon, abs=1e-6)
        assert back.dec.deg == pytest.approx(lat, abs=1e-6)

    def test_hor_to_eq_to_hor_recovers_original_coordinates(self):
        az, alt = 123.4, 37.5
        date_obs = "2025-03-21T04:00:00"
        eq = hor2eq(az=az, alt=alt, frame="icrs", date_obs=date_obs)
        back = eq2hor(lon=eq.ra.deg, lat=eq.dec.deg, frame="icrs", date_obs=date_obs)
        assert back.az.deg == pytest.approx(az, abs=1e-6)
        assert back.alt.deg == pytest.approx(alt, abs=1e-6)


# ---------------------------------------------------------------------------
# solar_coordinate
# ---------------------------------------------------------------------------

class TestSolarCoordinate:
    FIXED_TIME = Time("2025-06-21T12:00:00")

    def test_default_frame_matches_get_sun(self):
        expected = coord.get_sun(self.FIXED_TIME)
        result = solar_coordinate(time=self.FIXED_TIME)
        assert result.separation(expected).arcsec == pytest.approx(0.0, abs=1e-6)

    def test_string_frame_transforms(self):
        result = solar_coordinate(time=self.FIXED_TIME, frame="hcrs")
        assert isinstance(result.frame, coord.HCRS)

    def test_frame_class_transforms(self):
        result = solar_coordinate(time=self.FIXED_TIME, frame=coord.HCRS)
        assert isinstance(result.frame, coord.HCRS)

    def test_gcrs_frame_class_is_passthrough(self):
        result = solar_coordinate(time=self.FIXED_TIME, frame=coord.GCRS)
        assert isinstance(result.frame, coord.GCRS)

    def test_none_time_defaults_to_now(self):
        before = Time.now()
        result = solar_coordinate()
        after = Time.now()
        assert before <= result.obstime <= after

    def test_deterministic_for_fixed_time(self):
        a = solar_coordinate(time=self.FIXED_TIME)
        b = solar_coordinate(time=self.FIXED_TIME)
        assert a.separation(b).arcsec == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# sun_altaz
# ---------------------------------------------------------------------------

class TestSunAltaz:
    FIXED_TIME = Time("2025-06-21T20:00:00")

    def test_scalar_location_returns_single_altaz(self):
        sun = solar_coordinate(time=self.FIXED_TIME)
        altaz = sun_altaz(sun, SMA())
        assert altaz.frame.name == "altaz"
        assert altaz.isscalar

    def test_array_location_returns_one_per_antenna(self):
        sun = solar_coordinate(time=self.FIXED_TIME)
        antpos = fake_sma_antpos()
        altaz = sun_altaz(sun, antpos)
        assert len(altaz) == 8

    def test_array_altaz_agrees_closely_with_single_site(self):
        # SMA's baselines (~500 m) are negligible next to the Sun's
        # ~1 AU distance, so every antenna should see the Sun at
        # essentially the same alt/az as the array-center computation.
        sun = solar_coordinate(time=self.FIXED_TIME)
        single = sun_altaz(sun, SMA())
        antpos = fake_sma_antpos()
        per_antenna = sun_altaz(sun, antpos)
        assert np.allclose(per_antenna.alt.deg, single.alt.deg, atol=0.01)
        assert np.allclose(per_antenna.az.deg, single.az.deg, atol=0.01)


# ---------------------------------------------------------------------------
# sun_distance
# ---------------------------------------------------------------------------

class TestSunDistanceFromCoord:
    """sun_distance_from_coord(solar_altaz, antaz, antel) -- the original
    SkyCoord/EarthLocation-based path (renamed from sun_distance when
    the simpler 4-angle sun_distance() was added; see
    docs/monitorsystem_writer_design.md and conf/computations.json)."""

    FIXED_TIME = Time("2025-06-21T20:00:00")

    def _sun_altaz_for_antennas(self):
        sun = solar_coordinate(time=self.FIXED_TIME)
        antpos = fake_sma_antpos()
        return sun_altaz(sun, antpos)

    def test_pointing_at_the_sun_gives_zero_distance(self):
        solar_altaz = self._sun_altaz_for_antennas()
        antaz = solar_altaz.az.deg
        antel = solar_altaz.alt.deg
        distances = sun_distance_from_coord(solar_altaz, antaz, antel)
        assert np.allclose(distances.deg, 0.0, atol=1e-6)

    def test_mismatched_lengths_raise(self):
        solar_altaz = self._sun_altaz_for_antennas()
        with pytest.raises(ValueError):
            sun_distance_from_coord(solar_altaz, np.zeros(3), np.zeros(3))

    def test_plain_ndarray_assumed_degrees(self):
        solar_altaz = self._sun_altaz_for_antennas()
        antaz_deg = solar_altaz.az.deg
        antel_deg = solar_altaz.alt.deg
        as_array = sun_distance_from_coord(solar_altaz, antaz_deg, antel_deg)
        as_quantity = sun_distance_from_coord(solar_altaz, antaz_deg * u.degree, antel_deg * u.degree)
        assert np.allclose(as_array.deg, as_quantity.deg)

    def test_offset_pointing_gives_nonzero_distance(self):
        solar_altaz = self._sun_altaz_for_antennas()
        antaz = solar_altaz.az.deg + 10.0
        antel = solar_altaz.alt.deg
        distances = sun_distance_from_coord(solar_altaz, antaz, antel)
        assert np.all(distances.deg > 0.0)


class TestSunDistance:
    """sun_distance(sunaz, sunel, antaz, antel) -- angular separation
    between two (az, el) pairs directly, no EarthLocation/SkyCoord
    needed. Used by the monitor.compute 'sun_distance' function, one
    antenna per call (see conf/computations.json)."""

    def test_elevation_only_offset(self):
        d = sun_distance(100.0, 30.0, 100.0, 35.0)
        assert d.deg == pytest.approx(5.0)

    def test_pointing_directly_at_the_sun_is_zero(self):
        d = sun_distance(210.0, 42.0, 210.0, 42.0)
        assert d.deg == pytest.approx(0.0, abs=1e-9)

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError):
            sun_distance(np.zeros(3), np.zeros(3), np.zeros(4), np.zeros(4))

    def test_plain_float_assumed_degrees(self):
        as_plain = sun_distance(100.0, 30.0, 100.0, 35.0)
        as_quantity = sun_distance(100.0 * u.degree, 30.0 * u.degree, 100.0 * u.degree, 35.0 * u.degree)
        assert as_plain.deg == pytest.approx(as_quantity.deg)

    def test_array_inputs(self):
        sunaz = np.array([100.0, 200.0])
        sunel = np.array([30.0, 40.0])
        antaz = np.array([100.0, 200.0])
        antel = np.array([35.0, 40.0])
        d = sun_distance(sunaz, sunel, antaz, antel)
        assert np.allclose(d.deg, [5.0, 0.0])


# ---------------------------------------------------------------------------
# Static frame/label dictionaries -- light sanity checks
# ---------------------------------------------------------------------------

class TestFrameDictionaries:
    def test_astropy_frame_dict_values_are_frame_classes(self):
        for key, value in astropy_frame_dict.items():
            assert isinstance(value, type), f"{key!r} -> {value!r} is not a class"

    def test_crval4_to_pol_known_entries(self):
        assert crval4_to_pol[-1] == "RR"
        assert crval4_to_pol[-5] == "XX"
        assert crval4_to_pol[0] == "UNKNOWN"
        assert crval4_to_pol[1] == "I"
