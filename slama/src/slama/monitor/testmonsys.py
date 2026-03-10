#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Sep 30 14:07:57 2025

@author: mpound
"""
import json
from slama.monitor.monitorpoint import MonitorPoint
from slama.monitor.monitorsystem import MonitorSubsystem, MonitorSystem
from pathlib import Path

import json
from pathlib import Path
path = Path("../conf/smax.json")
mpdefs = json.load(open(path,"r"))
monsys = MonitorSystem()
topparent = "SMA Monitor System"
def createitems(mpdefs, monsys, parent):

    for k,v in mpdefs.items():
        if all(isinstance(value, dict) for value in v.values()):
            print(f"recursing {k}")         
            createitems(v,monsys, parent=k)
        else:
            print(f"instantiating monitory subsystem {k}") ## too far
            monsys[k] = MonitorSubsystem(k,parent, v)  
            
class DictNode:
    """Represents a JSON object (dictionary)."""
    def __init__(self, name, data):
        self.name = name
        self.children = []

        for key, value in data.items():
            if isinstance(value, dict):
                self.children.append(DictNode(key, value))
            elif isinstance(value, list):
                self.children.append(ListNode(key, value))
            else:
                self.children.append(ValueNode(key, value))

    def __repr__(self):
        return f"<DictNode {self.name}: {len(self.children)} children>"


class ListNode:
    """Represents a JSON array."""
    def __init__(self, name, data):
        self.name = name
        self.children = []
        for idx, item in enumerate(data):
            if isinstance(item, dict):
                self.children.append(DictNode(f"{name}[{idx}]", item))
            elif isinstance(item, list):
                self.children.append(ListNode(f"{name}[{idx}]", item))
            else:
                self.children.append(ValueNode(f"{name}[{idx}]", item))

    def __repr__(self):
        return f"<ListNode {self.name}: {len(self.children)} items>"


class ValueNode:
    """Represents a leaf key-value pair."""
    def __init__(self, key, value):
        self.key = key
        self.value = value

    def __repr__(self):
        return f"<ValueNode {self.key}={self.value!r}>"


def build_tree(json_data):
    """Builds the class hierarchy from a JSON structure."""
    if isinstance(json_data, dict):
        return DictNode("root", json_data)
    elif isinstance(json_data, list):
        return ListNode("root", json_data)
    else:
        return ValueNode("root", json_data)


def read_json_file(file_path):
    """Reads a JSON file and returns the parsed data."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {file_path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    # Example usage
    json_data = read_json_file("../conf/smax.json")
    root = build_tree(json_data)
    print(root)

    # Optional: pretty print the tree
    def print_tree(node, indent=0):
        print("  " * indent + repr(node))
        if hasattr(node, "children"):
            for child in node.children:
                print_tree(child, indent + 1)

    print_tree(root)


        