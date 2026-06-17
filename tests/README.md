# Patient Referrals Test Suite

This folder contains all test files and debugging utilities for the Patient Referrals application.

## File Organization

### Test Files (`test_*.py`)
Comprehensive test suites for various features and components:
- **test_all_features.py** - Integration tests covering multiple features
- **test_auth_functionality.py** - Authentication and authorization tests
- **test_billing_category.py** - Billing category functionality tests
- **test_bundle_comparison.py** - FHIR bundle comparison tests
- **test_bundler_coding.py** - ServiceRequest code building tests
- **test_checkbox_functionality.py** - Form checkbox interaction tests
- **test_comprehensive_bundle.py** - Full bundle creation tests
- **test_coverage_*.py** - Coverage and insurance-related tests
- **test_dashboard_implementation.py** - Dashboard feature tests
- **test_dropdown_*.py** - Dropdown selection and interaction tests
- **test_full_bundler.py** - Complete bundler workflow tests
- **test_group_tasks.py** - Task grouping functionality tests
- **test_practitioner_role.py** - Practitioner role data handling tests
- **test_request_*.py** - Service request-related tests
- **test_specimen_*.py** - Specimen collection tests
- **test_stats_implementation.py** - Statistics calculation tests
- **test_valueset.py** - FHIR ValueSet handling tests
- **test_workflow_integration.py** - End-to-end workflow tests

### Debug Files (`debug_*.py`)
Utility scripts for debugging and testing:
- **debug_dropdown_critical.py** - Dropdown selection issue debugging
- **debug_fhir_response.py** - FHIR server response analysis
- **debug_stats.py** - Statistics calculation debugging
- **debug_test_dropdown.py** - Test dropdown data validation
- **debug_undefined_display.py** - Display attribute debugging

### Utility Scripts
- **final_verification.py** - Final verification of implemented features
- **find_practitioner_roles.py** - FHIR practitioner role lookup utility
- **show_coverage_example.py** - Coverage data example
- **update_fhir_calls.py** - FHIR API call update utility

## Running Tests

To run all tests:
```bash
python -m pytest tests/
```

To run a specific test file:
```bash
python -m pytest tests/test_all_features.py
```

To run tests with verbose output:
```bash
python -m pytest tests/ -v
```

## Test Dependencies

Tests require the following packages (included in requirements.txt):
- pytest
- requests
- fhirclient

## Notes

- Tests use Python's unittest framework and pytest
- Some tests interact with external FHIR servers and may require network connectivity
- Debug utilities are useful for diagnosing specific issues during development
