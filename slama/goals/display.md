# Task Goal

Add to slama package the capability to display SMA monitor data in real time on the web. 

## Details

- Different web pages would display different monitor subsystems or collections of monitor points from different subsystems.  
- Most data will be displayed in table format, but there may be individual free-standing cells.  
- The table cells may contain numeric or string data.
- Each cell in the table maps to one Monitor Point
- Monitor system and monitor point reads should use the API developed in monitor module.
- The client can change the update interval.
- The client can change the fields displays.
- The web pages will be public facing with ~100 users.

**This is important:** It should be easy to configure and create new displays, for instance via a json representation. 

- Think about what technology stack would be best suited to this problem.

## Background

- A prototype can be found in /bigdisk/src/antenna-monitor. You should review that code before proceeding, but you do not have to use it if there is a better design.

