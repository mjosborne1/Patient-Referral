"""
Graph Builder Module

Constructs a directed graph from FHIR resources showing relationships between them.
Adapted from fhir-bundle-viz for use in Patient Referrals.
"""

from typing import Dict, List, Any, Set, Tuple, Optional
from fhir_parser import get_resource_type_display, get_resource_id, is_task_group, get_task_group_label


class Graph:
    """Represents a directed graph of FHIR resources."""
    
    def __init__(self):
        self.nodes: Dict[str, str] = {}  # node_id -> display_label
        self.edges: List[Tuple[str, str, str]] = []  # (source_id, target_id, edge_label)
        self.external_refs: Set[str] = set()  # Set of node IDs that are external references
        self.group_tasks: Set[str] = set()  # Set of node IDs that are group Tasks
        self.node_profiles: Dict[str, List[str]] = {}  # node_id -> list of profile URLs
    
    def add_node(self, node_id: str, label: str, is_external: bool = False, is_group_task: bool = False, profiles: Optional[List[str]] = None):
        """Add a node to the graph."""
        self.nodes[node_id] = label
        if profiles:
            self.node_profiles[node_id] = profiles
        if is_external:
            self.external_refs.add(node_id)
        if is_group_task:
            self.group_tasks.add(node_id)
    
    def add_edge(self, source_id: str, target_id: str, label: str):
        """Add a directed edge from source to target."""
        self.edges.append((source_id, target_id, label))


def build_graph(resources: Dict[str, Dict[str, Any]]) -> Graph:
    """
    Build a directed graph from FHIR resources.
    
    Direction: Target → Source (ownership model)
    E.g., Patient → Observation (patient owns observation)
    """
    graph = Graph()
    
    # First pass: Add all nodes for resources in the bundle
    for resource_id, resource_data in resources.items():
        resource = resource_data['resource']
        profiles = _extract_profiles(resource)
        if is_task_group(resource):
            label = get_task_group_label(resource)
            graph.add_node(resource_id, label, is_external=False, is_group_task=True, profiles=profiles)
        else:
            label = get_resource_type_display(resource)
            graph.add_node(resource_id, label, is_external=False, profiles=profiles)
    
    # Second pass: Extract references and create edges
    for resource_id, resource_data in resources.items():
        resource = resource_data['resource']
        references = extract_references(resource)
        
        for ref_type, ref_ids in references.items():
            for target_id in ref_ids:
                resolved_id = resolve_reference(target_id, resources)
                
                if resolved_id and resolved_id in resources:
                    # Referenced resource exists in bundle
                    graph.add_edge(resolved_id, resource_id, ref_type)
                elif target_id:
                    # Referenced resource is external
                    external_node_id = _create_external_ref_id(target_id)
                    if external_node_id not in graph.nodes:
                        external_label = _create_external_ref_label(target_id)
                        graph.add_node(external_node_id, external_label, is_external=True)
                    
                    graph.add_edge(external_node_id, resource_id, ref_type)
    
    return graph


def extract_references(resource: Dict[str, Any]) -> Dict[str, List[str]]:
    """Extract all references from a FHIR resource."""
    references = {}
    
    # Common reference fields
    ref_fields = [
        'subject', 'encounter', 'specimen', 'performer', 'requester',
        'recorder', 'asserter', 'participant', 'location',
        'serviceProvider', 'managingOrganization', 'organization',
        'basedOn', 'partOf', 'focus', 'context', 'author',
    ]
    
    for field in ref_fields:
        value = resource.get(field)
        if value:
            refs = _extract_reference_value(value, field)
            if refs:
                references[field] = refs
    
    # Array reference fields
    array_ref_fields = [
        'result', 'hasMember', 'derivedFrom', 'reasonReference',
        'insurance', 'careTeam', 'supportingInfo',
    ]
    
    for field in array_ref_fields:
        value = resource.get(field)
        if value and isinstance(value, list):
            all_refs = []
            for item in value:
                refs = _extract_reference_value(item, field)
                if refs:
                    all_refs.extend(refs)
            if all_refs:
                references[field] = all_refs
    
    return references


def _extract_reference_value(value: Any, field_name: str) -> List[str]:
    """Extract reference ID(s) from a value."""
    if not value:
        return []
    
    if isinstance(value, dict) and 'reference' in value:
        ref = value['reference']
        return [ref] if ref else []
    
    if isinstance(value, list):
        refs = []
        for item in value:
            if isinstance(item, dict) and 'reference' in item:
                ref = item['reference']
                if ref:
                    refs.append(ref)
        return refs
    
    return []


def resolve_reference(reference: str, resources: Dict[str, Dict[str, Any]]) -> str:
    """Resolve a FHIR reference to a resource ID."""
    if not reference:
        return ""
    
    # Handle urn:uuid: format
    if reference.startswith('urn:uuid:') or reference.startswith('Observation/urn:uuid:') or reference.startswith('DocumentReference/urn:uuid:') or reference.startswith('ServiceRequest/urn:uuid:') or reference.startswith('Coverage/urn:uuid:') or reference.startswith('Specimen/urn:uuid:') or reference.startswith('Task/urn:uuid:') or reference.startswith('Encounter/urn:uuid:'):
        # Extract UUID from various formats
        uuid_part = reference.split('urn:uuid:')[-1]
        return uuid_part
    
    # Handle relative references like "Patient/12345"
    if '/' in reference:
        parts = reference.split('/')
        if len(parts) >= 2:
            resource_id = parts[-1]
            
            if resource_id in resources:
                return resource_id
            
            for res_id, res_data in resources.items():
                full_url = res_data.get('fullUrl', '')
                if full_url.endswith(reference) or full_url.endswith(resource_id):
                    return res_id
    
    # Handle contained resources (skip for now)
    if reference.startswith('#'):
        return ""
    
    if reference in resources:
        return reference
    
    return ""


def _create_external_ref_id(reference: str) -> str:
    """Create a unique ID for an external reference."""
    safe_ref = reference.replace('/', '-').replace(':', '-').replace('#', '-')
    return f"ext-{safe_ref}"


def _create_external_ref_label(reference: str) -> str:
    """Create a display label for an external reference."""
    if '/' in reference:
        parts = reference.split('/')
        if len(parts) >= 2:
            resource_type = parts[-2] if len(parts) > 2 else parts[0]
            resource_id = parts[-1]
            return f"{resource_type}: {resource_id} (external)"
    
    return f"{reference} (external)"


def _extract_profiles(resource: Dict[str, Any]) -> List[str]:
    """Extract profile URLs from meta.profile array."""
    meta = resource.get('meta', {})
    profiles = meta.get('profile', [])
    return profiles if isinstance(profiles, list) else []


def get_graph_stats(graph: Graph) -> Dict[str, int]:
    """Get statistics about the graph."""
    return {
        'nodes': len(graph.nodes),
        'edges': len(graph.edges),
        'external_refs': len(graph.external_refs),
    }
