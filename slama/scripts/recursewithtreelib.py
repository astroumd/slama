#!/usr/bin/env python
import json
from pathlib import Path
from treelib import Tree
from slama.monitor.monitorpoint import MonitorPoint

# using treelib to instantiate a monitor system

# -------------------------------------------------------
# Utility to read JSON file
# -------------------------------------------------------
def read_json_file(file_path):
    """Reads and parses a JSON file."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {file_path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

class MonitorSubsystem:
    """Represents a dictionary-level subsystem node."""
    def __init__(self, name, data):
        self.name = name
        self.data = data

    def __repr__(self):
        return f"<MonitorSubsystem {self.name}>"


class XXMonitorPoint:
    """Represents a monitor point — flattened list or primitive values."""
    def __init__(self, name, values):
        self.name = name
        self.values = values  # list of dicts, possibly mixed primitives

    def __repr__(self):
        return f"<XXMonitorPoint {self.name}: {len(self.values)} entries>"


class MonitorSystem(Tree):
    """
    A monitoring system tree built from a JSON structure.
    Each node is either a MonitorSubsystem (for dicts)
    or a MonitorPoint (for lists or primitive values).
    """

    def __init__(self, json_data):
        super().__init__()
        self.create_node(tag="root", identifier="root",
                         data=MonitorSubsystem("root", json_data))
        self._build_tree("root", json_data)

    # -------------------------------------------------------
    # Recursive builder
    # -------------------------------------------------------
    def _build_tree(self, parent_id, data):
        if not isinstance(data, dict):
            raise TypeError("Root of a MonitorSystem must be a JSON object (dict).")

        for key, value in data.items():
            if isinstance(value, dict):
                if "smax_type" in value.keys():  
                    # we are at the bottom leaf and it is a monitor point.
                    mp = MonitorPoint(name=key,canonical_name=f"{parent_id}.{self[parent_id].data.name}.{key}",**value)
                    node_id = f"{parent_id}/{self[parent_id].data.name}_monitor"
                    node_id = mp.canonical_name
                    self.create_node(tag=mp.canonical_name, identifier=node_id,
                                     parent=parent_id, data=mp)
                else:                                                    
                    node_id = f"{parent_id}/{key}_subsystem"
                                                                          
                    self.create_node(tag=key, identifier=node_id,
                                     parent=parent_id, data=MonitorSubsystem(key, value))
                    self._build_tree(node_id, value)

            elif isinstance(value, list):
                mp_values = self._flatten_list(value)
                node_id = f"{parent_id}/{key}_monitor"
                self.create_node(tag=f"{key}_monitor", identifier=node_id,
                                 parent=parent_id, data=MonitorPoint(f"{key}", mp_values))

            #else:
                # Primitive values grouped under one MonitorPoint per subsystem level
            #    existing = [n for n in self.children(parent_id)
            #                if isinstance(n.data, MonitorPoint)
            #                #and n.data.name.endswith("_monitor")
            #                and n.data.name.startswith(self[parent_id].data.name)]
            #    if existing:
            #        # Append new primitive to existing MonitorPoint
            #        existing[0].data.values[0][key] = value
           #     else:
            #        mp = MonitorPoint(f"{self[parent_id].data.name}_monitor", [{key: value}])
            #        node_id = f"{parent_id}/{self[parent_id].data.name}_monitor"
            #        self.create_node(tag=mp.name, identifier=node_id,
            #                         parent=parent_id, data=mp)

    # -------------------------------------------------------
    # Helper: flatten mixed lists into list of dicts
    # -------------------------------------------------------
    def _flatten_list(self, lst):
        flattened = []
        for idx, item in enumerate(lst):
            if isinstance(item, dict):
                flattened.append(item)
            elif isinstance(item, list):
                for sub_idx, sub_item in enumerate(item):
                    flattened.append({f"list_{idx}_{sub_idx}": sub_item})
            else:
                flattened.append({f"item_{idx}": item})
        return flattened

    # -------------------------------------------------------
    # Optional convenience methods
    # -------------------------------------------------------
    def summary(self):
        """Print a simple hierarchy summary."""
        self.show(key=lambda n: n.tag)

    def details(self):
        """Print detailed data for every node."""
        for node in self.all_nodes_itr():
            print(f"{node.identifier}: {node.data}")





# -------------------------------------------------------
# Example usage
# -------------------------------------------------------
if __name__ == "__main__":
    # Example JSON file
    json_data = read_json_file("../src/slama/conf/smax.json")

    system = MonitorSystem(json_data)

    print("\n📂 Monitor System Hierarchy:\n")
    system.summary()

    print("\n🔍 Detailed Node Data:\n")
    system.details()

