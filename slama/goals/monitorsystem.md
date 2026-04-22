Marc would like you to plan code that can:

* Instantiate a Monitor System from the hierarchical file conf/smax.json.  
* The Monitor Points should be based SmaxVarBase.
* The Monitor System should be able to read and write to a valkey/redis database via SmaxRedisClient
* monitorsystem.py is prototype code for this.  You can change that or write completely new code.
* You can use treelib to read the hierachical json file or propose an alternative if you think there is a better one.  
* Consider if any additional functionality is needed 
* Note that smax.json does not yet contain Validity data for individual monitor points, but eventually it will.  
* Assume a valkey (redis) server will be running on port 6380
* Ask me if you are uncertain about anything
