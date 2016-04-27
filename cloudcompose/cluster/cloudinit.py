from jinja2 import Template
import yaml
from pprint import pprint

class CloudInit():
    def __init__(self, config, template):
        self.config = config
        self.template = template

    def build(self):
        template_obj = Template(open(self.template).read())
        config_data = None
        with open(self.config, 'r') as yaml_file:
            config_data = yaml.load(yaml_file)
        pprint(config_data)
        return template_obj.render(config_data['cluster'])

