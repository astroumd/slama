# Task Goal
Create a Fault System that watches the validities of a critical list of monitor points, discovers the root faults,  and trigger actions if required.  The fault system should run in a loop, continually watching the monitor system as it changes.  Actions should be configurable, but can include logging to a file, sending an email, triggering a physical alarm.   Only root faults should trigger actions. 

## Description
Because the monitor point system is hierarchical, leaf monitor points be in error states because of a node higher up in the tree.  A fault is indicated if a monitor point Validity has state INVALID_NO_DATA, INVALID_NO_HW, INVALID_HW_BAD, VALID_ERROR, VALID_ERROR_LOW, or VALID_ERROR_HIGH. If a fault occurs, it is important to know what the root fault is. The critical list of monitor points may therefore be represented by a directed acyclic graph. 

The DAG of critical points should be configured using a human readable text file format such as json or XML.   The configuration should include: 

 - the critical monitor point names
 - a transient filter variable indicating how long each monitor point needs to be in an invalid state before triggering a fault
 - the configuration should not be unnecessarily repetitive and may use the same or similar construct as the "\_\_each\_\_", "over", "template" construct as conf/smax.json.

The fault system will contain an object representation of the DAG and be able to reconfigure it's in-memory structure.

## Fault System API requirements

 - The API should include a method to ignore certain faults.  It could take two parameters
    - A string value to match against the critical monitor point list . The string may include wildcards.
    - An int value for how many seconds to ignore it (Default:0 which means ignore until notified otherwise).
 - The API should include a method to stop ignoring faults that were previously ignored. The parameter would be a string that may include wildcards.
 - The API should allow setting or changing the loop interval in seconds over which the monitor system is checked.
 
