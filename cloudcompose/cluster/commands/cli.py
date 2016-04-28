import click
from cloudcompose.cluster.cloudinit import CloudInit
from cloudcompose.cluster.aws.cloudcontroller import CloudController
from cloudcompose.config import CloudConfig

@click.group()
def cli():
    pass

@cli.command()
def up():
    """
    creates a new cluster
    """
    cloud_config = CloudConfig()
    cloud_controller = CloudController()
    cloud_controller.up(cloud_config)

@cli.command()
def down():
    """
    destroys an existing cluster
    """
    print "in cluster down command"

@cli.command()
def build():
    """
    builds the cloud_init script
    """
    cloud_config = CloudConfig()
    cloud_init = CloudInit()
    print cloud_init.build(cloud_config)
