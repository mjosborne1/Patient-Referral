#!/usr/bin/env python3
"""
Debug script to see the actual FHIR response for PractitionerRole with _include
"""

import sys
import os
import json

# Add the project root to Python path
sys.path.append('/Users/osb074/Development/tools/python/Patient-Referral')

# Import required modules
from fhirutils import fhir_get

def debug_practitioner_role_response():
    """Debug the actual FHIR response to understand the structure"""
    
    server_url = os.environ.get('FHIR_SERVER_URL', 'https://aucore.aidbox.beda.software/fhir')
    requester_id = 'aboriginal-gillies-han'
    
    print(f"Fetching PractitionerRole with _include from: {server_url}")
    print(f"URL: /PractitionerRole/{requester_id}?_include=PractitionerRole:practitioner")
    
    try:
        response = fhir_get(f"/PractitionerRole/{requester_id}?_include=PractitionerRole:practitioner", 
                          fhir_server_url=server_url, timeout=10)
        
        print(f"Response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Response type: {type(data)}")
            print(f"Resource type: {data.get('resourceType', 'Unknown')}")
            
            if data.get('resourceType') == 'PractitionerRole':
                print("\n📋 SINGLE RESOURCE RESPONSE:")
                print(f"PractitionerRole ID: {data.get('id')}")
                practitioner_ref = data.get('practitioner', {}).get('reference', '')
                print(f"Practitioner reference: {practitioner_ref}")
                
                print("\n⚠️  NOTE: _include didn't return a Bundle - the server might not support _include on single resource requests")
                
            elif data.get('resourceType') == 'Bundle':
                print("\n📦 BUNDLE RESPONSE:")
                entries = data.get('entry', [])
                print(f"Bundle has {len(entries)} entries:")
                
                for i, entry in enumerate(entries):
                    resource = entry.get('resource', {})
                    resource_type = resource.get('resourceType', 'Unknown')
                    resource_id = resource.get('id', 'Unknown')
                    print(f"  {i+1}. {resource_type} (ID: {resource_id})")
                    
                    if resource_type == 'PractitionerRole':
                        practitioner_ref = resource.get('practitioner', {}).get('reference', '')
                        print(f"     └─ Practitioner reference: {practitioner_ref}")
                    elif resource_type == 'Practitioner':
                        name = resource.get('name', [{}])[0]
                        given_names = ' '.join(name.get('given', []))
                        family_name = name.get('family', '')
                        full_name = f"{given_names} {family_name}".strip()
                        print(f"     └─ Name: {full_name}")
            
            # Show the raw response for debugging
            print(f"\n📄 RAW RESPONSE (first 1000 chars):")
            print(json.dumps(data, indent=2)[:1000])
            
        else:
            print(f"Failed request. Response: {response.text[:500]}")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_practitioner_role_response()
