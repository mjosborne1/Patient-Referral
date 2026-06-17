#!/usr/bin/env python3
"""Debug stats implementation"""
import sys
import os
import requests
from dotenv import load_dotenv

# Add the project directory to Python path
sys.path.insert(0, '/Users/osb074/Development/tools/python/Patient-Referral')

def get_server_info():
    load_dotenv()
    server_url = os.getenv('FHIR_SERVER', 'https://smile.sparked-fhir.com/ereq/fhir/DEFAULT')
    username = os.getenv('FHIR_USERNAME', 'placer')
    password = os.getenv('FHIR_PASSWORD', '')
    return server_url, (username, password)

try:
    print("=== Testing Stats Data Processing ===")
    server_url, auth = get_server_info()
    print(f"Using server: {server_url}")
    
    # Test ServiceRequests
    print("\n--- Testing ServiceRequests ---")
    sr_response = requests.get(f"{server_url}/ServiceRequest?_count=5", auth=auth, timeout=10)
    
    if sr_response.status_code == 200:
        sr_data = sr_response.json()
        service_requests = sr_data.get('entry', [])
        print(f"Found {len(service_requests)} ServiceRequests")
        
        for i, entry in enumerate(service_requests[:3], 1):
            resource = entry.get('resource', {})
            status = resource.get('status', 'unknown')
            
            # Get code info
            code = resource.get('code', {})
            code_text = code.get('text', 'No description')
            if not code_text or code_text == 'No description':
                if code.get('coding'):
                    code_text = code['coding'][0].get('display', 'No description')
            
            # Get category info
            category = resource.get('category', [])
            category_text = 'No category'
            if category and len(category) > 0:
                cat = category[0]
                category_text = cat.get('text', '')
                if not category_text and cat.get('coding'):
                    category_text = cat['coding'][0].get('display', 'No category')
            
            print(f"  SR {i}: status='{status}', code='{code_text}', category='{category_text}'")
    else:
        print(f"ServiceRequest query failed: {sr_response.status_code}")
    
    # Test Observations  
    print("\n--- Testing Observations ---")
    obs_response = requests.get(f"{server_url}/Observation?_count=5", auth=auth, timeout=10)
    
    if obs_response.status_code == 200:
        obs_data = obs_response.json()
        observations = obs_data.get('entry', [])
        print(f"Found {len(observations)} Observations")
        
        for i, entry in enumerate(observations[:3], 1):
            resource = entry.get('resource', {})
            status = resource.get('status', 'unknown')
            
            # Get code info
            code = resource.get('code', {})
            code_text = code.get('text', 'No description')
            if not code_text or code_text == 'No description':
                if code.get('coding'):
                    code_text = code['coding'][0].get('display', 'No description')
            
            # Get category info
            category = resource.get('category', [])
            category_text = 'No category'
            if category and len(category) > 0:
                cat = category[0]
                category_text = cat.get('text', '')
                if not category_text and cat.get('coding'):
                    category_text = cat['coding'][0].get('display', 'No category')
            
            print(f"  Obs {i}: status='{status}', code='{code_text}', category='{category_text}'")
    else:
        print(f"Observation query failed: {obs_response.status_code}")
        
    print("\n=== Debug Complete ===")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
