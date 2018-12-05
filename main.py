# -*- coding: utf-8 -*-
###
# (C) Copyright (2018) Hewlett Packard Enterprise Development LP
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
###

import sys
if sys.version_info < (3, 6):
	print('Incompatible version of Python, Please use Python ver 3.6 and above..!')
	sys.exit(1)

import argparse
import json
import ssl
import logging

import multiprocessing as mp
from time import sleep
import time
from hpOneView.oneview_client import OneViewClient
#from hpOneView import *
from functools import partial
import amqplib.client_0_8 as amqp
from ov_client.oneview_client import *
from common.send_nrdp import *
# from internal.polling_threads import *
from internal.polling_processes import *
from internal.scmb_utils import *

global tim1, dat, count
tim1=time.strftime("%H:%M:%S")
dat = time.strftime("%d-%m-%Y")
count=0



# Global variable for callback
config = {}
syslog_file = "oneview_splunk_logs/oneview_alerts_splunk.log"

def callback(channel, msg):
	global config
	logging.debug("callback.......")
	logging.debug("msg.delivery_tag: %s", msg.delivery_tag)
	logging.debug("msg.consumer_tag: %s", msg.consumer_tag)
		
	# ACK receipt of message
	channel.basic_ack(msg.delivery_tag)

	# Convert from json into a Python dictionary
	content = json.loads(msg.body)
	
	# Add a new attribute so that the server side can recognize from which appliance it is this message comes from.
	content['messageHost'] = config['oneViewIP'];
	# headers = {"Content-Type" : "application/json", "Accept" : "application/json"}

	logging.debug("CONTENT %s", content)
	#create_syslog(content["resource"])

	resource = content['resource']
	if(('alertState' in resource) and ('severity' in resource)):
		if((('Active' == resource['alertState']) or ('Cleared' == resource['alertState'])) and ('Critical' == resource['severity']) ):
			print(resource)
			global count
			count = count + 1
			try:
				print("Critical Created!")
				create_syslog(resource)
			except:
				print("Error in logging the alert")

	# Cancel this callback
	if msg.body == 'quit':
		channel.basic_cancel(msg.consumer_tag)


##function to convert alerts into  syslog format
def create_syslog(json_obj):
	#version=count
	global count
	fo = open(syslog_file, "a")
	created_date = json_obj['created']
	severity = json_obj['severity']
	uri = json_obj['uri']
	associated_rsc = json_obj['associatedResource']['associationType']+json_obj['associatedResource']['resourceCategory']+json_obj['associatedResource']['resourceName']+json_obj['associatedResource']['resourceUri']+json_obj['alertState']+json_obj['physicalResourceType']
	desc=json_obj['correctiveAction']
	if desc == None :
		Converted_str=convert_string(desc)
		desc=json_obj['description']+Converted_str
	else:
		desc=json_obj['description']+json_obj['correctiveAction']
	fo.write('OneView_Alerts-'+str(count)+" "+str(created_date)+" "+str(severity)+" "+str(uri)+" "+"-"+str(associated_rsc)+" "+"["+desc+"]"+" "+"\n")


##function for converting None type to string type
def convert_string(value):
	new_value = str(value)
	return new_value

def recv(host, route):
	logging.info("recv - Entry %s", route)

	# Create and bind to queue
	EXCHANGE_NAME = 'scmb'
	dest = host + ':5671'

	# Setup our ssl options
	ssl_options = ({'ca_certs': 'certs/' + host + '-caroot.pem',
					'certfile': 'certs/' + host + '-client.pem',
					'keyfile': 'certs/' + host + '-key.pem',
					'cert_reqs': ssl.CERT_REQUIRED,
					'ssl_version' : ssl.PROTOCOL_TLSv1_1,
					'server_side': False})

	logging.info(ssl_options)

	# Connect to RabbitMQ
	conn = amqp.Connection(dest, login_method='EXTERNAL', ssl=ssl_options)
	
	ch = conn.channel()
	qname, _, _ = ch.queue_declare()
	routeArray = route.split(';')
	for each in routeArray:
		logging.info("SCMB bind to " + each)
		ch.queue_bind(qname, EXCHANGE_NAME, each)
	ch.basic_consume(qname, callback=partial(callback, ch))
	print("\nConnection established to SCMB. Listening for alerts...\n")
	# Start listening for messages
	while ch.callbacks:
		ch.wait()

	ch.close()
	conn.close()
	logging.info("recv - Exit")


##################################################################
# Main function.
# 
##################################################################
def main():

	global config
	
	parser = argparse.ArgumentParser(add_help=True, description='Usage')
	parser.add_argument('-i','--input_file',dest='input_file', required=True,
						help='Json file containing oneview details')
		
	# Check and parse the input arguments into python's format
	inputFile = parser.parse_args()
	# Parsing file for details  
	with open(inputFile.input_file) as data_file:	
		inputConfig = json.load(data_file)
	# get the logging level
	loggingLevel = inputConfig["logging_level"].upper()
	
	try:
		# Validate the data in the OneView config files.
		oneViewDetails = inputConfig["oneview_config"]
	
	except Exception as e:
		# We will not be able to log this message since logging is not yet initialized, hence printing
		print("Error in config files. Check and try again.")
		print(e)
		sys.exit(1)

	# Initialize logging
	initialize_logging(oneViewDetails['host'], loggingLevel)

	# Valid alert types sent by Oneview. This is used to compare the user input "alert_type" from oneview.json file
	alertTypes = ['Ok','Warning','Critical','Unknown']
	hardwareTypes = ['server-hardware','enclosures','interconnects','sas-interconnects','logical-interconnects']

	# validate OneView details
	ret = validate_oneview_details(oneViewDetails)
	if ret == 0:
		logging.info("Successfully validated input file")
	
	# validate hardware types entered
	ret = validate_hardware_category(oneViewDetails,hardwareTypes)
	if ret == 0:
		logging.info("Successfully validated input file")
	
	# validate alert types entered
	ret = validate_alert_types(oneViewDetails, alertTypes)	
	if ret == 0:
		logging.info("Successfully validated input file")

	if not loggingLevel:
		logging.info("\"logging_level\" is not provided, taken\"WARNING\" as default.")
	

	# append global dict with required values
	config['oneViewIP'] = oneViewDetails['host']
	config['alertHardwareTypes'] = oneViewDetails["alert_hardware_category"].split(':')
	inputAlertTypes = oneViewDetails["alert_type"].split(':')
	config['inputAlertTypes'] = [x.lower() for x in inputAlertTypes] # User interested alert types


	# Logging input details.
	logging.info('OneView args: host = %s, alias = %s, route = %s, action = %s, process_onetime_alerts = %s, events_dated_from = %s', \
		oneViewDetails["host"], oneViewDetails["alias"], oneViewDetails["route"], oneViewDetails["action"], \
		oneViewDetails["process_onetime_alerts"], oneViewDetails["events_dated_from"])
		
	# Esatblish connection to OneView
	if oneViewDetails["action"] == "start":
		logging.debug("Attempting to establish connection with OV SCMB")
		logging.debug("Arguments: " + str(oneViewDetails))

		ovConfig = {
			"ip": oneViewDetails["host"],
			"credentials": {
				"userName": oneViewDetails["user"],
				"password": oneViewDetails["passwd"]
			}
		}

		try:
			oneview_client = OneViewClient(ovConfig)
			acceptEULA(oneview_client)
			logging.info("Connected to OneView appliance : {}".format(oneViewDetails["host"]))
		#except HPOneViewException as e:
		except Exception as e:
			#logging.error("Error connecting to appliance: msg: %s", e.msg)
			logging.error("Error connecting to appliance. Check for OneView details in input json file.")
			logging.error(e)
			sys.exit(1)

		# Create certs directory for storing the OV certificates
		initialize_certs()

		# Download the certificates
		getCertCa(oneview_client, oneViewDetails["host"])
		getRabbitKp(oneview_client, oneViewDetails["host"])
		

		# Start listening for messages.
		recv(oneViewDetails["host"], oneViewDetails["route"])
		

	elif oneViewDetails["action"] == "stop":
		# Stop SCMB connection for this appliance
		logging.info("TODO: stop action implementation")
		# stopSCMB(oneViewDetails.host)
	else:
		# Do nothing and exit
		logging.error("Missing or invalid option for action in oneview.json; It should be start/stop.")
		print("Missing or invalid option for action in oneview.json; It should be start/stop.")
		

if __name__ == '__main__':
	## Create a thread pool with 5 worker threads
	#
	#mpThreadPool = mp.Pool(5)
	sleep(0.1)
	
	sys.exit(main())
