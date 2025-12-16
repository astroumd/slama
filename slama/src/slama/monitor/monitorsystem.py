#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jul 16 08:19:27 2025

@author: mpound
"""
from abc import ABC, abstractmethod
from typing import Any, Union
import astropy.units as u
from astropy.time import Time
import numpy as np
from smax import SmaxRedisClient
import smax.smax_data_types as smaxdt
from pathlib import Path
import json
from collections import UserList
from enum import IntEnum, auto
from numbers import Number
from .monitorpoint import MonitorPoint
import treelib



class MonitorSubsystem:
    """Represents a JSON object (dictionary)."""
    def __init__(self, name, data):
        self.name = name
        self.children = []

        # Collect primitive key/values at this level
        primitive_values = {}
        for key, value in data.items():
            if isinstance(value, dict):
                # Nested object → new subsystem
                self.children.append(MonitorSubsystem(key, value))
            #elif isinstance(value, list):
            #    self.children.append(MonitorPoint(f"{key}_monitor", {"values": value}))
            else:
                # Collect primitive values for grouping later
                primitive_values[key] = value

        # If any primitives were found, group them into a MonitorPoint
        if primitive_values:
            self.children.append(MonitorPoint(f"{name}_monitor", primitive_values))

    def __repr__(self):
        return f"<MonitorSubsystem {self.name}: {len(self.children)} children>"

        
class MonitorSystem(treelib.Tree):
    def __init__(self, path: Path):
        super().__init_()
        self._json_data = self._read_json_file(path)
        self._subsystems = self._build_tree(self._json_data)
        
    def read_json_file(self, file_path):
        """Reads a JSON file and returns the parsed data."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"JSON file not found: {file_path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)        

def flatten_list(lst):
    """
    Flattens mixed-type lists (dicts, lists, primitives)
    into a list of dict entries.
    """
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


    def __getitem__(self,k):
        return self._subsystems[k]
    def __setitem__(self,k,value):
        self._subsytems[k] = value
