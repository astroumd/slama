# Goal
Come up with an extension to our JSON display format to accomodate tabular display of vector variables.

# Context
Some of the monitor points from SMAX/Redis database are arrays. These may be single-axis or multi-axis arrays.
For instance,   
`DSM:obscon:BDC48_X:DSM_BDC_VVA1_CTRL_READBACK_V8_F` is length 8, one value for each antenna.  While `
DSM:obscon:BDC48_X:DSM_BDC_TEMP_V2_V8_F` is a 2x8 array, for two devices times 8 antennas.   

Sometimes we don't want to display every member of a vector, for instance in `DSM:corcon:CORR_PACU_STATUS_X:DIGITAL_RACK_RETURN_AIR_TEMP_V9_F`the first element is ignored.

Currently, a vector is displayed  in a single cell.  We need a away 
The name of the variable will often indicate vector size, e.g. "V8_F" is a 8-length vector of floats, V2_V8_F is a 2x8 vector of floats.  However, it is unclear if the naming of variables in the database is consistent, so for now we can't rely on the variable name to inform us of the shape of its  contents. 

# Task

Devise at least two ways that the JSON file and web display python code can be changed to allow display of arrays in table format.  It should allow for the vector names to be either row or column headers and have a way to define the column or row header based on the array index, e.g. "Antenna{index}",  "Chassis{index-1}, "Foobar{index+3}".   There should be a way to choose which elements of a variable are displayed, with a default being all elements. It should be allowed to display all elements for one array and some elements for another array in the same table as long as the cell count is the same.

Describe the pros and cons of each way you come up with for solving this task.   Ask Marc if you have questions.   Do not implement anything yet, we are just planning.