# Netbox Automation

A program for automating the addition of network devices to Netbox.
Program read the file with hosts and then scan each host using pysnmp.

## How to run

 1. Install Netbox
    Install Netbox using the [official documentation](https://netbox.readthedocs.io/en/stable/).
 2. Create API-Key 
 3. Clone this repo
  ```
git clone git@github.com:Shabosun/netbox-automation.git
  ``` 
 4. Create virtual environment
 ```
 python -m venv venv
 source venv/bin/activate
 ```
 6. Enter your data to .env file
 7. Run this program
 ```
python.exe main.py
 ```
I used some elements from [this repository](https://github.com/woohung/netbox_automation_learning/tree/main) when writing this code.
