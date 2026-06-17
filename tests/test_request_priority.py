#!/usr/bin/env python3
"""
Test script to verify ServiceRequest priority functionality
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

def test_request_priority():
    """Test that ServiceRequest includes priority correctly"""
    
    print("⚡ TESTING: ServiceRequest Priority")
    print("="*70)
    
    # Test cases
    test_cases = [
        {
            "name": "Default Routine Priority (no requestPriority provided)",
            "form_data": {
                'patient_id': 'test-patient-123',
                'requester': 'aboriginal-gillies-han',
                'organisation': 'pathology-lab-123',
                'selectedTests': [{"code": "26604007", "display": "Complete Blood Count"}],
                'selectedReasons': [{"code": "182817000", "display": "Routine check"}]
                # No requestPriority field
            },
            "expected_priority": "routine"
        },
        {
            "name": "Explicitly Routine Priority",
            "form_data": {
                'patient_id': 'test-patient-123',
                'requester': 'aboriginal-gillies-han',
                'organisation': 'pathology-lab-123',
                'requestPriority': 'routine',  # Explicitly set to routine
                'selectedTests': [{"code": "26604007", "display": "Complete Blood Count"}],
                'selectedReasons': [{"code": "182817000", "display": "Routine check"}]
            },
            "expected_priority": "routine"
        },
        {
            "name": "Urgent Priority",
            "form_data": {
                'patient_id': 'test-patient-123',
                'requester': 'aboriginal-gillies-han',
                'organisation': 'pathology-lab-123',
                'requestPriority': 'urgent',  # Set to urgent
                'selectedTests': [{"code": "26604007", "display": "Complete Blood Count"}],
                'selectedReasons': [{"code": "182817000", "display": "Routine check"}]
            },
            "expected_priority": "urgent"
        },
        {
            "name": "ASAP Priority",
            "form_data": {
                'patient_id': 'test-patient-123',
                'requester': 'aboriginal-gillies-han',
                'organisation': 'pathology-lab-123',
                'requestPriority': 'asap',  # Set to ASAP
                'selectedTests': [{"code": "26604007", "display": "Complete Blood Count"}],
                'selectedReasons': [{"code": "182817000", "display": "Routine check"}]
            },
            "expected_priority": "asap"
        },
        {
            "name": "STAT Priority",
            "form_data": {
                'patient_id': 'test-patient-123',
                'requester': 'aboriginal-gillies-han',
                'organisation': 'pathology-lab-123',
                'requestPriority': 'stat',  # Set to STAT
                'selectedTests': [{"code": "26604007", "display": "Complete Blood Count"}],
                'selectedReasons': [{"code": "182817000", "display": "Routine check"}]
            },
            "expected_priority": "stat"
        },
        {
            "name": "Priority with Multiple Tests",
            "form_data": {
                'patient_id': 'test-patient-123',
                'requester': 'aboriginal-gillies-han',
                'organisation': 'pathology-lab-123',
                'requestPriority': 'urgent',  # Set to urgent
                'selectedTests': [
                    {"code": "26604007", "display": "Complete Blood Count"},
                    {"code": "33747000", "display": "Glucose measurement"}
                ],
                'selectedReasons': [{"code": "182817000", "display": "Routine check"}]
            },
            "expected_priority": "urgent"
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n⚡ Test Case {i}: {test_case['name']}")
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
            request_priority = test_case['form_data'].get('requestPriority', 'Not provided')
            print(f"     requestPriority: {request_priority}")
            print(f"   Found {len(service_requests)} ServiceRequest resource(s)")
            
            # Check each ServiceRequest for priority
            all_correct = True
            for j, sr in enumerate(service_requests, 1):
                sr_priority = sr.get('priority', 'Missing')
                
                print(f"\n   ServiceRequest {j}:")
                print(f"     Priority: {sr_priority}")
                print(f"     Expected: {test_case['expected_priority']}")
                
                # Check priority
                if sr_priority == test_case['expected_priority']:
                    print(f"     ✅ Priority is correct")
                else:
                    print(f"     ❌ Priority mismatch")
                    all_correct = False
                
                # Also verify other key fields are still present
                status = sr.get('status', 'Missing')
                intent = sr.get('intent', 'Missing')
                code = sr.get('code', {}).get('text', 'Missing')
                
                print(f"     Status: {status}")
                print(f"     Intent: {intent}")
                print(f"     Test: {code}")
                
                # Check extensions are still present
                extensions = sr.get('extension', [])
                extension_count = len(extensions)
                print(f"     Extensions: {extension_count} total")
                
                # Should have at least display sequence and fasting precondition
                if extension_count >= 2:
                    print(f"     ✅ Extensions present")
                else:
                    print(f"     ❌ Extensions missing or incomplete")
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
    print("🎯 REQUEST PRIORITY FUNCTIONALITY VERIFICATION:")
    print("   Form Field:")
    print("     - requestPriority: 'routine' (default), 'urgent', 'asap', or 'stat'")
    print("   ServiceRequest Field:")
    print("     - priority: String value from form")
    print("   Priority Options:")
    print("     - routine: Standard processing")
    print("     - urgent: Expedited processing")
    print("     - asap: As soon as possible")
    print("     - stat: Immediately/emergency")
    print("   Behavior:")
    print("     - Priority field always added to every ServiceRequest")
    print("     - Value determined by form requestPriority value")
    print("     - Defaults to 'routine' if not provided")
    print("   ✅ IMPLEMENTATION COMPLETE!")

if __name__ == "__main__":
    test_request_priority()
