# Cloud Compose cluster plugin
Cloud Compose cluster plugin simplifies the process of running Docker images on cloud servers. To use Cloud Compose you need three files:

1. docker-compose.yml for local testing
1. docker-compose.override.yml for overriding values to support cloud server
1. cluster.sh script for initializing the cloud server

For an example project that uses Cloud Compose see (Docker MongoDB)[https://github.com/washingtonpost/docker-mongodb].

Once you have the configuration files created run the follow commands to start up the cluster. 
```
cd my-configs
pip install cloud-compose cloud-compose-cluster
pip freeze -r > requirements.txt
cloud-compose cluster up
```

Although the cluster plugins is designed to be cloud agnostic, AWS is the only cloud provider currently supported.  Support for other cloud providers is welcomed as pull requests.

### AWS backend
If you are using the AWS backend the cluster plugin uses the (Boto)[http://boto3.readthedocs.io/en/latest/] client which requires the following environment variables:

* AWS_REGION
* AWS_ACCESS_KEY_ID
* AWS_SECRET_ACCESS_KEY

If you have multiple AWS accounts it is convenient to use the (Envdir)[https://pypi.python.org/pypi/envdir] project to easily switch between AWS accounts.


## Configuration 
To understand the purpose of each configuration file consider the follow examples with an explanation of each element.
### cloud-compose.yml
```yaml
cluster:
  name: ${CLUSTER_NAME}
  search_path:
    - docker-mongodb
    - docker-mongodb/cloud-compose/templates
  aws:
    ami: ${IMAGE_ID}
    username: ${IMAGE_USERNAME}
    terminate_protection: false
    security_groups: ${SECURITY_GROUP_ID}
    vpc: ${VPC_ID}
    ebs_optimized: false
    instance_type: t2.medium
    keypair: drydock
    volumes:
      - name: root
        size: 30G
      - name: docker
        size: 20G
        block: /dev/xvdz
        file_system: lvm2
        meta:
          group: docker
          volumes:
            - name: data 
              size: 19G
            - name: metadata
              size: 900M 
      - name: data
        size: 10G
        block: /dev/xvdc
        file_system: ext4
        meta:
          format: true
          mount: /data/mongodb
    tags:
      datadog: monitored
    nodes:
      - id: 0
        ip: ${CLUSTER_NODE_0_IP}
        subnet: ${CLUSTER_NODE_0_SUBNET}
      - id: 1
        ip: ${CLUSTER_NODE_1_IP}
        subnet: ${CLUSTER_NODE_1_SUBNET}
      - id: 2
        ip: ${CLUSTER_NODE_2_IP}
        subnet: ${CLUSTER_NODE_2_SUBNET}
```

#### name
The ``name`` is the unique name of this cluster which is also added as a ClusterName tag to each server created in the cluster.

### search_path 
The ``search_path`` is the directories that will be examined when looking for configuration files like the ``cluster.sh`` file and the `` docker-compose.override.yml``.

### AWS
The AWS section contains information needed to create the cluster on AWS.

#### ami
The ``ami`` is the Amazon Machine Image to start the EC2 servers from before installing the Docker containers that you want to run on these servers.

#### username
The ``username`` is used by the ``cluster.sh`` script to start the Docker containers using that user account.

#### terminate_protection (optional)
The ``terminate_protection`` is an EC2 feature that prevents accidently termination of servers. If this value is not provided it defaults to true, which is the recommended setting for production clusters.

#### security
The list of ``security_groups`` that should be added to the EC2 servers.

#### vpc
The ``vpc`` identifier to launch the EC2 servers in.

#### ebs_optimized (optional)
Set ``ebs_optimized`` to true if you want EC2 servers with this featured turned on. The default value is false.

#### instance_type
The ``instance_type`` you want to use for the EC2 servers.

#### keypair
The ``keypair`` is the SSH key that will be added to the EC2 servers.

#### volumes
The ``volumes`` is a list of volumes that should be added to the instance. All volumes have a ``size`` attribute which is a number followed by a unit of M, G, or T for megabytes, gigabytes, or terabytes.


#### root
The ``root`` volume is the main volume for the server. 

#### docker
Centos/RHEL servers that use Docker with device-mapper and LVM2, can create a LVM2 volume for use in configuring Docker image and metadata storage.

#### data
If you need to keep significant data on the instance it is recommend to create a data volume rather than putting the data on this volume because it makes restores much easier. The root volume does not accept any other parameters besides size. The data volume should also have mount point which is then mounted in your Docker container as a volume.

### tags
Additional ``tags`` that should be added to the EC2 instance can be added to this section.

### nodes
The ``nodes`` is a list of servers for the cluster.  Autoscaling groups are not recommended for database server because the cluster membership can changing quickly which can lead to data loss if the replication is not able to catch up in time. Since many database work better with static IP addresses, this is the default behavior of the cluster plugin. It is recommend that a separate subnet be just for servers using static IP addresses. Then add a node in each of these subnets and make sure you are running in at least 2-3 availability zones for maximum redundancy. 

## Extending
The cluster plugin was designed to support many different server platforms including MongoDB, Kafka, and Zookeeper, but it does require some scripting and configuration.  See the (Docker MongoDB)[https://github.com/washingtonpost/docker-mongodb] for an example project.

You can add additional server platforms by creating a similar project and adapting the configuration files as needed.

## Contributing 
To work on the code locally, checkout both cloud-compose and cloud-compose-cluster to the same parent directory. Then use a virtualenv and pip install editable to start working on them locally.
```
mkvirtualenv cloud-compose
pip install --editable cloud-compose
pip install --editable cloud-compose-cluster
```

Make sure to add unit tests for new code. You can run them using the standard setup tools command:

```
python setup.py test
```
