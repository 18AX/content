import demistomock as demisto
from CommonServerPython import *
from CommonServerUserPython import *

from urllib.parse import urlparse
import urllib.parse
from tldextract import extract
from typing import Type, Tuple, List, Dict, Union
import dill

dill.settings['recurse'] = True
import pandas as pd
import base64
import requests
import dill
import copy
import datetime
import numpy as np

MSG_INVALID_URL = "URL does not seem to be valid. Reason: "
MSG_NO_URL_GIVEN = "Please input at least one URL"
MSG_FAILED_RASTERIZE = "Rasterize for this url did not work correctly"
MSG_IMPOSSIBLE_CONNECTION = "Failed to establish a new connection - Name or service not known"
MSG_WHITE_LIST = "White List"
EMPTY_STRING = ""
URL_PHISHING_MODEL_NAME = "phishing_model"
OUT_OF_THE_BOX_MODEL_PATH = '/model/model_docker.pkl'
SCRIPT_MODEL_VERSION = '0.0'
OOB_VERSION_INFO_KEY = 'oob_version'
UNKNOWN_MODEL_TYPE = 'UNKNOWN_MODEL_TYPE'
THRESHOLD_NEW_DOMAIN_YEAR = 0.5
DOMAIN_AGE_KEY = 'New domain (less than %s year)' %str(THRESHOLD_NEW_DOMAIN_YEAR)

MALICIOUS_VERDICT = "malicious"
BENIGN_VERDICT = "benign"
BENIGN_VERDICT_WHITELIST = "benign - whitelist"
SUSPICIOUS_VERDICT = "suspicious"

BENIGN_THRESHOLD = 0.5
SUSPICIOUS_THRESHOLD = 0.7

SCORE_INVALID_URL = -1
SCORE_BENIGN = 0


GREEN_COLOR = "{{color:#15ff2c}}(%s)"
RED_COLOR = "{{color:#fd0800}}(%s)"

VERDICT_MALICIOUS_COLOR = "{{background:#fd0800}}({{color:#ffffff}}(**%s**))"
VERDICT_SUSPICIOUS_COLOR = "{{background:#fd9a14}}({{color:#ffffff}}(**%s**))"
VERDICT_BENIGN_COLOR = "{{background:#15ff2c}}({{color:#ffffff}}(**%s**))"
VERDICT_ERROR_COLOR = "{{background:#feff2b}}({{color:#000000}}(**%s**))"
MAPPING_VERDICT_COLOR = {MALICIOUS_VERDICT:VERDICT_MALICIOUS_COLOR, BENIGN_VERDICT:VERDICT_BENIGN_COLOR,
                         SUSPICIOUS_VERDICT:VERDICT_SUSPICIOUS_COLOR, BENIGN_VERDICT_WHITELIST:VERDICT_BENIGN_COLOR}

SCORE_THRESHOLD = 0.7

STATUS_CODE_VALID = 200

MODEL_KEY_URL_SCORE = 'url_score'
MODEL_KEY_LOGO_FOUND = 'logo_found'
MODEL_KEY_SEO = 'seo'
MODEL_KEY_LOGO_IMAGE_BYTES = 'image_bytes'
MODEL_KEY_LOGO_LOGIN_FORM = 'login_form'

WEIGHT_HEURISTIC = {DOMAIN_AGE_KEY: 1, MODEL_KEY_LOGO_LOGIN_FORM: 1, MODEL_KEY_SEO: 1,
                    MODEL_KEY_URL_SCORE: 2, MODEL_KEY_LOGO_FOUND: 1}


def get_model_data(model_name: str) -> Union[str, str]:
    """
    Return model data saved in demisto (string of encoded base 64)
    :param model_name: name of the model to load from demisto
    :return: str, str
    """
    res_model = demisto.executeCommand("getMLModel", {"modelName": model_name})[0]
    if is_error(res_model):
        handle_error("error reading model %s from Demisto" % model_name)
    else:
        model_data = res_model['Contents']['modelData']
        try:
            model_type = res_model['Contents']['model']["type"]["type"]
            return model_data, model_type
        except Exception:
            return model_data, UNKNOWN_MODEL_TYPE


def decode_model_data(model_data: str):
    """
    Decode the base 64 version of the model
    :param model_data: string of the encoded based 64 model
    :return: Model
    """
    return dill.loads(base64.b64decode(model_data.encode('utf-8')))


def load_oob(path=OUT_OF_THE_BOX_MODEL_PATH):
    """
    Load pickle model from the docker
    :param path: path of the model saved in the docker
    :return: bytes
    """
    with open(path, 'rb') as f:
        model_b = f.read()
        model_64 = base64.b64encode(model_b)
    return model_64


def load_oob_model(path: str = OUT_OF_THE_BOX_MODEL_PATH):
    """
    Load and save model from the model in the docker
    :return: None
    """
    try:
        encoded_model = load_oob(path)
    except Exception:
        return_error(traceback.format_exc())
    res = demisto.executeCommand('createMLModel', {'modelData': encoded_model.decode('utf-8'),
                                                   'modelName': URL_PHISHING_MODEL_NAME,
                                                   'modelLabels': [MALICIOUS_VERDICT, BENIGN_VERDICT],
                                                   'modelOverride': 'true',
                                                   'modelHidden': True,
                                                   'modelType': 'url_phishing',
                                                   'modelExtraInfo': {
                                                       OOB_VERSION_INFO_KEY: SCRIPT_MODEL_VERSION
                                                   }
                                                   })
    if is_error(res):
        return_error(get_error(res))


def oob_model_exists_and_updated() -> bool:
    """
    Check is the model exist and is updated in demisto
    :return: book
    """
    res_model = demisto.executeCommand("getMLModel", {"modelName": URL_PHISHING_MODEL_NAME})[0]
    if is_error(res_model):
        return False
    existing_model_version = res_model['Contents']['model']['extra'].get(OOB_VERSION_INFO_KEY, -1)
    return existing_model_version == SCRIPT_MODEL_VERSION


def image_from_base64_to_bytes(base64_message: str):
    """
    Transform image from base64 string into bytes
    :param base64_message:
    :return:
    """
    base64_bytes = base64_message.encode('utf-8')
    message_bytes = base64.b64decode(base64_bytes)
    return message_bytes


def extract_domainv2(url: str):
    """
    Return domain (SLD + TLD)
    :param url: URL from which to extract domain name
    :return:str
    """
    parts = extract(url)
    return parts.domain + "." + parts.suffix


def in_white_list(model, url: str) -> bool:
    """
    Check if url belongs to the Model whitelist
    :param model: model which contains top_domains attribute
    :param url: url to check
    :return:
    """
    if (extract_domainv2(url) in model.top_domains):
        return True
    else:
        return False


def get_colored_pred_json(pred_json: Dict) -> Dict:
    """
    Create copy and color json values according to their values.
    :param pred_json: json to color
    :return: json
    """
    pred_json_colored = copy.deepcopy(pred_json)
    pred_json_colored[MODEL_KEY_SEO] = GREEN_COLOR % pred_json[MODEL_KEY_SEO] if not pred_json[MODEL_KEY_SEO] else RED_COLOR % pred_json[MODEL_KEY_SEO]
    pred_json_colored[MODEL_KEY_LOGO_FOUND] = GREEN_COLOR % pred_json[MODEL_KEY_LOGO_FOUND] if not pred_json[
        MODEL_KEY_LOGO_FOUND] else RED_COLOR % pred_json[MODEL_KEY_LOGO_FOUND]
    pred_json_colored[MODEL_KEY_LOGO_LOGIN_FORM] = GREEN_COLOR % pred_json[MODEL_KEY_LOGO_LOGIN_FORM] if not pred_json[
        MODEL_KEY_LOGO_LOGIN_FORM] else RED_COLOR % pred_json[MODEL_KEY_LOGO_LOGIN_FORM]
    pred_json_colored[DOMAIN_AGE_KEY] = GREEN_COLOR % pred_json[DOMAIN_AGE_KEY] if not pred_json[
        DOMAIN_AGE_KEY] else RED_COLOR % pred_json[DOMAIN_AGE_KEY]
    return pred_json_colored


def create_X_pred(output_rasterize: Dict, url: str) -> pd.DataFrame:
    """
    Create dataframe to predict from the rasterize output
    :param output_rasterize: Dict from the output of rasterize command
    :param url: url to examine
    :return: pd.DataFrame
    """
    website64 = output_rasterize.get('image_b64', None)
    html = output_rasterize.get('html', None)
    X_pred = pd.DataFrame(columns=['name', 'image', 'html'])
    X_pred.loc[0] = [url, website64, html]
    return X_pred


def prepend_protocol(url: str, protocol: str, www: bool = True) -> str:
    """
    Append a protocol name (usually http or https) and www to a url
    :param url: url
    :param protocol: protocol we want to add (usually http or https)
    :return: str
    """
    p = urllib.parse.urlparse(url, protocol)
    netloc = p.netloc or p.path
    path = p.path if p.netloc else ''
    if not netloc.startswith('www.') and www:
        netloc = 'www.' + netloc
    p = urllib.parse.ParseResult(protocol, netloc, path, *p[3:])
    return p.geturl()


def is_valid_url(url: str) -> bool:
    """
    Check is an url is valid by requesting it using different protocol
    :param url: url
    :return: bool
    """
    try:
        response = requests.get(url, verify=False)
    except requests.exceptions.RequestException as e:
        prepend_url = prepend_protocol(url, 'http', True)
        try:
            response = requests.get(prepend_url, verify=False)
        except requests.exceptions.RequestException as e:
            prepend_url = prepend_protocol(url, 'https', True)
            try:
                response = requests.get(prepend_url, verify=False)
            except requests.exceptions.RequestException as e:
                prepend_url = prepend_protocol(url, 'http', False)
                try:
                    response = requests.get(prepend_url, verify=False)
                except requests.exceptions.RequestException as e:
                    prepend_url = prepend_protocol(url, 'https', False)
                    try:
                        response = requests.get(prepend_url, verify=False)
                    except requests.exceptions.RequestException as e:
                        return False, MSG_IMPOSSIBLE_CONNECTION
    if response.status_code == 200:
        return True, EMPTY_STRING
    else:
        return False, response.reason


def return_entry_summary(pred_json: Dict, url: str, verdict: str, whitelist: bool):
    """
    Return entry to demisto
    :param pred_json: json with output of the model
    :param url: url
    :param verdict: output of the verdict heuristic
    :param whitelist: if url belongs to whitelist of the model
    :return: entry to demisto
    """
    if not pred_json:
        return
    if whitelist:
        url_score = SCORE_BENIGN
        url_score = GREEN_COLOR % str(url_score) if url_score < SCORE_THRESHOLD else RED_COLOR % str(
            url_score)  # GREEN_COLOR%'0'
    else:
        url_score = pred_json[MODEL_KEY_URL_SCORE]
        url_score = GREEN_COLOR % str(url_score) if url_score < SCORE_THRESHOLD else RED_COLOR % str(url_score)
    pred_json_colored = get_colored_pred_json(pred_json)
    domain = extract_domainv2(url)
    explain = {
        "Domain": domain,
        "URL": url,
        "NewDomain": str(pred_json[DOMAIN_AGE_KEY]),
        "LogoFound": str(pred_json[MODEL_KEY_LOGO_FOUND]),
        "LoginForm": str(pred_json[MODEL_KEY_LOGO_LOGIN_FORM]),
        "URLScore": url_score,
        "ContentBasedVerdict": str(pred_json[MODEL_KEY_SEO])
    }
    explain_hr = {
        "Domain from the URL": domain,
        "Has the domain bad SEO ?": str(pred_json_colored[MODEL_KEY_SEO]),
        DOMAIN_AGE_KEY: str(pred_json_colored[DOMAIN_AGE_KEY]),
        "Has the website a login form?": str(pred_json_colored[MODEL_KEY_LOGO_LOGIN_FORM]),
        "Logo found that does not correspond to the given domain": str(pred_json_colored[MODEL_KEY_LOGO_FOUND]),
        "URL severity score (from 0 to 1)": url_score
    }
    return_entry = {
        "Type": entryTypes["note"],
        "ContentsFormat": formats['json'],
        "HumanReadable": tableToMarkdown("Report %s" %domain, explain_hr),
        "Contents": explain,
        "EntryContext": {'DBotPredictURLPhishing': explain}
    }
    demisto.results(return_entry)
    # Get rasterize image or logo detection if logo was found
    image = pred_json[MODEL_KEY_LOGO_IMAGE_BYTES]
    if not image:
        return
        image = image_from_base64_to_bytes(output_rasterize.get('image_b64', None))
    res = fileResult(filename='Logo detection engine', data=image)
    res['Type'] = entryTypes['image']
    demisto.results(res)


def return_entry_white_list(url):
    """
    Create syntethci entry when url belongs to whitelist
    :param url: url
    :return:
    """
    explain = {
        "Domain": extract_domainv2(url),
        "URL": url,
        "NewDomain": MSG_WHITE_LIST,
        "LogoFound": MSG_WHITE_LIST,
        "LoginPage": MSG_WHITE_LIST,
        "URLScore": MSG_WHITE_LIST,
        "ContentBasedVerdict": MSG_WHITE_LIST
    }
    explain_hr = {
        "Domain": extract_domainv2(url),
        "Has the domain good SEO ?": MSG_WHITE_LIST,
        DOMAIN_AGE_KEY: MSG_WHITE_LIST,
        "Has the website a login page?": MSG_WHITE_LIST,
        "Logo found that does not correspond to the given domain": MSG_WHITE_LIST,
        "URL severity score (from 0 to 1)": MSG_WHITE_LIST
    }
    verdict_hr = {
        "Verdict": BENIGN_VERDICT,
        "URL": url
    }
    return_entry = {
        "Type": entryTypes["note"],
        "ContentsFormat": formats['json'],
        "HumanReadable": tableToMarkdown("Verdict", verdict_hr) + tableToMarkdown("Report", explain_hr),
        "Contents": explain,
        "EntryContext": {'DBotPredictURLPhishing': explain}
    }
    demisto.results(return_entry)


def get_score(pred_json):
    use_age = False
    use_logo = False
    if pred_json[DOMAIN_AGE_KEY]:
        use_age = True
    if pred_json[MODEL_KEY_LOGO_FOUND]:
        use_logo = True
    total_weight_used = WEIGHT_HEURISTIC[DOMAIN_AGE_KEY] * use_age + \
                        WEIGHT_HEURISTIC[MODEL_KEY_LOGO_LOGIN_FORM] + \
                        WEIGHT_HEURISTIC[MODEL_KEY_SEO]+ \
                        WEIGHT_HEURISTIC[MODEL_KEY_URL_SCORE]+ \
                        WEIGHT_HEURISTIC[MODEL_KEY_LOGO_FOUND] * use_logo
    score = (
             use_age * WEIGHT_HEURISTIC[DOMAIN_AGE_KEY]*pred_json[DOMAIN_AGE_KEY] +
             WEIGHT_HEURISTIC[MODEL_KEY_LOGO_LOGIN_FORM]*pred_json[MODEL_KEY_LOGO_LOGIN_FORM] +
             WEIGHT_HEURISTIC[MODEL_KEY_SEO] * pred_json[MODEL_KEY_SEO] +
             WEIGHT_HEURISTIC[MODEL_KEY_URL_SCORE] * pred_json[MODEL_KEY_URL_SCORE] +
             use_logo * WEIGHT_HEURISTIC[MODEL_KEY_LOGO_FOUND] * pred_json[MODEL_KEY_LOGO_FOUND]
            ) / (total_weight_used)
    return score



def get_verdict(pred_json: Dict, is_white_listed: bool) -> Union[float, str]:
    """
    Return verdict of the url based on the output of the model
    :param pred_json: output from the model
    :return:
    """
    if is_white_listed:
        return SCORE_BENIGN, BENIGN_VERDICT
    score = get_score(pred_json)
    if pred_json[MODEL_KEY_LOGO_FOUND]:
        return score, MALICIOUS_VERDICT
    else:
        if score < BENIGN_THRESHOLD:
            return score, BENIGN_VERDICT
        elif score < SUSPICIOUS_THRESHOLD:
            return score, SUSPICIOUS_VERDICT
        else:
            return score, MALICIOUS_VERDICT

def create_dict_context(url, verdict, pred_json, score, is_white_listed):
    return {'url': url, 'verdict': verdict, 'pred_json': pred_json, 'score': score, 'is_white_listed': is_white_listed}

def extract_created_date(entry_list: List) -> bool:
    """
    Check if domain age is younger than THRESHOLD_NEW_DOMAIN_YEAR year
    :param entry_list: output of the whois command
    :return: bool
    """
    for entry in entry_list:
        if is_error(entry):
            continue
        else:
            date_str = entry['EntryContext'].get('Domain(val.Name && val.Name == obj.Name)').get('WHOIS').get('CreationDate')
            if date_str:
                date = datetime.datetime.strptime(date_str, '%d-%m-%Y')
                threshold_date = datetime.datetime.now() - datetime.timedelta(days=THRESHOLD_NEW_DOMAIN_YEAR * 365)
                return date > threshold_date
    return  False

def get_prediction_single_url(model, url, force_model):
    is_white_listed = False
    # Check if URL is valid and accessible
    valid_url, error = is_valid_url(url)
    if not valid_url:
        return create_dict_context(url, MSG_INVALID_URL + error, {}, SCORE_INVALID_URL, is_white_listed)

    #Check domain age from WHOIS command
    domain = extract_domainv2(url)
    res = demisto.executeCommand('whois', {'query': domain,
                                       })
    is_new_domain = extract_created_date(res)

    # Check is domain in white list -  If yes we don't run the model
    if in_white_list(model, url):
        if not force_model:
            return create_dict_context(url, BENIGN_VERDICT_WHITELIST, {}, SCORE_BENIGN, is_white_listed)
        else:
            is_white_listed = True

    # Rasterize html and image
    res = demisto.executeCommand('rasterize', {'type': 'json',
                                               'url': url,
                                               })
    if len(res) > 0:
        output_rasterize = res[0]['Contents']
    else:
        return_error(MSG_FAILED_RASTERIZE)

    # Create X_pred
    if isinstance(output_rasterize, str):
        return_error(output_rasterize)
    X_pred = create_X_pred(output_rasterize, url)

    # Prediction of the model
    pred_json = model.predict(X_pred)
    pred_json[DOMAIN_AGE_KEY] = is_new_domain

    score, verdict = get_verdict(pred_json, is_white_listed)

    return create_dict_context(url, verdict, pred_json, score, is_white_listed)


def return_general_summary(results, tag="Summary"):
    df_summary = pd.DataFrame()
    df_summary['url'] = [x.get('url') for x in results]
    df_summary['verdict'] = [MAPPING_VERDICT_COLOR[x.get('verdict')] %x.get('verdict') if x.get('verdict')
                                                                                           in MAPPING_VERDICT_COLOR.keys()
                             else VERDICT_ERROR_COLOR %x.get('verdict') for x in results ]
    df_summary_json = df_summary.to_dict(orient='records')
    return_entry = {
        "Type": entryTypes["note"],
        "ContentsFormat": formats['json'],
        "HumanReadable": tableToMarkdown("Summary", df_summary_json),
        "Contents": df_summary_json,
        "EntryContext": {'DBotPredictURLPhishing': df_summary_json}
    }
    if tag is not None:
        return_entry["Tags"] = ['SimilarIncidents_{}'.format(tag)]
    demisto.results(return_entry)

def return_detailed_summary(results, number_entries_to_return):
    severity_list = [x.get('score') for x in results]
    indice_descending_severity = np.argsort(-np.array(severity_list), kind='mergesort')
    for i in range(min(number_entries_to_return, len(results))):
        index = indice_descending_severity[i]
        pred_json = results[index].get('pred_json')
        url = results[index].get('url')
        verdict = results[index].get('verdict')
        is_white_listed = results[index].get('is_white_listed')
        return_entry_summary(pred_json, url, verdict, is_white_listed)



def main():
    if not oob_model_exists_and_updated():
        load_oob_model()
    model_64_str = get_model_data(URL_PHISHING_MODEL_NAME)[0]
    model = decode_model_data(model_64_str)

    force_model = demisto.args().get('forceModel', 'False') == 'True'
    urls = [x.strip() for x in demisto.args().get('urls', '').split(',') if x]
    if not urls:
        return_error(MSG_NO_URL_GIVEN)
    number_entries_to_return = int(demisto.args().get('numberEntryToReturn'))
    results = [get_prediction_single_url(model, x, force_model) for x in urls]

    return_general_summary(results)
    return_detailed_summary(results, number_entries_to_return)




if __name__ in ['__main__', '__builtin__', 'builtins']:
    main()
