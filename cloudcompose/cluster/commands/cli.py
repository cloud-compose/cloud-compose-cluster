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
    cloud_init = CloudInit(cloud_config)
    cloud_controller = CloudController(cloud_config)
    cloud_controller.up(cloud_init)

@cli.command()
def down():
    """
    destroys an existing cluster
    """
    cloud_config = CloudConfig()
    cloud_controller = CloudController(cloud_config)
    cloud_controller.down()

@cli.command()
def build():
    """
    builds the cloud_init script
    """
    cloud_config = CloudConfig()
    cloud_init = CloudInit(cloud_config)
    print cloud_init.build()
