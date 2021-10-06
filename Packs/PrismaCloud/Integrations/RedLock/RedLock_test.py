import pytest
import json
from freezegun import freeze_time
import demistomock as demisto

integration_params = {
    'url': 'http://test.com',
    'credentials': {'identifier': 'test', 'password': 'pass'},
    'fetch_time': '3 days',
    'proxy': 'false',
    'unsecure': 'false',
}


def load_json(file: str):
    with open(file) as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def set_mocks(mocker):
    mocker.patch.object(demisto, 'params', return_value=integration_params)


@freeze_time()
def test_fetch_incident(mocker):
    from RedLock import fetch_incidents
    example_alerts = load_json('test_data/example_alert.json')
    mocker.patch('RedLock.req', return_value=example_alerts)
    incidents, last_fetches, last_seen_time = fetch_incidents()
    assert len(incidents) == 2, 'There are two alerts in example response'
    for incident, alert in zip(incidents, example_alerts):
        assert incident.get('name') == f"{alert.get('policy.name', 'No policy')} - {alert.get('id')}"
    assert last_seen_time == 1633109203697


@freeze_time("2021-07-10T16:34:14.758295 UTC+1")
def test_empty_incident(mocker):
    from RedLock import fetch_incidents
    mocker.patch('RedLock.req', return_value=[])
    incidents, last_fetches, last_seen_time = fetch_incidents()
    assert len(incidents) == 0, 'There are no alerts in example response'
    assert last_seen_time == 1625668454000
