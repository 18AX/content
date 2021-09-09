from CommonServerPython import *

# Disable insecure warnings
requests.packages.urllib3.disable_warnings()

''' CLIENT CLASS '''


class Client(BaseClient):
    def __init__(self, base_url, verify=True, proxy=False, ok_codes=(), headers=None, auth=None, token=None):
        super().__init__(base_url, verify, proxy, ok_codes, headers, auth)
        self.token = token

    def get_file_report(self, file_hash: str):
        return self._http_request(
            'POST',
            url_suffix='/get/report',
            params={'apikey': self.token, 'format': 'pdf', 'hash': file_hash},
            resp_type='response',
            ok_codes=(200, 404),
        )


''' HELPER FUNCTIONS '''


def hash_args_handler(sha256=None, md5=None):
    inputs = argToList(sha256) if sha256 else argToList(md5)
    for element in inputs:
        if sha256Regex.match(element) or md5Regex.match(element):
            continue
        raise Exception('Invalid hash. Only SHA256 and MD5 are supported.')

    return inputs


''' COMMAND FUNCTIONS '''


def test_module(client):
    try:
        wildfire_hash_example = 'dca86121cc7427e375fd24fe5871d727'  # guardrails-disable-line
        client.get_file_report(wildfire_hash_example)
    except DemistoException as e:
        if 'Forbidden' in str(e):
            return 'Authorization Error: make sure API Key is correctly set'
        else:
            raise e
    return 'ok'


def wildfire_get_report_command(client, args):
    """
    Args:
        args: the command arguments from demisto.args(), including url or file hash (sha256 or md5) to query on

    Returns:
        A single or list of CommandResults, and the status of the reports of the url or file of interest.

    """
    command_results_list = []
    sha256 = args.get('sha256')
    md5 = args.get('md5')
    inputs = hash_args_handler(sha256, md5)

    for element in inputs:
        res = client.get_file_report(element)

        if res.status_code == 200:
            file_name = 'wildfire_report_' + element + '.pdf'
            file_type = entryTypes['entryInfoFile']
            result = fileResult(file_name, res.content, file_type)  # will be saved under 'InfoFile' in the context.
            demisto.results(result)
            command_results = ''
        elif res.status_code == 404:
            command_results = 'Report not found.'
        else:
            command_results = res.content

        command_results_list.append(command_results)

    return command_results_list


''' MAIN FUNCTION '''


def main():
    command = demisto.command()
    params = demisto.params()
    args = demisto.args()

    base_url = params.get('server')
    if base_url and base_url[-1] == '/':
        base_url = base_url[:-1]
    if base_url and not base_url.endswith('/publicapi'):
        base_url += '/publicapi'
    token = params.get('token')
    verify_certificate = not params.get('insecure', False)
    proxy = params.get('proxy', False)

    headers = {'Content-Type': 'application/x-www-form-urlencoded'}

    demisto.debug(f'Command being called is {command}')

    try:
        client = Client(
            base_url=base_url,
            token=token,
            headers=headers,
            verify=verify_certificate,
            proxy=proxy,
        )

        if command == 'test-module':
            result = test_module(client)
            return_results(result)

        elif command == 'wildfire-get-report':
            return_results(wildfire_get_report_command(client, args))

    # Log exceptions and return errors
    except Exception as e:
        demisto.error(traceback.format_exc())  # print the traceback
        return_error(f'Failed to execute {demisto.command()} command.\nError:\n{str(e)}')


''' ENTRY POINT '''

if __name__ in ('__main__', '__builtin__', 'builtins'):
    main()
