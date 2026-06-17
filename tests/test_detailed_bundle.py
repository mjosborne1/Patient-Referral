#!/usr/bin/env python3
"""
Test script to verify both PractitionerRole and Practitioner resources are included
"""

import sys
import os

# Add the project root to Python path
sys.path.append('/Users/osb074/Development/tools/python/Patient-Referral')

# Import required modules
from bundler import create_request_bundle

def test_practitioner_and_role():
    """Test that both PractitionerRole and Practitioner are included"""
    
    # Sample form data with valid requester ID
    form_data = {
        'patient_id': 'test-patient-123',
        'requester': 'aboriginal-gillies-han',  # Valid PractitionerRole ID
        'selectedTests': [{"code": "26604007", "display": "Complete Blood Count"}],
        'selectedReasons': [{"code": "182817000", "display": "Routine check"}],
        'collect_specimen': True,
        'specimen_type': 'Blood',
        'collection_method': 'Venipuncture',
        'body_site': 'Arm'
    }
    
    print("Testing PractitionerRole AND Practitioner inclusion...")
    
    try:
        # Create the bundle
        bundle = create_request_bundle(form_data)
        
        # Check bundle entries
        entries = bundle.get('entry', [])
        print(f"Bundle has {len(entries)} entries:")
        
        practitioner_role_entries = []
        practitioner_entries = []
        
        for i, entry in enumerate(entries):
            resource = entry.get('resource')
            request = entry.get('request', {})
            method = request.get('method', '')
            url = request.get('url', '')
            
            if resource:
                resource_type = resource.get('resourceType', 'Unknown')
                resource_id = resource.get('id', 'Unknown')
                
                print(f"Entry {i+1}: {method} {url} -> {resource_type} (ID: {resource_id})")
                
                if resource_type == 'PractitionerRole':
                    practitioner_role_entries.append(entry)
                    # Show practitioner reference
                    practitioner_ref = resource.get('practitioner', {}).get('reference', '')
                    print(f"   └─ Practitioner reference: {practitioner_ref}")
                elif resource_type == 'Practitioner':
                    practitioner_entries.append(entry)
                    # Show practitioner name
                    name = resource.get('name', [{}])[0]
                    given_names = ' '.join(name.get('given', []))
                    family_name = name.get('family', '')
                    full_name = f"{given_names} {family_name}".strip()
                    print(f"   └─ Practitioner name: {full_name}")
            else:
                print(f"Entry {i+1}: {method} {url} -> (request only)")
        
        # Summary
        print("\n" + "="*60)
        print("INCLUSION SUMMARY:")
        print(f"✅ PractitionerRole resources: {len(practitioner_role_entries)}")
        print(f"✅ Practitioner resources: {len(practitioner_entries)}")
        
        if practitioner_role_entries and practitioner_entries:
            print("\n🎉 PERFECT: Both PractitionerRole and Practitioner resources are included!")
        elif practitioner_role_entries:
            print("\n✅ PractitionerRole included, but Practitioner might not be available")
        else:
            print("\n❌ Neither PractitionerRole nor Practitioner included")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_practitioner_and_role()
