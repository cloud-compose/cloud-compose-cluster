import click
from cloudcompose.cluster.cloudinit import CloudInit
from cloudcompose.cluster.aws.cloudcontroller import CloudController
from cloudcompose.config import CloudConfig

@click.group()
def cli():
    pass

@cli.command()
@click.option('--cloud-init/--no-cloud-init', default=True)
def up(cloud_init):
    """
    creates a new cluster
    """
    cloud_config = CloudConfig()
    ci = None

    if cloud_init:
        ci = CloudInit(cloud_config)

    cloud_controller = CloudController(cloud_config)
    cloud_controller.up(ci)

@cli.command()
def down():
    """
    destroys an existing cluster
    """
    cloud_config = CloudConfig()
    cloud_controller = CloudController(cloud_config)
    cloud_controller.down()

@cli.command()
def cleanup():
    """
    deletes launch configs and auto scaling group
    """
    cloud_config = CloudConfig()
    cloud_controller = CloudController(cloud_config)
    cloud_controller.cleanup()

@cli.command()
def build():
    """
    builds the cloud_init script
    """
    cloud_config = CloudConfig()
    cloud_init = CloudInit(cloud_config)
    print cloud_init.build()
