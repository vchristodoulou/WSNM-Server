# Server for Wireless Sensor Networks Management

Built with Python <br>
Server holds the overall system functionality and status. This is done based on information received from gateways.
Server is responsible for:
* Processing requests from application.
* Forwarding corresponding requests to the control-specific gateways nodes.
* Forwarding debug messages produced by nodes in the application.

![WSNM_architecture](../media/WSNM_architecture.png?raw=true)

### Installation
1) Install pip (pip3)
    - `sudo apt install python3-pip`
2) Install pipenv
    - `sudo -H pip3 install -U pipenv`
    - Install dependencies
        - `pipenv install` (from Pipfile)
3) Install MongoDB
    - `sudo apt install mongodb`

### Configuration
You can adjust the project settings with the following files:
- `src/server.cfg`
- `src/.env` (ftp)
