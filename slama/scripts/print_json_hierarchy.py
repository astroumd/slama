#!/usr/bin/env python3
"""
Print out a sorted json hierarchy with or without final leaves.  Useful for visual understanding of smax.json and variants

Usage
   uv run scripts/print_json_hierarchy.py [--file JSON_FILE] [--leaves] 
"""
import argparse
import json

def sort_data_recursively(data):
    """
    Recursively sorts dictionaries by key and lists (if containing dicts) 
    to ensure alphabetical traversal.
    """
    if isinstance(data, dict):
        # Sort dictionary items by key alphabetically
        return {k: sort_data_recursively(v) for k, v in sorted(data.items())}
    elif isinstance(data, list):
        # Sort list items. 
        # Note: If the list contains mixed types (dicts and primitives), 
        # this sorts dicts within the list but keeps primitive order unless specified.
        # To strictly sort primitives too, you'd need type checking.
        # Here we assume we want to process list items in order, 
        # but if you want to sort the list itself, uncomment the next line:
        # data = sorted(data, key=lambda x: str(x)) 
        return [sort_data_recursively(item) for item in data]
    else:
        return data

def print_hierarchy(data, indent=0, print_leaves=True):
    """
    Prints the hierarchy of a JSON object.
    Expects 'data' to be pre-sorted if alphabetical order is required.
    """
    prefix = "  " * indent
    
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                print(f"{prefix}Key: {key}")
                print_hierarchy(value, indent + 1, print_leaves)
            else:
                # This is a leaf node
                if print_leaves:
                    print(f"{prefix}Key: {key} -> Value: {value}")
                #else:
                #    print(f"{prefix}Key: {key} (Leaf)")
    elif isinstance(data, list):
        for index, item in enumerate(data):
            if isinstance(item, (dict, list)):
                print(f"{prefix}Index: {index}")
                print_hierarchy(item, indent + 1, print_leaves)
            else:
                if print_leaves:
                    print(f"{prefix}Index: {index} -> Value: {item}")
                else:
                    print(f"{prefix}Index: {index} (Leaf)")

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", "-f", required=True, 
                        help="input JSON file path")
    parser.add_argument("--leaves", action="store_true",
                        help="Print leaves, default is don't print")
    args = parser.parse_args()
    print_hierarchy(data=sort_data_recursively(json.load(open(args.input))), print_leaves=args.leaves)
if __name__ == "__main__":
    main()
