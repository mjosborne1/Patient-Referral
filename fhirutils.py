import os
import requests
import urllib3
from datetime import datetime
from dotenv import load_dotenv
from typing import Optional, Tuple, Union

# Internal sentinel: distinguishes "caller didn't pass auth" (use env fallback)
# from "caller explicitly passed None" (force unauthenticated request).
_UNSET = object()

def fhir_get(path, fhir_server_url=None, auth_credentials=_UNSET, bearer_token=None, **kwargs):
    """
    Wrapper for requests.get that includes FHIR server auth.
    path: the endpoint path, e.g. '/Patient?_count=10'
    fhir_server_url: full base URL, e.g. 'https://smile.sparked-fhir.com/aucore/fhir/DEFAULT'
    auth_credentials:
      - omitted / _UNSET  → fall back to FHIR_USERNAME/FHIR_PASSWORD env vars
      - tuple (user, pass) → use these credentials
      - None              → explicitly unauthenticated, skip env-var fallback
    bearer_token: if provided, use Bearer token auth instead of Basic auth
    """
    # Read at call time so load_dotenv() in app.py has already run.
    # Set FHIR_VERIFY_SSL=false in .env for servers with untrusted certificates.
    verify_ssl = os.environ.get('FHIR_VERIFY_SSL', 'true').lower() not in ('false', '0', 'no')
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    base_url = fhir_server_url or os.environ.get('FHIR_SERVER_URL')
    url = ''
    if base_url:
        url = base_url.rstrip('/') + '/' + path.lstrip('/')

    # Bearer token takes priority over Basic auth
    if bearer_token:
        headers = kwargs.pop('headers', {})
        headers['Authorization'] = f'Bearer {bearer_token}'
        print(f'Attempting get {url} using Bearer token')
        return requests.get(url, headers=headers, verify=verify_ssl, **kwargs)

    if auth_credentials is _UNSET:
        # Caller didn't specify — fall back to environment
        env_user = os.environ.get('FHIR_USERNAME')
        env_pass = os.environ.get('FHIR_PASSWORD')
        auth: Optional[Tuple[str, str]] = (env_user, env_pass) if env_user and env_pass else None
    else:
        # None → unauthenticated; tuple → use it
        auth = auth_credentials  # type: ignore[assignment]

    if auth:
        print(f'Attempting get {url} using auth {auth[0]}:*****')  # Hide password in logs
        return requests.get(url, auth=auth, verify=verify_ssl, **kwargs)
    else:
        print(f'Attempting get {url} with no auth')
        return requests.get(url, verify=verify_ssl, **kwargs)

def format_fhir_date(date_str, fmt="D"):
    """
    Takes a FHIR date or datetime string and returns a formatted date.
    - fmt="D": returns 'YYYY-MM-DD'
    - fmt="DT": returns 'YYYY-MM-DD HH:MM'
    Handles both 'YYYY-MM-DD' and 'YYYY-MM-DDTHH:MM:SS' formats.
    Returns the original string if parsing fails or input is empty.
    """
    if not date_str:
        return ''
    try:
        if 'T' in date_str:
            dt = datetime.strptime(date_str[:19], '%Y-%m-%dT%H:%M:%S')
            if fmt == "DT":
                return dt.strftime('%Y-%m-%d %H:%M')
            else:
                return dt.strftime('%Y-%m-%d')
        else:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            return dt.strftime('%Y-%m-%d')
    except ValueError:
        return date_str
    
def get_text_display(codeable_concept, default="Unknown"):
    """
    Returns the best display string for a FHIR CodeableConcept.
    - Prefers the first coding.display, then text, else default.
    """
    if not codeable_concept:
        return default
    # Try coding.display
    codings = codeable_concept.get('coding', [])
    for coding in codings:
        if coding.get('display'):
            return coding['display']
    # Try text
    if codeable_concept.get('text'):
        return codeable_concept['text']
    return default

def find_category(categories, system, code):
    """
    Returns True if any coding in any category matches the given system and code.
    categories: list of category dicts (each with 'coding' list)
    system: string, e.g. "http://terminology.hl7.org/CodeSystem/observation-category"
    code: string, e.g. "laboratory"
    """
    if not categories:
        return False
    for cat in categories:
        for coding in cat.get('coding', []):
            if coding.get('system') == system and coding.get('code') == code:
                return True
    return False


def get_form_data(request):
    """
    Utility function to process and log form data from a Flask request.
    Handles both single and multi-valued form fields.
    
    Args:
        request: The Flask request object
        
    Returns:
        dict: Processed form data with single values unwrapped
    """
    form_data = {}
    for key in request.form:
        values = request.form.getlist(key)
        form_data[key] = values if len(values) > 1 else values[0]
    
    return form_data