import signal
import sys
import os
import json
import logging
from urllib import request
from time import sleep

import boto3

INSTANCE_METADATA_ENDPOINT = "http://169.254.169.254/latest/meta-data/"
TASK_METADATA_ENDPOINT = os.environ["ECS_CONTAINER_METADATA_URI"]
CHECK_INTERVAL = 5  # As seconds

# Initialize logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
h = logging.StreamHandler(sys.stdout)  # Do not buffer, output stdout immediately.
h.flush = sys.stdout.flush
logger.addHandler(h)

# Get region
res = request.urlopen(f"{INSTANCE_METADATA_ENDPOINT}/placement/availability-zone")
region = res.read().decode("utf-8")[:-1]  # Extract region from AZ by deleting last character.

# Get instance id
res = request.urlopen(f"{INSTANCE_METADATA_ENDPOINT}/instance-id")
instance_id = res.read().decode("utf-8")

# Get cluster name
res = request.urlopen(f"{TASK_METADATA_ENDPOINT}/task")
content = res.read().decode("utf-8")
json = json.loads(content)
cluster_name = json["Cluster"]

# Get container instance id
ECS = boto3.client("ecs", region_name=region)
res = ECS.list_container_instances(cluster=cluster_name, filter=f"ec2InstanceId=={instance_id}")
container_instance_arn = res["containerInstanceArns"][0]


def wait_all_task_stop(num, frame):
    logger.info(f"ecs-instance-watcher on {instance_id}({container_instance_arn}) was trapped SIGTERM.")

    # Get DAEMON service ids
    res = ECS.list_services(cluster=cluster_name, schedulingStrategy="DAEMON")
    daemon_service_arns = res["serviceArns"]
    res = ECS.describe_services(cluster=cluster_name, services=daemon_service_arns)
    daemon_service_ids = [svc["deployments"][0]["id"] for svc in res["services"]]
    logger.info(f"DAEMON service ids: {daemon_service_ids}")

    # Execute only when instance status is DRAINING.
    res = ECS.describe_container_instances(cluster=cluster_name, containerInstances=[container_instance_arn])
    status = res["containerInstances"][0]["status"]
    logger.info(f"Instance status: {status}")
    if status != "DRAINING":
        logger.info("Instance status is not DRAINING, quit soon.")
        sys.exit(0)

    # Check running task
    while True:
        retry = False
        running_task_arns = ECS.list_tasks(cluster=cluster_name,
                                           containerInstance=container_instance_arn,
                                           desiredStatus="RUNNING")["taskArns"]
        logger.info(f"Running task arns: {running_task_arns}")

        if len(running_task_arns) == 0:
            break

        running_tasks = ECS.describe_tasks(cluster=cluster_name, tasks=running_task_arns)["tasks"]
        logger.info(f"Running tasks: {running_tasks}")

        for task in running_tasks:
            if task["startedBy"] not in daemon_service_ids:
                logger.info(f"Task is still running, check again after {CHECK_INTERVAL} sec.")
                retry = True
                sleep(CHECK_INTERVAL)
                break
        if retry is False:
            break

    # Check stopped task
    while True:
        retry = False
        stopped_task_arns = ECS.list_tasks(cluster=cluster_name,
                                           containerInstance=container_instance_arn,
                                           desiredStatus="STOPPED")["taskArns"]
        logger.info(f"Stopped task arns: {stopped_task_arns}")
        stopped_tasks = ECS.describe_tasks(cluster=cluster_name, tasks=stopped_task_arns)["tasks"]
        logger.info(f"Stopped tasks: {stopped_tasks}")

        for task in stopped_tasks:
            # If except of DAEMON services lastStatus is not stopped, task is still contining execution after accept SIGTERM.
            if task["startedBy"] not in daemon_service_ids and task["lastStatus"] != "STOPPED":
                logger.info(f"Desired status is changed STOPPED, but lastStatus is still RUNNING. Check again after {CHECK_INTERVAL} sec.")
                retry = True
                sleep(CHECK_INTERVAL)
                break
        if retry is False:
            break

    logger.info("All tasks are stopped, quit soon.")
    sys.exit(0)


signal.signal(signal.SIGTERM, wait_all_task_stop)

while True:
    sleep(CHECK_INTERVAL)
