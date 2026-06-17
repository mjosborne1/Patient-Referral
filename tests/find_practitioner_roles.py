#!/usr/bin/env python3
"""
Test script to find a valid PractitionerRole ID for testing
"""

import sys
import os

# Add the project root to Python path
sys.path.append('/Users/osb074/Development/tools/python/Patient-Referral')

# Import required modules
from fhirutils import fhir_get

def find_practitioner_roles():
    """Find valid PractitionerRole IDs from the server"""
    
    server_url = os.environ.get('FHIR_SERVER_URL', 'https://aucore.aidbox.beda.software/fhir')
    
    print(f"Checking PractitionerRoles on server: {server_url}")
    
    try:
        # Get a list of PractitionerRoles
        response = fhir_get("/PractitionerRole?_count=5", fhir_server_url=server_url, timeout=10)
        print(f"Response status: {response.status_code}")
        
        if response.status_code == 200:
            bundle = response.json()
            entries = bundle.get('entry', [])
            print(f"Found {len(entries)} PractitionerRole entries:")
            
            for i, entry in enumerate(entries):
                resource = entry.get('resource', {})
                if resource.get('resourceType') == 'PractitionerRole':
                    role_id = resource.get('id', 'Unknown')
                    print(f"  {i+1}. PractitionerRole ID: {role_id}")
                    
                    # Show some details
                    practitioner_ref = resource.get('practitioner', {}).get('reference', '')
                    organization_ref = resource.get('organization', {}).get('reference', '')
                    specialties = resource.get('specialty', [])
                    
                    print(f"     Practitioner: {practitioner_ref}")
                    print(f"     Organization: {organization_ref}")
                    if specialties:
                        for specialty in specialties:
                            for coding in specialty.get('coding', []):
                                if coding.get('display'):
                                    print(f"     Specialty: {coding['display']}")
                                    break
                    print()
            
            if entries:
                first_role_id = entries[0]['resource']['id']
                print(f"Use this PractitionerRole ID for testing: {first_role_id}")
                return first_role_id
        else:
            print(f"Failed to get PractitionerRoles: {response.status_code}")
            if hasattr(response, 'text'):
                print(f"Response: {response.text[:500]}")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        
    return None

if __name__ == "__main__":
    find_practitioner_roles()
