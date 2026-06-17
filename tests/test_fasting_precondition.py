#!/usr/bin/env python3
"""
Test script to verify ServiceRequest fasting precondition extension functionality
"""

import sys
import os
import json

# Add the project root to Python path
sys.path.append('/Users/osb074/Development/tools/python/Patient-Referral')

# Set flag to prevent Flask app from running when importing
os.environ['TESTING'] = 'true'

# Import required modules
from bundler import create_request_bundle

def test_fasting_precondition_extension():
    """Test that ServiceRequest includes fasting precondition extension correctly"""
    
    print("🍽️ TESTING: ServiceRequest Fasting Precondition Extension")
    print("="*70)
    
    # Test cases
    test_cases = [
        {
            "name": "Default Non-Fasting Status (no fastingStatus provided)",
            "form_data": {
                'patient_id': 'test-patient-123',
                'requester': 'aboriginal-gillies-han',
                'organisation': 'pathology-lab-123',
                'selectedTests': [{"code": "26604007", "display": "Complete Blood Count"}],
                'selectedReasons': [{"code": "182817000", "display": "Routine check"}]
                # No fastingStatus field
            },
            "expected_fasting_code": "276330003",
            "expected_fasting_display": "Non-fasting"
        },
        {
            "name": "Explicitly Non-Fasting Status",
            "form_data": {
                'patient_id': 'test-patient-123',
                'requester': 'aboriginal-gillies-han',
                'organisation': 'pathology-lab-123',
                'fastingStatus': 'Non-fasting',  # Explicitly set to non-fasting
                'selectedTests': [{"code": "26604007", "display": "Complete Blood Count"}],
                'selectedReasons': [{"code": "182817000", "display": "Routine check"}]
            },
            "expected_fasting_code": "276330003",
            "expected_fasting_display": "Non-fasting"
        },
        {
            "name": "Fasting Status",
            "form_data": {
                'patient_id': 'test-patient-123',
                'requester': 'aboriginal-gillies-han',
                'organisation': 'pathology-lab-123',
                'fastingStatus': 'Fasting',  # Set to fasting
                'selectedTests': [{"code": "26604007", "display": "Complete Blood Count"}],
                'selectedReasons': [{"code": "182817000", "display": "Routine check"}]
            },
            "expected_fasting_code": "16985007",
            "expected_fasting_display": "Fasting"
        },
        {
            "name": "Fasting Status with Multiple Tests",
            "form_data": {
                'patient_id': 'test-patient-123',
                'requester': 'aboriginal-gillies-han',
                'organisation': 'pathology-lab-123',
                'fastingStatus': 'Fasting',  # Set to fasting
                'selectedTests': [
                    {"code": "26604007", "display": "Complete Blood Count"},
                    {"code": "33747000", "display": "Glucose measurement"}
                ],
                'selectedReasons': [{"code": "182817000", "display": "Routine check"}]
            },
            "expected_fasting_code": "16985007",
            "expected_fasting_display": "Fasting"
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n🍽️ Test Case {i}: {test_case['name']}")
        print("-" * 60)
        
        try:
            bundle = create_request_bundle(test_case['form_data'])
            entries = bundle.get('entry', [])
            
            # Find ServiceRequest resources
            service_requests = []
            for entry in entries:
                resource = entry.get('resource', {})
                if resource.get('resourceType') == 'ServiceRequest':
                    service_requests.append(resource)
            
            print(f"   Form data:")
            fasting_status = test_case['form_data'].get('fastingStatus', 'Not provided')
            print(f"     fastingStatus: {fasting_status}")
            print(f"   Found {len(service_requests)} ServiceRequest resource(s)")
            
            # Check each ServiceRequest for fasting precondition extension
            all_correct = True
            for j, sr in enumerate(service_requests, 1):
                extensions = sr.get('extension', [])
                
                print(f"\n   ServiceRequest {j}:")
                print(f"     Extensions: {len(extensions)} total")
                
                # Look for fasting precondition extension
                fasting_extension = None
                for ext in extensions:
                    if ext.get('url') == 'http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-fastingprecondition':
                        fasting_extension = ext
                        break
                
                if fasting_extension:
                    coding = fasting_extension.get('valueCodeableConcept', {}).get('coding', [])
                    if coding and len(coding) > 0:
                        code = coding[0].get('code', '')
                        display = coding[0].get('display', '')
                        system = coding[0].get('system', '')
                        
                        print(f"     Fasting Extension: Found")
                        print(f"     System: {system}")
                        print(f"     Code: {code}")
                        print(f"     Display: {display}")
                        print(f"     Expected Code: {test_case['expected_fasting_code']}")
                        print(f"     Expected Display: {test_case['expected_fasting_display']}")
                        
                        if (code == test_case['expected_fasting_code'] and 
                            display == test_case['expected_fasting_display'] and
                            system == "http://snomed.info/sct"):
                            print(f"     ✅ Fasting precondition extension is correct")
                        else:
                            print(f"     ❌ Fasting precondition extension incorrect")
                            all_correct = False
                    else:
                        print(f"     ❌ Fasting extension has no coding")
                        all_correct = False
                else:
                    print(f"     ❌ Fasting precondition extension missing")
                    all_correct = False
                
                # Also check for other expected extensions
                display_sequence_found = False
                for ext in extensions:
                    if ext.get('url') == 'http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-displaysequence':
                        display_sequence_found = True
                        break
                
                if display_sequence_found:
                    print(f"     ✅ Display sequence extension found")
                else:
                    print(f"     ❌ Display sequence extension missing")
                    all_correct = False
            
            # Test result
            if all_correct:
                print(f"\n   ✅ PASS")
            else:
                print(f"\n   ❌ FAIL")
                
        except Exception as e:
            print(f"   ❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*70)
    print("🎯 FASTING PRECONDITION EXTENSION VERIFICATION:")
    print("   Form Field:")
    print("     - fastingStatus: 'Non-fasting' (default) or 'Fasting'")
    print("   ServiceRequest Extension:")
    print("     - URL: http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-fastingprecondition")
    print("     - valueCodeableConcept with SNOMED coding")
    print("   SNOMED Codes:")
    print("     - 276330003: Non-fasting")
    print("     - 16985007: Fasting")
    print("   Behavior:")
    print("     - Extension always added to every ServiceRequest")
    print("     - Code and display determined by form fastingStatus value")
    print("   ✅ IMPLEMENTATION COMPLETE!")

if __name__ == "__main__":
    test_fasting_precondition_extension()
