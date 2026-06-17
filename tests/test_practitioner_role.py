#!/usr/bin/env python3
"""
Test script to verify PractitionerRole resource addition to transaction bundle
"""

import sys
import os

# Add the project root to Python path
sys.path.append('/Users/osb074/Development/tools/python/Patient-Referral')

# Import required modules
from bundler import create_request_bundle

def test_practitioner_role_bundle():
    """Test that PractitionerRole is added as resource, not just GET request"""
    
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
    
    print("Testing PractitionerRole inclusion in bundle...")
    print(f"Form data: {form_data}")
    
    try:
        # Create the bundle
        bundle = create_request_bundle(form_data)
        
        print(f"Bundle type: {type(bundle)}")
        print(f"Bundle keys: {bundle.keys() if isinstance(bundle, dict) else 'Not a dict'}")
        
        # Check bundle entries
        entries = bundle.get('entry', [])
        print(f"\nBundle has {len(entries)} entries:")
        
        # If no entries, let's see what's in the bundle
        if len(entries) == 0:
            print("Bundle content:")
            print(bundle)
            return
        
        practitioner_role_entries = []
        get_requests = []
        
        for i, entry in enumerate(entries):
            resource = entry.get('resource')
            request = entry.get('request', {})
            method = request.get('method', '')
            url = request.get('url', '')
            
            print(f"Entry {i+1}:")
            print(f"  Method: {method}")
            print(f"  URL: {url}")
            
            if resource:
                resource_type = resource.get('resourceType', 'Unknown')
                print(f"  Resource Type: {resource_type}")
                
                if resource_type == 'PractitionerRole':
                    practitioner_role_entries.append(entry)
            else:
                print(f"  No resource (request-only entry)")
                
            if 'PractitionerRole' in url and method == 'GET':
                get_requests.append(entry)
            
            print()
        
        # Summary
        print("="*50)
        print("SUMMARY:")
        print(f"PractitionerRole resources found: {len(practitioner_role_entries)}")
        print(f"PractitionerRole GET requests found: {len(get_requests)}")
        
        if practitioner_role_entries:
            print("\n✅ SUCCESS: PractitionerRole resource(s) included in bundle")
            for entry in practitioner_role_entries:
                resource = entry['resource']
                print(f"   - PractitionerRole ID: {resource.get('id', 'Unknown')}")
        else:
            print("\n❌ ISSUE: No PractitionerRole resources found")
            
        if get_requests:
            print(f"\n⚠️  WARNING: Still found {len(get_requests)} PractitionerRole GET request(s)")
        else:
            print("\n✅ GOOD: No PractitionerRole GET requests found")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_practitioner_role_bundle()
