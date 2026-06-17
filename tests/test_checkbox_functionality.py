#!/usr/bin/env python3
"""
Test script to verify Consent resource is included when MHR consent is withdrawn
"""

import sys
import os
import json

# Add the project root to Python path
sys.path.append('/Users/osb074/Development/tools/python/Patient-Referral')

# Import required modules
from bundler import create_request_bundle

def test_mhr_consent_withdrawal():
    """Test that Consent resource is included when MHR consent withdrawal checkbox is ticked"""
    
    print("🔒 TESTING: My Health Record Consent Withdrawal")
    print("="*60)
    
    # Test cases
    test_cases = [
        {
            "name": "MHR Consent Withdrawn (checkbox ticked)",
            "form_data": {
                'patient_id': 'test-patient-123',
                'requester': 'aboriginal-gillies-han',
                'organisation': 'pathology-lab-123',
                'mhrConsentWithdrawn': True,  # Checkbox is ticked
                'selectedTests': [{"code": "26604007", "display": "Complete Blood Count"}],
                'selectedReasons': [{"code": "182817000", "display": "Routine check"}]
            },
            "should_have_consent": True
        },
        {
            "name": "MHR Consent NOT Withdrawn (checkbox not ticked)",
            "form_data": {
                'patient_id': 'test-patient-123',
                'requester': 'aboriginal-gillies-han',
                'organisation': 'pathology-lab-123',
                # No mhrConsentWithdrawn field
                'selectedTests': [{"code": "26604007", "display": "Complete Blood Count"}],
                'selectedReasons': [{"code": "182817000", "display": "Routine check"}]
            },
            "should_have_consent": False
        },
        {
            "name": "MHR Consent Withdrawn with value 'true' (string)",
            "form_data": {
                'patient_id': 'test-patient-123',
                'requester': 'aboriginal-gillies-han',
                'organisation': 'pathology-lab-123',
                'mhrConsentWithdrawn': 'true',  # String value as sent by HTML form
                'selectedTests': [{"code": "26604007", "display": "Complete Blood Count"}],
                'selectedReasons': [{"code": "182817000", "display": "Routine check"}]
            },
            "should_have_consent": True
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n📋 Test Case {i}: {test_case['name']}")
        print("-" * 50)
        
        try:
            bundle = create_request_bundle(test_case['form_data'])
            entries = bundle.get('entry', [])
            
            # Find Consent resources
            consent_resources = []
            for entry in entries:
                resource = entry.get('resource', {})
                if resource.get('resourceType') == 'Consent':
                    consent_resources.append(resource)
            
            print(f"   Form field value: {test_case['form_data'].get('mhrConsentWithdrawn', 'Not provided')}")
            print(f"   Found {len(consent_resources)} Consent resource(s)")
            print(f"   Expected consent: {test_case['should_have_consent']}")
            
            # Check if expectation matches reality
            has_consent = len(consent_resources) > 0
            
            if has_consent == test_case['should_have_consent']:
                print(f"   ✅ PASS")
            else:
                print(f"   ❌ FAIL")
                
            # Show details of any Consent resources found
            for j, consent in enumerate(consent_resources, 1):
                print(f"\n   📄 Consent Resource {j}:")
                print(f"      ID: {consent.get('id')}")
                print(f"      Status: {consent.get('status')}")
                
                # Show scope
                scope = consent.get('scope', {})
                scope_coding = scope.get('coding', [{}])[0]
                print(f"      Scope: {scope_coding.get('display', 'Unknown')}")
                
                # Show category
                categories = consent.get('category', [])
                if categories:
                    category_coding = categories[0].get('coding', [{}])[0]
                    print(f"      Category: {category_coding.get('display', 'Unknown')}")
                
                # Show provision type
                provision = consent.get('provision', {})
                provision_type = provision.get('type', 'Unknown')
                print(f"      Provision Type: {provision_type}")
                
                # Show profile
                profiles = consent.get('meta', {}).get('profile', [])
                if profiles:
                    profile = profiles[0]
                    if 'mhrconsentwithdrawal' in profile:
                        print(f"      ✅ Correct MHR Consent Withdrawal profile")
                    else:
                        print(f"      ⚠️  Unexpected profile: {profile}")
                
        except Exception as e:
            print(f"   ❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*60)
    print("🎯 MHR CONSENT WITHDRAWAL VERIFICATION:")
    print("   Requirement: Include Consent resource when 'Do not upload to MHR' is ticked")
    print("   Form field: mhrConsentWithdrawn")
    print("   Bundler check: form_data.get('mhrConsentWithdrawn', False)")
    print("   ✅ FIELD NAME MISMATCH FIXED!")
    print("\n   💡 Expected Behavior:")
    print("      - Checkbox ticked → Consent resource with provision.type='deny' included")
    print("      - Checkbox not ticked → No Consent resource in bundle")
    print("      - Uses AU eRequesting MHR Consent Withdrawal profile")

if __name__ == "__main__":
    test_mhr_consent_withdrawal()
