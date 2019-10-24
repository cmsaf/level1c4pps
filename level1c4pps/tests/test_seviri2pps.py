#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2019 level1c4pps developers
#
# This file is part of level1c4pps
#
# atrain_match is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# atrain_match is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with atrain_match.  If not, see <http://www.gnu.org/licenses/>.
# Author(s):

#   Stephan Finkensieper <stephan.finkensieper@dwd.de>

"""Unit tests for the seviri2pps_lib module."""

import datetime as dt
import numpy as np
from pyresample.geometry import AreaDefinition
import unittest
from unittest import mock
import xarray as xr

import level1c4pps.seviri2pps_lib as seviri2pps
import level1c4pps.calibration_coefs as calib



class TestSeviri2PPS(unittest.TestCase):
    def test_rotate_band(self):
        """Test rotation of bands."""
        area = AreaDefinition(area_id='test',
                              description='test',
                              proj_id='test',
                              projection={'proj': 'geos', 'h': 12345},
                              width=3,
                              height=3,
                              area_extent=[1001, 1002, -1003, -1004])
        data = xr.DataArray(data=[[1, 2, 3],
                                  [4, 5, 6],
                                  [7, 8, 9]],
                            dims=('y', 'x'),
                            coords=[('y', [1.1, 0, -1.1]), ('x', [1, 0, -1])],
                            attrs={'area': area})
        scene = {'data': data}

        # Rotate
        seviri2pps.rotate_band(scene, 'data')

        # Check results
        self.assertTupleEqual(scene['data'].attrs['area'].area_extent,
                              (-1003, -1004, 1001, 1002))
        np.testing.assert_array_equal(scene['data']['x'], [-1, 0, 1])
        np.testing.assert_array_equal(scene['data']['y'], [-1.1, 0, 1.1])
        np.testing.assert_array_equal(scene['data'], [[9, 8, 7],
                                                      [6, 5, 4],
                                                      [3, 2, 1]])
        lons, lats = scene['data'].attrs['area'].get_lonlats()
        self.assertTrue(lons[0, 0] < 0)
        self.assertTrue(lons[0, 2] > 0)
        self.assertTrue(lats[0, 0] > 0)
        self.assertTrue(lons[2, 0] < 0)

    def test_get_lonlats(self):
        """Test getting lat/lon coordinates."""
        lons = np.array([1, 2, -1234, 1234], dtype=float)
        lats = np.array([-1234, 1234, 1, 2], dtype=float)
        area = mock.MagicMock()
        area.get_lonlats.return_value = lons, lats
        ds = mock.MagicMock(attrs={'area': area})

        lons_m, lats_m = seviri2pps.get_lonlats(ds)

        np.testing.assert_array_equal(lons_m, np.array([1, 2, np.nan, np.nan]))
        np.testing.assert_array_equal(lats_m, np.array([np.nan, np.nan, 1, 2]))

    @mock.patch('level1c4pps.seviri2pps_lib.sun_zenith_angle')
    @mock.patch('level1c4pps.seviri2pps_lib.get_alt_az')
    def test_get_solar_angles(self, get_alt_az, sun_zenith_angle):
        """Test getting solar angles."""
        get_alt_az.return_value = None, np.pi
        sun_zenith_angle.return_value = 'sunz'
        ds = mock.MagicMock(attrs={'start_time': 'start_time'})
        suna, sunz = seviri2pps.get_solar_angles(ds, lons='lons', lats='lats')
        self.assertEqual(suna, 180.0)
        self.assertEqual(sunz, 'sunz')
        get_alt_az.assert_called_with('start_time', 'lons', 'lats')
        sun_zenith_angle.assert_called_with('start_time', 'lons', 'lats')

    @mock.patch('level1c4pps.seviri2pps_lib.get_observer_look')
    @mock.patch('level1c4pps.seviri2pps_lib.satpy.utils.get_satpos')
    def test_get_satellite_angles(self, get_satpos, get_observer_look):
        """Test getting satellite angles."""
        def get_observer_look_patched(lon, lat, alt, *args):
            if alt == 36000*1000:
                return None, 31  # > 30
            elif alt == 36000:
                return None, 22  # < 20
            else:
                return 'sata', 176

        get_observer_look.side_effect = get_observer_look_patched
        get_satpos.return_value = 'sat_lon', 'sat_lat', 12345678
        ds = mock.MagicMock(attrs={'start_time': 'start_time'})
        sata, satz = seviri2pps.get_satellite_angles(ds, 'lons', 'lats')
        self.assertEqual(sata, 'sata')
        self.assertEqual(satz, -86)
        get_observer_look.assert_called_with('sat_lon', 'sat_lat', 12345.678,
                                             'start_time', 'lons', 'lats', 0)

        # Height in km
        get_satpos.return_value = 'sat_lon', 'sat_lat', 36000
        self.assertRaises(seviri2pps.UnexpectedSatpyVersion,
                          seviri2pps.get_satellite_angles, ds, 'lons', 'lats')

        # pyorbital behaves unexpectedly
        get_satpos.return_value = 'sat_lon', 'sat_lat', 38001
        get_observer_look.reset_mock(side_effect=True)
        get_observer_look.return_value = None, 9999
        self.assertRaises(seviri2pps.UnexpectedSatpyVersion,
                          seviri2pps.get_satellite_angles, ds, 'lons', 'lats')

    def test_set_attrs(self):
        """Test setting scene attributes."""
        seviri2pps.BANDNAMES = ['VIS006', 'IR_108']
        vis006 = mock.MagicMock(attrs={})
        ir108 = mock.MagicMock(attrs={'platform_name': 'myplatform'})
        scene_dict = {'VIS006': vis006, 'IR_108': ir108}
        scene = mock.MagicMock(attrs={})
        scene.__getitem__.side_effect = scene_dict.__getitem__

        seviri2pps.set_attrs(scene)
        self.assertEqual(scene['VIS006'].attrs['name'], 'image0')
        self.assertEqual(scene['VIS006'].attrs['id_tag'], 'ch_r06')
        self.assertEqual(scene['IR_108'].attrs['name'], 'image1')
        self.assertEqual(scene['IR_108'].attrs['id_tag'], 'ch_tb11')

    def test_set_coords(self):
        seviri2pps.BANDNAMES = ['band1', 'band2']
        band1 = xr.DataArray(data=[1, 2, 3],
                             dims=('x',),
                             coords={'acq_time': ('x', [0, 0, 0])},
                             attrs={'area': 'myarea',
                                    'start_time': dt.datetime(2009, 7, 1)})
        band2 = xr.DataArray(data=[4, 5, 6],
                             dims=('x',),
                             coords={'acq_time': ('x', [0, 0, 0])},
                             attrs={'start_time': dt.datetime(2009, 7, 1)})
        scene = {'band1': band1, 'band2': band2}
        seviri2pps.set_coords(scene)

        for band in seviri2pps.BANDNAMES:
            self.assertNotIn('acq_time', scene[band].coords)
            self.assertEqual(scene[band].attrs['coordinates'], 'lon lat')
            np.testing.assert_array_equal(
                scene[band].coords['time'].data,
                np.datetime64(dt.datetime(2009, 7, 1)))

        np.testing.assert_array_equal(scene['band1'].data, band1.data)
        np.testing.assert_array_equal(scene['band2'].data, band2.data)

    def test_add_ancillary_datasets(self):
        """Test adding ancillary datasets"""
        start_time = dt.datetime(2009, 7, 1, 0)
        end_time = dt.datetime(2009, 7, 1, 1)
        yvals = np.array([-1.0, 1.0])
        xvals = np.array([-1.1, 1.1])

        lons = np.array([[1.0, 2.0], [3.0, 4.0]])
        lats = np.array([[1.1, 2.1], [3.1, 4.1]])
        sunz = np.array([[1.2, 2.2], [3.2, 4.2]])
        satz = np.array([[1.3, 2.3], [3.3, 4.3]])
        azidiff = np.array([[1.4, 2.4], [3.4, 4.4]])

        ir_108 = xr.DataArray(data=np.array([[0.1, 0.2], [0.3, 0.4]]),
                              dims=('y', 'x'),
                              coords={'y': yvals,
                                      'x': xvals},
                              attrs={'start_time': start_time,
                                     'end_time': end_time,
                                     'orbital_parameters': 'orb_params',
                                     'georef_offset_corrected': True})
        scene = {'IR_108': ir_108}
        seviri2pps.add_ancillary_datasets(scene, lons=lons, lats=lats,
                                          sunz=sunz, satz=satz,
                                          azidiff=azidiff)

        # Test lon/lat
        np.testing.assert_array_equal(scene['lon'].data, lons)
        self.assertEqual(scene['lon'].attrs['units'], 'degrees_east')

        np.testing.assert_array_equal(scene['lat'].data, lats)
        self.assertEqual(scene['lat'].attrs['units'], 'degrees_north')

        # Test angles
        np.testing.assert_array_equal(scene['sunzenith'].data, sunz)
        self.assertEqual(scene['sunzenith'].attrs['name'], 'image11')

        np.testing.assert_array_equal(scene['satzenith'].data, satz)
        self.assertEqual(scene['satzenith'].attrs['name'], 'image12')

        np.testing.assert_array_equal(scene['azimuthdiff'].data, azidiff)
        self.assertEqual(scene['azimuthdiff'].attrs['name'], 'image13')

        for angle in ['azimuthdiff', 'satzenith', 'sunzenith']:
            self.assertTupleEqual(scene[angle].dims, ('y', 'x'))
            np.testing.assert_array_equal(scene[angle].coords['x'].data, xvals)
            np.testing.assert_array_equal(scene[angle].coords['y'].data, yvals)
            np.testing.assert_array_equal(scene[angle].coords['time'].data,
                                          np.datetime64(start_time))
            self.assertEqual(scene[angle].attrs['units'], 'degree')
            self.assertEqual(scene[angle].attrs['orbital_parameters'],
                             'orb_params')
            self.assertEqual(scene[angle].attrs['georef_offset_corrected'],
                             True)

        # Test common properties
        for name in ['lon', 'lat', 'azimuthdiff', 'satzenith', 'sunzenith']:
            self.assertTupleEqual(scene[name].dims, ('y', 'x'))
            np.testing.assert_array_equal(scene[name].coords['x'].data, xvals)
            np.testing.assert_array_equal(scene[name].coords['y'].data, yvals)
            self.assertEqual(scene[name].attrs['start_time'], start_time)
            self.assertEqual(scene[name].attrs['end_time'], end_time)

    def test_compose_filename(self):
        start_time = dt.datetime(2009, 7, 1, 12, 15)
        end_time = dt.datetime(2009, 7, 1, 12, 30)
        scene_dict = {'IR_108': mock.MagicMock(attrs={'start_time': start_time,
                                                      'end_time': end_time})}
        scene = mock.MagicMock(attrs={'platform': 'Meteosat-9'})
        scene.__getitem__.side_effect = scene_dict.__getitem__
        fname_exp = '/out/path/S_NWC_seviri_meteosat9_99999_20090701T1215000Z_20090701T1230000Z.nc'

        fname = seviri2pps.compose_filename(scene, '/out/path')
        self.assertEqual(fname, fname_exp)

    def test_get_encoding(self):
        seviri2pps.BANDNAMES = ['VIS006', 'IR_108']
        vis006 = mock.MagicMock(attrs={'name': 'image0'})
        ir_108 = mock.MagicMock(attrs={'name': 'image1'})
        scene = {'VIS006': vis006, 'IR_108': ir_108}
        enc_exp_angles = {'dtype': 'int16',
                          'scale_factor': 0.01,
                          'zlib': True,
                          'complevel': 4,
                          '_FillValue': -32767,
                          'add_offset': 0.0,
                          'chunksizes': (1, 512, 3712)}
        enc_exp_coords = {'dtype': 'float32',
                          'zlib': True,
                          'complevel': 4,
                          '_FillValue': -999.0,
                          'chunksizes': (512, 3712)}
        encoding_exp = {
            'image0': {'dtype': 'int16',
                       'scale_factor': 0.01,
                       'zlib': True,
                       'complevel': 4,
                       '_FillValue': -32767,
                       'add_offset': 0.0,
                       'chunksizes': (1, 512, 3712)},
            'image1': {'dtype': 'int16',
                        'scale_factor': 0.01,
                        '_FillValue': -32767,
                        'zlib': True,
                        'complevel': 4,
                        'add_offset': 273.15,
                        'chunksizes': (1, 512, 3712)},
            'image11': enc_exp_angles,
            'image12': enc_exp_angles,
            'image13': enc_exp_angles,
            'lon': enc_exp_coords,
            'lat': enc_exp_coords
        }
        encoding = seviri2pps.get_encoding(scene)
        self.assertDictEqual(encoding, encoding_exp)

    def test_get_header_attrs(self):
        start_time = dt.datetime(2009, 7, 1, 12, 15)
        end_time = dt.datetime(2009, 7, 1, 12, 30)
        scene = mock.MagicMock(attrs={'foo': 'bar',
                                      'start_time': start_time,
                                      'end_time': end_time})
        header_attrs_exp = {
            'foo': 'bar',
            'start_time': '2009-07-01 12:15:00',
            'end_time': '2009-07-01 12:30:00',
            'sensor': 'seviri'
        }
        header_attrs = seviri2pps.get_header_attrs(scene)
        self.assertDictEqual(header_attrs, header_attrs_exp)


class TestCalibration(unittest.TestCase):
    def test_get_calibration_for_date(self):
        """Test MODIS-intercalibrated gain and offset for specific date."""
        coefs = calib.get_calibration_for_date(
            platform='MSG3', date=dt.date(2018, 1, 18))
        REF = {
            'VIS006': {'gain': 0.023689275200000002, 'offset': -1.2081530352},
            'VIS008': {'gain': 0.029757990399999996,
                       'offset': -1.5176575103999999},
            'IR_016': {'gain': 0.0228774688, 'offset': -1.1667509087999999}}
        for channel in REF.keys():
            self.assertEqual(coefs[channel]['gain'], REF[channel]['gain'])
            self.assertEqual(coefs[channel]['offset'], REF[channel]['offset'])

    def test_get_calibration_for_time(self):
        """Test MODIS-intercalibrated gain and offset for specific time."""
        coefs = calib.get_calibration_for_time(
            platform='MSG3', time=dt.datetime(2018, 1, 18, 0, 0))
        REF = {
            'VIS006': {'gain': 0.023689275200000002, 'offset': -1.2081530352},
            'VIS008': {'gain': 0.029757990399999996,
                       'offset': -1.5176575103999999},
            'IR_016': {'gain': 0.0228774688, 'offset': -1.1667509087999999}}
        for channel in REF.keys():
            self.assertEqual(coefs[channel]['gain'], REF[channel]['gain'])
            self.assertEqual(coefs[channel]['offset'], REF[channel]['offset'])

    def test_get_calibration(self):
        """Test MODIS-intercalibrated for date and time."""
        coefs1 = calib.get_calibration_for_time(
            platform='MSG3', time=dt.datetime(2018, 1, 18, 23, 59))
        coefs2 = calib.get_calibration_for_date(
            platform='MSG3', date=dt.date(2018, 1, 19))
        for channel in coefs1.keys():
            self.assertAlmostEqual(coefs1[channel]['gain'],
                                   coefs2[channel]['gain'],
                                   delta=10e-8)
            self.assertAlmostEqual(coefs1[channel]['offset'],
                                   coefs2[channel]['offset'],
                                   delta=10e-8)


def suite():
    """Create the test suite for test_seviri2pps."""
    loader = unittest.TestLoader()
    mysuite = unittest.TestSuite()
    mysuite.addTest(loader.loadTestsFromTestCase(TestSeviri2PPS))
    mysuite.addTest(loader.loadTestsFromTestCase(TestCalibration))

    return mysuite