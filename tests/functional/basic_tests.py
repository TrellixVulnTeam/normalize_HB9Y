import json
from os import path, getenv, mkdir
import logging
import tempfile

from normalize.app import app

# Setup/Teardown

_tempdir: str = ""


def setup_module():
    print(f" == Setting up tests for {__name__}")
    app.config['TESTING'] = True

    global _tempdir
    _tempdir = getenv('TEMPDIR')
    if _tempdir:
        try:
            mkdir(_tempdir)
        except FileExistsError:
            pass
    else:
        _tempdir = tempfile.gettempdir()


def teardown_module():
    print(f" == Tearing down tests for {__name__}")


dirname = path.dirname(__file__)
corfu_shp_path = path.join(dirname, '..', 'test_data/get_pois_v02_corfu_2100.zip')
hotel_shp_path = path.join(dirname, '..', 'test_data/MR_TT_Hotel_THA.zip')
corfu_csv_path = path.join(dirname, '..', 'test_data/osm20_pois_corfu.csv')


def _check_all_fields_are_present(expected: set, r: dict, api_path: str):
    """Check that all expected fields are present in a JSON response object (only examines top-level fields)"""
    missing = expected.difference(r.keys())
    if missing:
        logging.error(f'{api_path}: the response contained the fields {list(r.keys())} '
                      f' but it was missing the following fields: {missing}')
        assert False, 'The response is missing some fields'


def _check_endpoint(path_to_test: str, data: dict, expected_fields: set, content_type: str = 'multipart/form-data'):
    """Check an endpoint of the profile microservice"""
    with app.test_client() as client:
        # Test if it fails when no file is submitted
        res = client.post(path_to_test, content_type=content_type)
        assert res.status_code == 400
        # Test if it succeeds when a file is submitted
        res = client.post(path_to_test, data=data, content_type=content_type)
        assert res.status_code in [200, 202]
        # Test if it returns the expected fields
        r = json.loads(res.get_data(as_text=True))
        _check_all_fields_are_present(expected_fields, r, path_to_test)


#
# Tests
#


def test_get_documentation_1():
    with app.test_client() as client:
        res = client.get('/', query_string=dict(), headers=dict())
        assert res.status_code == 200
        r = res.get_json()
        assert not (r.get('openapi') is None)


def test_get_health_check():
    with app.test_client() as client:
        res = client.get('/_health', query_string=dict(), headers=dict())
        assert res.status_code == 200
        r = res.get_json()
        if 'reason' in r:
            logging.error('The service is unhealthy: %(reason)s\n%(detail)s', r)
        logging.debug("From /_health: %s" % r)
        assert r['status'] == 'OK'
